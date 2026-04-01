import frappe
import requests
import json
import uuid
import math
from datetime import datetime
from frappe.utils import now_datetime, add_to_date

# ================= SAFE LOGGING UTILITY =================
def safe_log(message, title=None, log_type="info"):
    """
    Safe logging that prevents CharacterLengthExceededError
    """
    message_str = str(message)
    if len(message_str) > 200:
        message_str = message_str[:200] + "..."
    
    logger = frappe.logger()
    
    if log_type == "error":
        logger.error(f"{title or 'ERROR'}: {message_str}")
        if title and "Error" in title:
            simple_title = title[:80] if len(title) > 80 else title
            simple_msg = message_str[:100] if len(message_str) > 100 else message_str
            frappe.log_error(simple_msg, simple_title)
    elif log_type == "warning":
        logger.warning(f"{title or 'WARNING'}: {message_str}")
    elif log_type == "debug":
        logger.debug(f"{title or 'DEBUG'}: {message_str}")
    else:
        logger.info(f"{title or 'INFO'}: {message_str}")
# =========================================================

def get_delivery_gln_from_sales_order(sales_order):
    """Get delivery GLN from Sales Order by looking up the Delivery Point."""
    try:
        delivery_point_name = sales_order.get('custom_delivery_point')
        
        if delivery_point_name:
            delivery_point = frappe.get_doc("Delivery Point", delivery_point_name)
            floriday_gln = delivery_point.get('custom_floriday_delivery_id')
            
            if floriday_gln:
                safe_log(f"Found GLN {floriday_gln} from Delivery Point {delivery_point_name}", 
                        "Delivery Point GLN Lookup", "info")
                return floriday_gln
            else:
                safe_log(f"Delivery Point {delivery_point_name} has no custom_floriday_delivery_id set", 
                        "Missing GLN Warning", "warning")
                return None
        else:
            safe_log(f"Sales Order {sales_order.name} has no delivery point set", 
                    "No Delivery Point", "debug")
            return None
            
    except Exception as e:
        safe_log(f"Error getting GLN from delivery point: {str(e)}", 
                "Delivery Point GLN Error", "error")
        return None

def get_default_gln():
    """Get default GLN from settings"""
    try:
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if settings_list:
            settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
            if hasattr(settings, 'default_gln') and settings.default_gln:
                return settings.default_gln
    except:
        pass
    
    return "8713783461136"

def get_delivery_remarks(sales_order):
    """Get delivery remarks, ensuring minimum length of 1 character"""
    remarks = ""
    if hasattr(sales_order, 'delivery_notes') and sales_order.delivery_notes:
        remarks = sales_order.delivery_notes
    
    if not remarks or len(remarks.strip()) == 0:
        remarks = "Standard delivery"
    
    if len(remarks) > 100:
        remarks = remarks[:97] + "..."
    
    return remarks

def get_commercial_invoice_reference(floriday_order_id, sales_order_name):
    """Generate commercial invoice reference with max length of 26 characters"""
    short_uuid = floriday_order_id[-10:] if len(floriday_order_id) > 10 else floriday_order_id
    short_so = sales_order_name[-8:] if len(sales_order_name) > 8 else sales_order_name
    
    reference = f"{short_uuid}-{short_so}"
    
    if len(reference) > 26:
        reference = reference[:26]
    
    return reference

def get_load_carrier_reference(sales_order_name):
    """Generate load carrier reference with max length of 14 characters"""
    if len(sales_order_name) > 14:
        reference = sales_order_name[-14:]
    else:
        reference = sales_order_name.zfill(14)
    
    return reference

