import frappe
import requests
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ================= SAFE LOGGING UTILITY =================
def safe_log(message, title=None, log_type="info"):
    """
    Safe logging that prevents CharacterLengthExceededError
    Logs to server logs and only critical errors to Error Log doctype
    """
    # Ensure message is string and truncate if too long
    message_str = str(message)
    if len(message_str) > 200:
        message_str = message_str[:200] + "..."
    
    # Log to appropriate logger based on type
    logger = frappe.logger()
    
    if log_type == "error":
        logger.error(f"{title or 'ERROR'}: {message_str}")
        # Only log simple version to Error Log doctype for actual errors
        if title and "Error" in title:
            simple_title = title[:80] if len(title) > 80 else title
            simple_msg = message_str[:100] if len(message_str) > 100 else message_str
            frappe.log_error(simple_msg, simple_title)
    elif log_type == "warning":
        logger.warning(f"{title or 'WARNING'}: {message_str}")
    elif log_type == "debug":
        logger.debug(f"{title or 'DEBUG'}: {message_str}")
    else:  # info
        logger.info(f"{title or 'INFO'}: {message_str}")
# =========================================================

@frappe.whitelist()
def create_fulfillment_orders_from_sales_orders():
    """
    Creates fulfillment orders in Floriday for Sales Orders that are READY TO SHIP
    This should be called when orders are actually packed and ready for shipment
    """
    try:
        safe_log("Starting Floriday fulfillment order creation for READY orders", "Floriday Fulfillment Sync")
        
        # Get Floriday Settings
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            error_msg = "Floriday Settings not configured"
            safe_log(error_msg, "Floriday Settings Error", "error")
            frappe.throw(error_msg)

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)

        API_KEY = settings.api_key
        BASE_URL = settings.base_url.rstrip('/')
        ACCESS_TOKEN = settings.access_token
        SUPPLIER_ORG_ID = settings.organization_supplier_id
        
        # Validate required settings
        if not all([API_KEY, BASE_URL, ACCESS_TOKEN, SUPPLIER_ORG_ID]):
            error_msg = "Floriday Settings are incomplete"
            safe_log(error_msg, "Floriday Settings Error", "error")
            frappe.throw("Floriday Settings are incomplete. Please check API Key, Base URL, Access Token, and Supplier Organization ID.")

        # Find Sales Orders that are READY for fulfillment
        # These should be orders that are packed and ready to ship
        # We'll look for orders with specific status or custom field indicating they're ready
        sales_orders = frappe.get_all(
            "Sales Order",
            filters={
                "po_no": ["!=", ""],  # Has Floriday Order ID
                "docstatus": 1,  # Only submitted sales orders
                "status": ["in", ["To Deliver and Bill", "To Bill"]]  # Orders ready for delivery
            },
            fields=["name", "po_no", "customer", "delivery_date"],
            order_by="delivery_date"
        )

        if not sales_orders:
            safe_log("No Sales Orders found that are READY for fulfillment", "Floriday Fulfillment", "info")
            return {
                "status": "success",
                "message": "No Sales Orders found that are READY for fulfillment",
                "results": []
            }

        safe_log(f"Found {len(sales_orders)} Sales Orders READY for fulfillment", "Floriday Fulfillment")

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        results = []
        success_count = 0
        error_count = 0
        skipped_count = 0

        for so in sales_orders:
            sales_order_name = so.name
            floriday_order_id = so.po_no  # Using po_no as Floriday Order ID
            
            try:
                safe_log(f"Processing READY Sales Order: {sales_order_name} with Floriday Order ID: {floriday_order_id}", "Floriday Fulfillment Processing", "debug")
                
                # Get full Sales Order document
                sales_order = frappe.get_doc("Sales Order", sales_order_name)
                
                # IMPORTANT: Check if we have packing information
                # We need actual packing info before creating fulfillment
                if not has_packing_info(sales_order):
                    skipped_count += 1
                    results.append({
                        "sales_order": sales_order_name,
                        "floriday_order_id": floriday_order_id,
                        "status": "skipped",
                        "message": "Missing packing information. Please add packing details before creating fulfillment."
                    })
                    continue
                
                # Get Sales Order items for fulfillment data
                if not sales_order.items:
                    skipped_count += 1
                    results.append({
                        "sales_order": sales_order_name,
                        "floriday_order_id": floriday_order_id,
                        "status": "skipped",
                        "message": "No items in sales order"
                    })
                    continue
                
                # Build fulfillment order payload with ACTUAL packing information
                fulfillment_payload = build_fulfillment_payload_with_packing(sales_order, SUPPLIER_ORG_ID)
                
                if not fulfillment_payload:
                    skipped_count += 1
                    results.append({
                        "sales_order": sales_order_name,
                        "floriday_order_id": floriday_order_id,
                        "status": "skipped",
                        "message": "Could not build fulfillment payload. Check packing information."
                    })
                    continue
                
                # Call Floriday API to create fulfillment order
                endpoint = f"{BASE_URL}/fulfillment-orders"
                
                safe_log(f"API request to: {endpoint}", "Floriday Fulfillment API Request", "debug")
                safe_log(f"Request payload: {json.dumps(fulfillment_payload, indent=2)}", "Floriday Fulfillment Payload", "debug")
                
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=fulfillment_payload,
                    timeout=30
                )
                
                safe_log(f"API Response Status: {response.status_code}", "Floriday Fulfillment API Response")
                
                if response.status_code == 200:
                    # Success - update Sales Order status
                    response_data = response.json()
                    fulfillment_id = response_data.get("fulfillmentOrderId", str(uuid.uuid4()))
                    
                    # Update Sales Order to mark as fulfilled
                    # Change status to indicate fulfillment created
                    sales_order.status = "Completed"
                    
                    # Add fulfillment info to Sales Order description
                    current_description = sales_order.remarks or ""
                    fulfillment_info = f"\n[Floriday Fulfillment Created: {fulfillment_id} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
                    sales_order.remarks = current_description + fulfillment_info
                    
                    sales_order.save()
                    frappe.db.commit()
                    
                    # Also update delivery note if it exists
                    update_delivery_note_with_fulfillment(sales_order_name, fulfillment_id)
                    
                    success_count += 1
                    results.append({
                        "sales_order": sales_order_name,
                        "floriday_order_id": floriday_order_id,
                        "fulfillment_id": fulfillment_id,
                        "status": "success",
                        "message": "Fulfillment order created successfully. Order marked as shipped in Floriday."
                    })
                    
                    safe_log(f"Created fulfillment order {fulfillment_id} for Sales Order {sales_order_name}. Order is now SHIPPED in Floriday.", "Floriday Fulfillment Success", "info")
                    
                else:
                    error_count += 1
                    error_msg = f"API failed: {response.status_code} - {response.text[:200]}"
                    safe_log(error_msg, "Floriday Fulfillment Error", "error")
                    
                    results.append({
                        "sales_order": sales_order_name,
                        "floriday_order_id": floriday_order_id,
                        "status": "error",
                        "error": f"HTTP {response.status_code}: {response.text[:100]}"
                    })
                    
            except Exception as e:
                error_count += 1
                error_msg = f"Error processing Sales Order {sales_order_name}: {str(e)[:100]}"
                safe_log(error_msg, "Floriday Fulfillment Processing Error", "error")
                
                results.append({
                    "sales_order": sales_order_name,
                    "floriday_order_id": floriday_order_id,
                    "status": "error",
                    "error": str(e)[:100]
                })

        # Log summary
        summary_msg = f"""
Floriday Fulfillment Order Creation Summary (READY ORDERS ONLY):
- Total READY Sales Orders: {len(sales_orders)}
- Successfully created fulfillment: {success_count}
- Skipped (missing packing info): {skipped_count}
- Errors: {error_count}"""
        
        safe_log(summary_msg, "Floriday Fulfillment Summary", "info")

        return {
            "status": "success",
            "results": results,
            "summary": {
                "total_ready": len(sales_orders),
                "successful": success_count,
                "skipped": skipped_count,
                "errors": error_count
            }
        }

    except Exception as e:
        error_summary = f"Fulfillment creation failed: {type(e).__name__}"
        safe_log(f"{error_summary} - Full error: {str(e)}", "Floriday Fulfillment Sync Error", "error")
        return {"status": "error", "message": error_summary}


def has_packing_info(sales_order):
    """
    Check if Sales Order has packing information needed for fulfillment
    Returns True if we have enough info to create fulfillment
    """
    # Check if we have item quantities
    if not sales_order.items:
        return False
    
    # Check if items have warehouse assignment (indicating they're ready)
    for item in sales_order.items:
        if not item.warehouse:
            safe_log(f"Item {item.item_code} has no warehouse assigned", "Packing Info Check", "warning")
            return False
    
    # Check if we have delivery date (when it should be shipped)
    if not sales_order.delivery_date:
        safe_log("No delivery date set", "Packing Info Check", "warning")
        return False
    
    return True


def build_fulfillment_payload_with_packing(sales_order, supplier_org_id):
    """
    Builds the fulfillment order payload with ACTUAL packing information
    This should be called when items are actually packed and ready to ship
    """
    try:
        # Generate a unique fulfillment order ID
        fulfillment_order_id = str(uuid.uuid4())
        
        # Get delivery location GLN - use default for now
        delivery_location_gln = get_default_gln()
        
        # Build load carriers with ACTUAL packing information
        load_carriers = build_load_carriers_with_actual_packing(sales_order.items, supplier_org_id, sales_order)
        
        if not load_carriers:
            safe_log("No load carriers could be built - check actual packing information", "Floriday Fulfillment Payload", "warning")
            return None
        
        # Build the main payload
        payload = {
            "fulfillmentOrderId": fulfillment_order_id,
            "carrierOrganizationId": supplier_org_id,  # Using supplier org as carrier
            "logisticHub": "NONE",
            "oneLabelOnly": True,
            "loadCarriers": load_carriers,
            "deliveryLocationGln": delivery_location_gln
        }
        
        safe_log(f"Built fulfillment payload with ACTUAL packing info: {len(load_carriers)} load carrier(s)", "Floriday Fulfillment Payload", "debug")
        
        return payload
        
    except Exception as e:
        safe_log(f"Error building fulfillment payload: {str(e)}", "Floriday Fulfillment Payload Error", "error")
        return None