def get_fulfillment_request_id(base_url, headers, sales_order_id):
    """
    Fetch the fulfillmentRequestId from Floriday for a given salesOrderId.
    Calls GET /fulfillment-requests and finds the matching request.
    """
    try:
        url = f"{base_url}/fulfillment-requests"
        params = {"salesOrderId": sales_order_id}
        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()
            # Response may be a list or a dict with results key
            items = data if isinstance(data, list) else data.get("results", data.get("items", []))
            for item in items:
                if item.get("salesOrderId") == sales_order_id:
                    req_id = item.get("fulfillmentRequestId")
                    if req_id:
                        safe_log(f"Found fulfillmentRequestId {req_id} for salesOrderId {sales_order_id}",
                                 "Fulfillment Request Lookup", "info")
                        return req_id
            # If only one result and no salesOrderId field to match, return its ID
            if len(items) == 1:
                req_id = items[0].get("fulfillmentRequestId")
                if req_id:
                    return req_id
            safe_log(f"No fulfillmentRequestId found for salesOrderId {sales_order_id}. Response: {str(data)[:300]}",
                     "Fulfillment Request Lookup Warning", "warning")
        else:
            safe_log(f"GET /fulfillment-requests failed: {response.status_code} {response.text[:200]}",
                     "Fulfillment Request Lookup Error", "error")
    except Exception as e:
        safe_log(f"Error fetching fulfillment requests: {str(e)}", "Fulfillment Request Lookup Error", "error")

    return None


def update_delivery_note_with_fulfillment(sales_order_name, fulfillment_id):
    """Update Delivery Note with fulfillment information"""
    try:
        delivery_notes = frappe.get_all(
            "Delivery Note",
            filters={"docstatus": 1, "against_sales_order": sales_order_name},
            fields=["name"],
            limit=1
        )
        
        if delivery_notes:
            delivery_note = frappe.get_doc("Delivery Note", delivery_notes[0].name)
            current_remarks = delivery_note.remarks or ""
            fulfillment_info = f"\n[Floriday Fulfillment ID: {fulfillment_id}]"
            delivery_note.remarks = current_remarks + fulfillment_info
            delivery_note.save()
            frappe.db.commit()
            safe_log(f"Updated Delivery Note {delivery_note.name} with fulfillment ID", "Delivery Note Update", "info")
            
    except Exception as e:
        safe_log(f"Could not update delivery note: {str(e)}", "Delivery Note Update Error", "warning")