def build_load_carriers_with_actual_packing(items, supplier_org_id, sales_order):
    """
    Build load carriers array with ACTUAL packing information
    This should reflect how items are actually packed for shipment
    """
    load_carriers = []
    
    try:
        # In real scenario, you would get actual packing information from:
        # 1. Packing slips
        # 2. Warehouse packing data
        # 3. Manual input from packing team
        
        # For now, we'll create a simple load carrier
        # In production, you should enhance this with actual packing data
        
        load_carrier_items = []
        
        for idx, item in enumerate(items):
            # Get trade item ID from item mapping
            trade_item_id = get_trade_item_id_from_item_code(item.item_code)
            
            if not trade_item_id:
                safe_log(f"No trade item ID found for item {item.item_code}", "Floriday Item Mapping", "warning")
                continue
            
            # ACTUAL PACKING: This should come from actual packing information
            # For example: How many boxes? What size? Weight? etc.
            # For now, we'll use item quantity as packages (1 stem = 1 package is NOT realistic)
            
            # TODO: Replace with ACTUAL packing information
            # This should come from your packing process
            number_of_packages = calculate_actual_packages(item.item_code, item.qty)
            
            # Create load carrier item with ACTUAL packing info
            load_carrier_item = {
                "fulfillmentRequestId": str(uuid.uuid4()),
                "numberOfPackages": number_of_packages,
                "serviceCode": get_service_code_for_item(item.item_code),  # Get actual service code
                "packingAgentOrganizationId": supplier_org_id,
                "sortIndex": idx,
                "deliveryRemarks": get_delivery_remarks(sales_order),
                "commercialInvoiceReference": sales_order.po_no or sales_order.name
            }
            
            load_carrier_items.append(load_carrier_item)
        
        if not load_carrier_items:
            safe_log("No valid load carrier items created", "Floriday Load Carriers", "warning")
            return None
        
        # Create the load carrier with ACTUAL load carrier type
        load_carrier = {
            "loadCarrierItems": load_carrier_items,
            "loadCarrierType": get_actual_load_carrier_type(sales_order),  # Get actual carrier type
            "numberOfAdditionalLayers": 0,
            "sortIndex": 0,
            "loadCarrierReference": f"SO-{sales_order.name}-{datetime.now().strftime('%Y%m%d')}"
        }
        
        load_carriers.append(load_carrier)
        
        return load_carriers
        
    except Exception as e:
        safe_log(f"Error building load carriers: {str(e)}", "Floriday Load Carriers Error", "error")
        return None


def calculate_actual_packages(item_code, quantity):
    """
    Calculate ACTUAL number of packages based on item and quantity
    This should be based on your actual packing configuration
    """
    # TODO: Implement actual packing logic
    # Example: If roses are packed 25 stems per box
    # return math.ceil(quantity / 25)
    
    # For now, return at least 1 package
    return max(1, int(quantity))


def get_service_code_for_item(item_code):
    """
    Get actual service code for the item
    Different items might have different service requirements
    """
    # TODO: Implement based on your service codes
    # Check item properties or category
    return 9999  # Default service code


def get_delivery_remarks(sales_order):
    """
    Get delivery remarks from sales order
    """
    if hasattr(sales_order, 'delivery_notes'):
        return sales_order.delivery_notes or ""
    return ""


def get_actual_load_carrier_type(sales_order):
    """
    Get actual load carrier type based on order
    """
    # TODO: Implement based on your carrier preferences
    # Check order size, weight, destination, etc.
    return "NONE"  # Default


def get_default_gln():
    """
    Get default GLN from settings
    """
    try:
        # Try to get from Floriday Settings
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if settings_list:
            settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
            if hasattr(settings, 'default_gln') and settings.default_gln:
                return settings.default_gln
    except:
        pass
    
    return "1234567890123"  # Default GLN


def get_trade_item_id_from_item_code(item_code):
    """
    Get Floriday trade item ID from ERPNext item code
    """
    try:
        # First try to get from Floriday Item Mapping doctype
        mappings = frappe.get_all(
            "Floriday Item Mapping",
            fields=["trade_item_id"],
            filters={"item_code": item_code}
        )
        
        if mappings:
            return mappings[0].trade_item_id
        
        # Fallback to custom field on Item
        trade_item_id = frappe.db.get_value("Item", item_code, "floriday_trade_item_id")
        if trade_item_id:
            return trade_item_id
        
        return None
        
    except Exception as e:
        safe_log(f"Error getting trade item ID for {item_code}: {str(e)}", "Floriday Item Mapping Error", "error")
        return None