@frappe.whitelist()
def order_fullment():
    """
    Creates fulfillment orders in Floriday for Sales Orders created in the last 1 hour.
    Uses POST /fulfillment-orders endpoint.
    """
    logger = frappe.logger()

    def step(msg):
        logger.info(f"[Floriday Fulfillment] {msg}")

    try:
        now = now_datetime()
        start_time = add_to_date(now, hours=-1)
        step(f"STEP 1: Started. now={now}, looking back to {start_time}")

        # ── Settings ────────────────────────────────────────────────────────
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            step("STEP 2 FAILED: Floriday Settings not configured")
            return {"status": "error", "message": "Floriday Settings not configured"}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
        API_KEY = settings.api_key
        BASE_URL = settings.base_url.rstrip('/')
        ACCESS_TOKEN = settings.access_token
        SUPPLIER_ORG_ID = settings.organization_supplier_id

        missing = [k for k, v in {"API_KEY": API_KEY, "BASE_URL": BASE_URL,
                                   "ACCESS_TOKEN": ACCESS_TOKEN, "SUPPLIER_ORG_ID": SUPPLIER_ORG_ID}.items() if not v]
        if missing:
            step(f"STEP 2 FAILED: Missing settings: {missing}")
            return {"status": "error", "message": f"Floriday Settings incomplete: {missing}"}

        step(f"STEP 2 OK: Settings loaded. BASE_URL={BASE_URL}, SUPPLIER_ORG_ID='{SUPPLIER_ORG_ID}'")

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "text/plain"
        }

        # ── Query Sales Orders (Last 1 hour) ────────────────────────────────
        sales_orders = frappe.get_all(
            "Sales Order",
            filters={
                "docstatus": 1,
                "customer_group": "Floriday",
                "po_no": ["!=", ""],
                "creation": [">=", start_time]
            },
            fields=["name", "po_no", "customer", "delivery_date", "status", "creation", "custom_delivery_point"]
        )
        step(f"STEP 3: Orders in last 1 hour: {len(sales_orders)}")

        if not sales_orders:
            step("STEP 3: No orders in last 1 hour — nothing to fulfill")
            return {
                "status": "success",
                "message": "No Floriday Sales Orders found in the last 1 hour",
                "results": []
            }

        # ── Process Each Order ──────────────────────────────────────────────
        endpoint = f"{BASE_URL}/fulfillment-orders"
        results = []
        success_count = 0
        error_count = 0

        for so in sales_orders:
            sales_order_name = so.name
            floriday_order_id = so.po_no
            step(f"STEP 4: Processing {sales_order_name} | fulfillmentOrderId={floriday_order_id}")

            try:
                sales_order = frappe.get_doc("Sales Order", sales_order_name)
                step(f"  STEP 4a: Loaded SO. items={len(sales_order.items)}")

                if not sales_order.items:
                    step(f"  STEP 4b: No items in {sales_order_name} — skipping")
                    error_count += 1
                    results.append({
                        "sales_order": sales_order_name,
                        "status": "error",
                        "message": "Sales Order has no items"
                    })
                    continue

                # Calculate total stems and packages
                total_stems = sum(float(item.qty or 0) for item in sales_order.items)
                
                if total_stems <= 0:
                    step(f"  STEP 4b ERROR: Total stems is 0 for {sales_order_name}")
                    error_count += 1
                    results.append({
                        "sales_order": sales_order_name,
                        "status": "error",
                        "message": "Total stems quantity is 0"
                    })
                    continue
                
                number_of_packages = math.ceil(total_stems / 200)
                step(f"  STEP 4b: Total stems = {total_stems}, Packages = {number_of_packages}")
                
                # Get delivery GLN
                delivery_gln = get_delivery_gln_from_sales_order(sales_order)
                if not delivery_gln:
                    delivery_gln = get_default_gln()
                    safe_log(f"Using default GLN {delivery_gln}", "Default GLN Used", "warning")
                
                # In Floriday's DIRECT_SALES flow, the fulfillmentRequestId = salesOrderId (po_no).
                # There is no separate lookup endpoint needed.
                fulfillment_request_id = floriday_order_id

                # Generate references
                load_carrier_reference = get_load_carrier_reference(sales_order_name)
                commercial_invoice_ref = get_commercial_invoice_reference(floriday_order_id, sales_order_name)
                delivery_remarks = get_delivery_remarks(sales_order)
                
                # Generate a new UUID for the fulfillmentOrderId — this is OUR identifier for this fulfillment,
                # NOT the buyer's salesOrderId (floriday_order_id). Reusing po_no causes the 400 error.
                new_fulfillment_order_id = str(uuid.uuid4())
                step(f"  STEP 4c: fulfillmentRequestId={fulfillment_request_id}, new fulfillmentOrderId={new_fulfillment_order_id}")

                # Build the fulfillment order payload exactly as per curl example
                fulfillment_payload = {
                    "fulfillmentOrderId": new_fulfillment_order_id,
                    "carrierOrganizationId": SUPPLIER_ORG_ID,
                    "logisticHub": "NONE",
                    "oneLabelOnly": False,
                    "loadCarriers": [
                        {
                            "loadCarrierItems": [
                                {
                                    "fulfillmentRequestId": fulfillment_request_id,
                                    "numberOfPackages": number_of_packages,
                                    "serviceCode": 1,  # Standard service code; 9999 was the spec's max-value example, not a valid code
                                    "packingAgentOrganizationId": SUPPLIER_ORG_ID,
                                    "sortIndex": 0,
                                    "deliveryRemarks": delivery_remarks,
                                    "commercialInvoiceReference": commercial_invoice_ref
                                }
                            ],
                            "loadCarrierType": "NONE",
                            "numberOfAdditionalLayers": 0,
                            "sortIndex": 0,
                            "loadCarrierReference": load_carrier_reference
                        }
                    ],
                    "deliveryLocationGln": delivery_gln
                }

                step(f"  STEP 4d: Sending POST to {endpoint}")
                response = requests.post(endpoint, headers=headers, json=fulfillment_payload, timeout=30)

                step(f"  STEP 4e: Response status={response.status_code}")
                
                if response.status_code in (200, 201):
                    response_data = response.json() if response.text else {}
                    fulfillment_id = response_data.get("fulfillmentOrderId", new_fulfillment_order_id)
                    step(f"  STEP 4f SUCCESS: fulfillment_id={fulfillment_id}")

                    # Update Sales Order
                    current_remarks = sales_order.get("remarks") or ""
                    sales_order.remarks = (
                        current_remarks
                        + f"\n[Floriday Fulfillment Created: {fulfillment_id} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
                        + f"\nTotal Stems: {total_stems}, Packages: {number_of_packages} (200 stems/package)"
                        + f"\nDelivery GLN: {delivery_gln}"
                        + f"\nFulfillment Request ID: {fulfillment_request_id}"
                    )
                    sales_order.save(ignore_permissions=True)
                    frappe.db.commit()

                    update_delivery_note_with_fulfillment(sales_order_name, fulfillment_id)

                    success_count += 1
                    results.append({
                        "sales_order": sales_order_name,
                        "floriday_order_id": floriday_order_id,
                        "fulfillment_id": fulfillment_id,
                        "fulfillment_request_id": fulfillment_request_id,
                        "total_stems": total_stems,
                        "number_of_packages": number_of_packages,
                        "delivery_gln": delivery_gln,
                        "status": "success",
                        "message": f"Fulfillment order created successfully"
                    })
                else:
                    error_detail = ""
                    try:
                        error_response = response.json()
                        error_detail = json.dumps(error_response, indent=2)
                    except:
                        error_detail = response.text

                    # "already fulfilled" means the order was successfully fulfilled in a prior run
                    if response.status_code == 400 and "has already been fulfilled" in error_detail:
                        step(f"  STEP 4f ALREADY FULFILLED: {sales_order_name}")
                        success_count += 1
                        results.append({
                            "sales_order": sales_order_name,
                            "floriday_order_id": floriday_order_id,
                            "fulfillment_request_id": fulfillment_request_id,
                            "status": "success",
                            "message": "Already fulfilled in Floriday"
                        })
                    else:
                        step(f"  STEP 4f ERROR: {error_detail[:200]}")
                        error_count += 1
                        results.append({
                            "sales_order": sales_order_name,
                            "floriday_order_id": floriday_order_id,
                            "new_fulfillment_order_id": new_fulfillment_order_id,
                            "fulfillment_request_id": fulfillment_request_id,
                            "status": "error",
                            "status_code": response.status_code,
                            "message": f"HTTP {response.status_code}: {error_detail[:200]}"
                        })

            except Exception as e:
                import traceback
                step(f"  STEP 4 EXCEPTION: {str(e)[:200]}")
                frappe.log_error(
                    title=f"Floriday Fulfillment Exception - {sales_order_name}",
                    message=f"Error: {str(e)}\n\nTraceback: {traceback.format_exc()[:500]}"
                )
                error_count += 1
                results.append({
                    "sales_order": sales_order_name,
                    "status": "error",
                    "message": str(e)[:300]
                })

        step(f"STEP 5 DONE: total={len(sales_orders)} success={success_count} errors={error_count}")

        return {
            "status": "success",
            "results": results,
            "summary": {
                "total": len(sales_orders),
                "successful": success_count,
                "errors": error_count
            }
        }

    except Exception as e:
        import traceback
        frappe.log_error(f"Floriday Fulfillment Fatal Error: {str(e)[:150]}\n{traceback.format_exc()[:200]}", "Floriday Fulfillment Fatal Error")
        return {"status": "error", "message": str(e)[:300]}