def update_delivery_note_with_fulfillment(sales_order_name, fulfillment_id):
    """
    Update Delivery Note with fulfillment information if it exists
    """
    try:
        # Find delivery note linked to this sales order
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
def create_fulfillment_for_single_order_when_ready(sales_order_name, packing_details=None):
    """
    Create fulfillment order for a single Sales Order WHEN IT'S READY TO SHIP
    packing_details should contain actual packing information
    """
    try:
        safe_log(f"Creating fulfillment for READY Sales Order: {sales_order_name}", "Floriday Single Fulfillment")
        
        # Get Floriday Settings
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            error_msg = "Floriday Settings not configured"
            safe_log(error_msg, "Floriday Settings Error", "error")
            return {"status": "error", "message": error_msg}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)

        API_KEY = settings.api_key
        BASE_URL = settings.base_url.rstrip('/')
        ACCESS_TOKEN = settings.access_token
        SUPPLIER_ORG_ID = settings.organization_supplier_id
        
        # Validate required settings
        if not all([API_KEY, BASE_URL, ACCESS_TOKEN, SUPPLIER_ORG_ID]):
            error_msg = "Floriday Settings are incomplete"
            safe_log(error_msg, "Floriday Settings Error", "error")
            return {"status": "error", "message": error_msg}
        
        # Get Sales Order
        if not frappe.db.exists("Sales Order", sales_order_name):
            return {"status": "error", "message": f"Sales Order {sales_order_name} not found"}
        
        sales_order = frappe.get_doc("Sales Order", sales_order_name)
        
        # Check if already fulfilled
        if sales_order.status == "Completed":
            return {
                "status": "info", 
                "message": f"Sales Order is already marked as Completed (likely already fulfilled)"
            }
        
        # Check if has Floriday Order ID in po_no
        if not sales_order.po_no or not sales_order.po_no.strip():
            return {"status": "error", "message": "Sales Order does not have a PO Number (Floriday Order ID)"}
        
        # Validate that order is ready for fulfillment
        if not has_packing_info(sales_order):
            return {
                "status": "error",
                "message": "Order is not ready for fulfillment. Missing packing information or warehouse assignment."
            }
        
        # Build fulfillment payload with packing information
        fulfillment_payload = build_fulfillment_payload_with_packing(sales_order, SUPPLIER_ORG_ID)
        
        if not fulfillment_payload:
            return {"status": "error", "message": "Could not build fulfillment payload. Check packing information."}
        
        # Call Floriday API
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        endpoint = f"{BASE_URL}/fulfillment-orders"
        
        response = requests.post(
            endpoint,
            headers=headers,
            json=fulfillment_payload,
            timeout=30
        )
        
        if response.status_code == 200:
            response_data = response.json()
            fulfillment_id = response_data.get("fulfillmentOrderId", str(uuid.uuid4()))
            
            # Update Sales Order status to Completed
            sales_order.status = "Completed"
            current_remarks = sales_order.remarks or ""
            fulfillment_info = f"\n[Floriday Fulfillment Created: {fulfillment_id} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
            sales_order.remarks = current_remarks + fulfillment_info
            sales_order.save()
            frappe.db.commit()
            
            # Update delivery note if exists
            update_delivery_note_with_fulfillment(sales_order_name, fulfillment_id)
            
            safe_log(f"Created fulfillment order {fulfillment_id} for Sales Order {sales_order_name}. Order is now SHIPPED in Floriday.", "Floriday Fulfillment Success", "info")
            
            return {
                "status": "success",
                "message": "Fulfillment order created successfully. Order marked as shipped in Floriday.",
                "fulfillment_id": fulfillment_id,
                "sales_order": sales_order_name,
                "new_status": "Completed"
            }
        else:
            error_msg = f"API failed: {response.status_code} - {response.text[:200]}"
            safe_log(error_msg, "Floriday Fulfillment Error", "error")
            
            return {
                "status": "error",
                "message": f"HTTP {response.status_code}: {response.text[:100]}"
            }
            
    except Exception as e:
        error_msg = f"Error creating fulfillment: {str(e)}"
        safe_log(error_msg, "Floriday Single Fulfillment Error", "error")
        return {"status": "error", "message": error_msg}


@frappe.whitelist()
def get_orders_ready_for_fulfillment():
    """
    Get list of Sales Orders that are READY for fulfillment
    These are orders that are packed and ready to ship
    """
    try:
        # Get orders that are ready for fulfillment
        ready_orders = frappe.get_all(
            "Sales Order",
            filters={
                "po_no": ["!=", ""],  # Has Floriday Order ID
                "docstatus": 1,  # Only submitted sales orders
                "status": ["in", ["To Deliver and Bill", "To Bill"]]  # Orders ready for delivery
            },
            fields=["name", "po_no", "customer", "delivery_date", "grand_total", "status", "per_delivered"],
            order_by="delivery_date"
        )
        
        # Add fulfillment readiness check
        for order in ready_orders:
            sales_order = frappe.get_doc("Sales Order", order.name)
            order["is_ready"] = has_packing_info(sales_order)
            order["item_count"] = len(sales_order.items)
            
            # Check if items have warehouse assigned
            warehouse_assigned = all(item.warehouse for item in sales_order.items if hasattr(item, 'warehouse'))
            order["warehouse_assigned"] = warehouse_assigned
        
        return {
            "status": "success",
            "ready_orders": ready_orders,
            "count": len(ready_orders),
            "message": f"Found {len(ready_orders)} orders ready for fulfillment"
        }
        
    except Exception as e:
        error_msg = f"Error getting ready orders: {str(e)}"
        safe_log(error_msg, "Ready Orders Error", "error")
        return {"status": "error", "message": error_msg}


@frappe.whitelist()
def mark_order_as_ready_for_fulfillment(sales_order_name):
    """
    Mark a Sales Order as ready for fulfillment
    This should be called when order is actually packed and ready to ship
    """
    try:
        if not frappe.db.exists("Sales Order", sales_order_name):
            return {"status": "error", "message": f"Sales Order {sales_order_name} not found"}
        
        sales_order = frappe.get_doc("Sales Order", sales_order_name)
        
        # Check if order is from Floriday
        if not sales_order.po_no or not sales_order.po_no.strip():
            return {"status": "error", "message": "This is not a Floriday order (no PO Number)"}
        
        # Check if already fulfilled
        if sales_order.status == "Completed":
            return {"status": "info", "message": "Order is already marked as Completed"}
        
        # Update status to indicate ready for fulfillment
        sales_order.status = "To Deliver and Bill"
        sales_order.save()
        frappe.db.commit()
        
        safe_log(f"Marked Sales Order {sales_order_name} as ready for fulfillment", "Order Status Update", "info")
        
        return {
            "status": "success",
            "message": "Order marked as ready for fulfillment",
            "sales_order": sales_order_name,
            "new_status": "To Deliver and Bill"
        }
        
    except Exception as e:
        error_msg = f"Error marking order as ready: {str(e)}"
        safe_log(error_msg, "Order Status Error", "error")
        return {"status": "error", "message": error_msg}


@frappe.whitelist()
def check_fulfillment_readiness(sales_order_name):
    """
    Check if a Sales Order is ready for fulfillment
    """
    try:
        if not frappe.db.exists("Sales Order", sales_order_name):
            return {"status": "error", "message": f"Sales Order {sales_order_name} not found"}
        
        sales_order = frappe.get_doc("Sales Order", sales_order_name)
        
        # Check readiness criteria
        readiness_checks = {
            "has_floriday_id": bool(sales_order.po_no and sales_order.po_no.strip()),
            "is_submitted": sales_order.docstatus == 1,
            "has_items": len(sales_order.items) > 0,
            "all_items_have_warehouse": all(item.warehouse for item in sales_order.items if hasattr(item, 'warehouse')),
            "has_delivery_date": bool(sales_order.delivery_date),
            "current_status": sales_order.status,
            "is_ready_status": sales_order.status in ["To Deliver and Bill", "To Bill"],
            "is_completed": sales_order.status == "Completed"
        }
        
        # Overall readiness
        is_ready = (
            readiness_checks["has_floriday_id"] and
            readiness_checks["is_submitted"] and
            readiness_checks["has_items"] and
            readiness_checks["all_items_have_warehouse"] and
            readiness_checks["has_delivery_date"] and
            readiness_checks["is_ready_status"] and
            not readiness_checks["is_completed"]
        )
        
        return {
            "status": "success",
            "sales_order": sales_order_name,
            "is_ready": is_ready,
            "readiness_checks": readiness_checks,
            "message": "Ready for fulfillment" if is_ready else "Not ready for fulfillment"
        }
        
    except Exception as e:
        error_msg = f"Error checking fulfillment readiness: {str(e)}"
        safe_log(error_msg, "Fulfillment Readiness Error", "error")
        return {"status": "error", "message": error_msg}