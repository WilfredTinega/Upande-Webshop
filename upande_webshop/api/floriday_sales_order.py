import frappe
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

def setup_custom_fields():
    """
    Creates minimal required custom fields for Floriday integration
    """
    # Only create custom field for Item to map Floriday items
    item_fields = [
        {
            "fieldname": "floriday_trade_item_id",
            "label": "Floriday Trade Item ID",
            "fieldtype": "Data",
            "insert_after": "item_code",
            "unique": 1,
            "allow_in_quick_entry": 1,
            "translatable": 0
        }
    ]
            
    # Create custom fields for Item
    for field in item_fields:
        if not frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": field["fieldname"]}):
            custom_field = frappe.get_doc({
                "doctype": "Custom Field",
                "dt": "Item",
                **field
            })
            custom_field.insert()

@frappe.whitelist()
def create_sales_orders_from_floriday():
    """
    Fetches orders from Floriday API and creates corresponding Sales Orders in ERPNext.
    Only processes orders from the last 24 hours based on orderDateTime.
    """
    try:
        setup_custom_fields()
        
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            frappe.throw("Floriday Settings not configured")

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)

        API_KEY = settings.api_key
        BASE_URL = settings.base_url.rstrip('/')
        ACCESS_TOKEN = settings.access_token
        SUPPLIER_ORG_ID = settings.organization_supplier_id
        
        # Validate required settings
        if not all([API_KEY, BASE_URL, ACCESS_TOKEN, SUPPLIER_ORG_ID]):
            frappe.throw("Floriday Settings are incomplete. Please check API Key, Base URL, Access Token, and Supplier Organization ID.")

        # Set date range for last 24 hours (UTC-aware)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(hours=24)

        frappe.log_error(f"Fetching Floriday orders from {start_date} to {end_date} for supplier: {SUPPLIER_ORG_ID}", "Floriday Order Sync")

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Build API endpoint with supplier organization filter AND date filtering
        endpoint = f"{BASE_URL}/sales-orders"
        
        # UPDATED: Use startDateTime and endDateTime parameters as per API documentation
        params = {
            "supplierOrganizationId": SUPPLIER_ORG_ID,
            "pageSize": 100,
            "startDateTime": start_date.isoformat(),  # ISO 8601 format
            "endDateTime": end_date.isoformat(),
            "limitResult": 1000  # Added limitResult as per API docs
        }

        frappe.log_error(f"Making API request to: {endpoint}", "Floriday API Request")
        frappe.log_error(f"Request params: {json.dumps(params, indent=2)}", "Floriday API Params")

        response = requests.get(
            endpoint,
            headers=headers,
            params=params,
            timeout=30
        )

        frappe.log_error(f"Floriday API Response Status: {response.status_code}", "Floriday Order API")

        if response.status_code != 200:
            error_msg = f"Failed to fetch Floriday orders: {response.status_code} - {response.text}"
            frappe.log_error(error_msg, "Floriday Order Fetch Error")
            return {"status": "error", "message": error_msg}

        # LOG THE RAW RESPONSE PAYLOAD
        raw_response = response.text
        frappe.log_error(f"RAW FLORIDAY API RESPONSE:\n{raw_response}", "Floriday Raw Response")

        orders = response.json()
        
        # LOG THE PARSED ORDERS PAYLOAD
        frappe.log_error(f"PARSED FLORIDAY ORDERS PAYLOAD:\n{json.dumps(orders, indent=2)}", "Floriday Orders Payload")

        if not isinstance(orders, list):
            error_msg = f"Unexpected API response format. Expected list, got {type(orders)}"
            frappe.log_error(error_msg, "Floriday Order Format Error")
            frappe.throw(error_msg)

        frappe.log_error(f"Retrieved {len(orders)} total orders from Floriday API", "Floriday Order Count")

        results = []
        processed_count = 0
        skipped_count = 0
        error_count = 0
        date_filtered_count = 0

        for order in orders:
            order_dt_str = order.get("orderDateTime")
            if not order_dt_str:
                frappe.log_error(f"Order missing orderDateTime: {order.get('salesOrderId', 'Unknown')}", "Floriday Order Date Missing")
                skipped_count += 1
                continue

            # Parse Floriday orderDateTime to UTC-aware datetime
            try:
                order_dt = parse_order_date(order_dt_str)
            except ValueError as e:
                frappe.log_error(f"Error parsing date {order_dt_str}: {str(e)}", "Floriday Date Parse Error")
                skipped_count += 1
                continue
            
            # STRICT DATE FILTERING - Skip orders outside last 24 hours
            if not (start_date <= order_dt <= end_date):
                date_filtered_count += 1
                frappe.log_error(f"❌ DATE FILTERED - Order {order.get('salesOrderId')} from {order_dt} is outside range {start_date} to {end_date}", "Floriday Order Date Range")
                continue

            # Only process COMMITTED orders
            if order.get("status") != "COMMITTED":
                frappe.log_error(f"Skipping non-COMMITTED order: {order.get('salesOrderId')} - Status: {order.get('status')}", "Floriday Order Status")
                skipped_count += 1
                continue

            try:
                # LOG INDIVIDUAL ORDER PAYLOAD BEFORE PROCESSING
                frappe.log_error(f"✅ PROCESSING FLORIDAY ORDER (Within Date Range):\n{json.dumps(order, indent=2)}", f"Floriday Order {order.get('salesOrderId')}")
                
                sales_order = create_sales_order_from_floriday(order)
                processed_count += 1
                
                results.append({
                    "floriday_order_id": order.get("salesOrderId"),
                    "sales_channel_order_id": order.get("salesChannelOrderId"),
                    "erpnext_sales_order": sales_order.name,
                    "status": "success"
                })

                frappe.log_error(f"✅ Successfully created Sales Order {sales_order.name} from Floriday order {order.get('salesOrderId')}", "Floriday Order Success")

            except Exception as e:
                error_count += 1
                error_msg = f"Error creating sales order from Floriday order {order.get('salesOrderId', 'Unknown')}: {str(e)}"
                frappe.log_error(error_msg, "Floriday Order Creation Error")
                results.append({
                    "floriday_order_id": order.get("salesOrderId"),
                    "status": "error",
                    "error": str(e)
                })

        # Log comprehensive summary
        summary_msg = f"""
Floriday Order Sync Summary:
- Total orders from API: {len(orders)}
- Processed successfully: {processed_count}
- Filtered by date (outside 24h): {date_filtered_count}
- Skipped (non-COMMITTED/missing data): {skipped_count}
- Errors: {error_count}
- Date range: {start_date} to {end_date}
- Supplier Organization: {SUPPLIER_ORG_ID}"""
        
        frappe.log_error(summary_msg, "Floriday Order Sync Summary")

        if processed_count == 0 and date_filtered_count > 0:
            frappe.log_error(
                f"No orders found in the last 24 hours. {date_filtered_count} orders were filtered out due to date range.",
                "Floriday Order Sync Info"
            )

        return {
            "status": "success", 
            "results": results,
            "summary": {
                "total_from_api": len(orders),
                "processed": processed_count,
                "date_filtered": date_filtered_count,
                "skipped": skipped_count,
                "errors": error_count,
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "supplier_organization": SUPPLIER_ORG_ID
            }
        }

    except Exception as e:
        error_msg = f"Error in Floriday order sync: {str(e)}"
        frappe.log_error(error_msg, "Floriday Order Sync Error")
        return {"status": "error", "message": str(e)}


def create_sales_order_from_floriday(floriday_order):
    """
    Creates a Sales Order in ERPNext from a Floriday order.
    Args:
        floriday_order: Dictionary containing the Floriday order data
    Returns:
        The created Sales Order document
    """
    floriday_order_id = floriday_order.get("salesOrderId")
    if not floriday_order_id:
        frappe.throw("Floriday order missing salesOrderId")

    # First check if order already exists
    if frappe.db.exists("Sales Order", {"floriday_order_id": floriday_order_id}):
        frappe.throw(f"Sales Order already exists for Floriday order {floriday_order_id}")

    # Create a default customer if customerOrganizationId exists
    customer = get_or_create_customer(floriday_order)

    # Parse dates
    delivery_datetime = parse_delivery_date(floriday_order.get("delivery", {}).get("latestDeliveryDateTime"))
    order_datetime = parse_order_date(floriday_order.get("orderDateTime"))

    # Get Floriday Settings for fallback
    settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
    settings = frappe.get_doc("Floriday Settings", settings_list[0].name) if settings_list else None

    # Create Sales Order
    sales_order = frappe.new_doc("Sales Order")
    sales_order.customer = customer
    sales_order.transaction_date = order_datetime.date()
    sales_order.delivery_date = delivery_datetime.date()
    sales_order.order_type = "Sales"
    sales_order.po_no = floriday_order_id
    sales_order.po_date = order_datetime.date()
    sales_order.floriday_order_id = floriday_order_id
    
    # SET THE REQUIRED CUSTOM FIELDS - FIX FOR THE ERRORS
    sales_order.custom_sales_order_type = "Roses"
    
    # Add Floriday details to notes
    floriday_details = f"""Floriday Order Details:
- Sales Order ID: {floriday_order.get("salesOrderId")}
- Channel Order ID: {floriday_order.get("salesChannelOrderId")}
- Sales Channel: {floriday_order.get("salesChannel")}
- Trade Instrument: {floriday_order.get("tradeInstrument")}
- Supplier Organization: {floriday_order.get("supplierOrganizationId")}
- Sequence Number: {floriday_order.get("sequenceNumber")}"""

    sales_order.notes = floriday_details
    
    # Set currency from pricePerPiece
    price_info = floriday_order.get("pricePerPiece", {})
    transaction_currency = price_info.get("currency", "EUR")
    sales_order.currency = transaction_currency

    # Add delivery info
    delivery = floriday_order.get("delivery", {})
    if delivery.get("regionGln"):
        sales_order.delivery_region_gln = delivery.get("regionGln")
    if delivery.get("deliveryRemarks"):
        sales_order.delivery_notes = delivery.get("deliveryRemarks")
        
    # Add packing info to notes
    packing = floriday_order.get("packingConfiguration", {})
    if packing:
        packing_info = f"""
Packing Configuration:
- Pieces per Package: {packing.get('piecesPerPackage')}
- Load Carrier: {packing.get('loadCarrier')}
- VBN Package Code: {packing.get('package', {}).get('vbnPackageCode')}"""
        sales_order.notes += packing_info

    # CALCULATE TOTAL ORDERED STEMS FIRST - before item processing
    total_ordered_stems = floriday_order.get("numberOfPieces", 0)
    frappe.log_error(f"Total ordered stems from Floriday order: {total_ordered_stems}", "Floriday Ordered Stems Calculation")

    # Add items and get ALL data from Stock Entry
    trade_item_id = floriday_order.get("tradeItemId")
    
    if trade_item_id:
        item_code = get_erpnext_item_code(trade_item_id)
        if item_code:
            number_of_pieces = floriday_order.get("numberOfPieces", 0)
            price_per_piece = price_info.get("value", 0)
            
            # Get calculated total if available
            calculated = floriday_order.get("calculatedFields", {})
            total_price_per_piece = calculated.get("totalPricePerPiece", {}).get("value", price_per_piece)
            
            # Get ALL data from Stock Entry - custom_farm, custom_business_unit, warehouse, AND company
            farm, business_unit, warehouse, company_from_stock_entry = get_farm_business_unit_warehouse_company_from_stock_entry(trade_item_id, item_code)
            
            # Set company from Stock Entry (same source as other fields)
            if company_from_stock_entry:
                sales_order.company = company_from_stock_entry
                frappe.log_error(f"Set company from Stock Entry: {company_from_stock_entry}", "Floriday Company From Stock Entry")
            elif settings and settings.company:
                sales_order.company = settings.company
                frappe.log_error(f"Set company from Floriday Settings: {settings.company}", "Floriday Company From Settings")
            else:
                # Final fallback - get first company
                companies = frappe.get_all("Company", limit_page_length=1)
                if companies:
                    sales_order.company = companies[0].name
                    frappe.log_error(f"Set company from fallback: {sales_order.company}", "Floriday Company Fallback")
            
            # Create item entry with warehouse from Stock Entry - INCLUDING CUSTOM FIELDS
            item = {
                "item_code": item_code,
                "qty": number_of_pieces,
                "rate": total_price_per_piece,
                "delivery_date": delivery_datetime.date(),
                "warehouse": warehouse,
                # SET THE ORDERED STEMS FIELD IN THE ITEM TABLE
                "custom_ordered_quantity": number_of_pieces,  # This is the correct field name
                "description": f"""Floriday Details:
- Trade Item ID: {trade_item_id}
- Pieces per Package: {packing.get("piecesPerPackage", "N/A")}
- Farm: {farm or "Not specified"}
- Business Unit: {business_unit or "Not specified"}"""
            }
            
            sales_order.append("items", item)
            
            # Set farm and business unit in Sales Order from Stock Entry
            if farm:
                sales_order.custom_farm = farm
                frappe.log_error(f"Set custom_farm on Sales Order: {farm}", "Floriday Farm Set")
            else:
                frappe.log_error("No farm found to set on Sales Order", "Floriday Farm Missing")
                
            if business_unit:
                sales_order.custom_business_unit = business_unit
                frappe.log_error(f"Set custom_business_unit on Sales Order: {business_unit}", "Floriday Business Unit Set")
            else:
                frappe.log_error("No business_unit found to set on Sales Order", "Floriday Business Unit Missing")
        else:
            frappe.log_error(f"Could not find item code for trade item ID: {trade_item_id}", "Floriday Item Mapping Error")
    else:
        frappe.log_error("No tradeItemId found in Floriday order", "Floriday Trade Item Missing")

    if not sales_order.items:
        frappe.throw(f"No valid items found in Floriday order {floriday_order_id}")

    # SET THE ORDERED STEMS CUSTOM FIELD - FIX FOR THE SECOND ERROR
    # Ensure it's never zero by using the calculated value
    if total_ordered_stems == 0:
        # If somehow still zero, try to get from items
        for item in sales_order.items:
            total_ordered_stems += item.qty
        frappe.log_error(f"Recalculated ordered stems from items: {total_ordered_stems}", "Floriday Ordered Stems Recalculation")
    
    # Set the main sales order custom field for ordered stems (if it exists)
    if hasattr(sales_order, 'custom_ordered_stems'):
        sales_order.custom_ordered_stems = total_ordered_stems
        frappe.log_error(f"Set custom_ordered_stems to: {total_ordered_stems}", "Floriday Ordered Stems Set")

    # Set conversion rate if company is set
    if sales_order.company:
        company_currency = frappe.get_cached_value('Company', sales_order.company, 'default_currency')
        
        if transaction_currency != company_currency:
            # Get exchange rate from ERPNext
            exchange_rate = get_exchange_rate(transaction_currency, company_currency, order_datetime)
            if exchange_rate:
                sales_order.conversion_rate = exchange_rate
            else:
                frappe.log_error(f"No exchange rate found for {transaction_currency} to {company_currency}", "Floriday Exchange Rate")
                # Set default conversion rate
                sales_order.conversion_rate = 1.0

    # LOG THE SALES ORDER PAYLOAD BEFORE CREATION
    sales_order_payload = {
        "customer": sales_order.customer,
        "transaction_date": str(sales_order.transaction_date),
        "delivery_date": str(sales_order.delivery_date),
        "currency": sales_order.currency,
        "conversion_rate": getattr(sales_order, 'conversion_rate', 1.0),
        "company": sales_order.company,
        "custom_farm": getattr(sales_order, 'custom_farm', 'Not set'),
        "custom_business_unit": getattr(sales_order, 'custom_business_unit', 'Not set'),
        "custom_sales_order_type": getattr(sales_order, 'custom_sales_order_type', 'Not set'),
        "custom_ordered_stems": getattr(sales_order, 'custom_ordered_stems', 'Not set'),
        "items": [
            {
                "item_code": item.item_code,
                "qty": item.qty,
                "rate": item.rate,
                "warehouse": item.warehouse,
                "custom_ordered_quantity": getattr(item, 'custom_ordered_quantity', 'Not set')
            } for item in sales_order.items
        ]
    }
    frappe.log_error(f"SALES ORDER PAYLOAD TO BE CREATED:\n{json.dumps(sales_order_payload, indent=2)}", f"Sales Order Payload {floriday_order_id}")
    
    # Validate and calculate totals
    sales_order.run_method('validate')
    sales_order.run_method('calculate_taxes_and_totals')
    
    # Insert and submit
    sales_order.insert(ignore_permissions=True)
    sales_order.submit()
    
    frappe.log_error(f"Created and submitted Sales Order: {sales_order.name}", "Floriday Sales Order Created")
    return sales_order


def get_farm_business_unit_warehouse_company_from_stock_entry(trade_item_id, item_code):
    """
    Get farm, business unit, warehouse, and company from the latest Stock Entry for this item
    """
    try:
        farm = None
        business_unit = None
        warehouse = None
        company = None
        
        frappe.log_error(f"Looking for Stock Entry with item: {item_code} (trade_item_id: {trade_item_id})", "Floriday Stock Entry Search")
        
        # Look for the latest Stock Entry that contains this item
        stock_entry_details = frappe.get_all(
            "Stock Entry Detail",
            fields=["parent", "t_warehouse"],
            filters={
                "item_code": item_code,
                "docstatus": 1  # Only submitted stock entries
            },
            order_by="creation DESC",
            limit_page_length=1
        )
        
        if stock_entry_details:
            stock_entry_name = stock_entry_details[0].parent
            frappe.log_error(f"Found Stock Entry: {stock_entry_name} for item {item_code}", "Floriday Stock Entry Found")
            
            # Get the full Stock Entry document
            stock_entry = frappe.get_doc("Stock Entry", stock_entry_name)
            
            # Get ALL fields from the Stock Entry
            farm = stock_entry.get('custom_farm')  # Use correct field name
            business_unit = stock_entry.get('custom_business_unit')  # Use correct field name
            warehouse = stock_entry.to_warehouse or stock_entry_details[0].t_warehouse
            company = stock_entry.company  # Company is a standard field in Stock Entry
            
            frappe.log_error(f"From Stock Entry {stock_entry_name}: custom_farm='{farm}', custom_business_unit='{business_unit}', warehouse='{warehouse}', company='{company}'", "Floriday Stock Entry Data")
            
        else:
            frappe.log_error(f"No Stock Entries found for item {item_code}", "Floriday Stock Entry Not Found")
        
        # If no Stock Entry found, use fallbacks
        if not company:
            companies = frappe.get_all("Company", limit_page_length=1)
            if companies:
                company = companies[0].name
                frappe.log_error(f"Using fallback company: {company}", "Floriday Company Fallback")
        
        if not warehouse and company:
            item_defaults = frappe.get_all(
                "Item Default",
                fields=["default_warehouse"],
                filters={"parent": item_code, "company": company}
            )
            if item_defaults:
                warehouse = item_defaults[0].default_warehouse
                frappe.log_error(f"Using fallback warehouse: {warehouse}", "Floriday Warehouse Fallback")
        
        frappe.log_error(f"Final result - custom_farm: '{farm}', custom_business_unit: '{business_unit}', warehouse: '{warehouse}', company: '{company}'", "Floriday Final Result")
        
        return farm, business_unit, warehouse, company
        
    except Exception as e:
        frappe.log_error(f"Error getting data from stock entry for trade item {trade_item_id}: {str(e)}", "Floriday Stock Entry Error")
        return None, None, None, None


def get_exchange_rate(from_currency, to_currency, date):
    """
    Get exchange rate between currencies for a specific date
    """
    try:
        exchange_rate = frappe.db.sql("""
            SELECT exchange_rate
            FROM `tabCurrency Exchange`
            WHERE from_currency = %s AND to_currency = %s AND date <= %s
            ORDER BY date DESC
            LIMIT 1
        """, (from_currency, to_currency, date), as_dict=True)

        if exchange_rate:
            return exchange_rate[0].exchange_rate
        
        # Fallback: try to get from Currency Exchange Rate Settings
        try:
            from frappe.utils import getdate
            exchange_rate = frappe.db.get_value("Currency Exchange", {
                "from_currency": from_currency,
                "to_currency": to_currency,
                "date": getdate(date)
            }, "exchange_rate")
            
            if exchange_rate:
                return exchange_rate
        except:
            pass
            
        return None
    except Exception as e:
        frappe.log_error(f"Error getting exchange rate: {str(e)}", "Floriday Exchange Rate Error")
        return None


def get_or_create_customer(floriday_order):
    """
    Gets or creates a customer based on Floriday order data.
    """
    if not floriday_order:
        frappe.throw("No order data provided")
    
    # Get customer organization ID
    customer_org_id = floriday_order.get('customerOrganizationId')
    if not customer_org_id:
        # Use a default customer for orders without organization ID
        customer_name = "Floriday-Default-Customer"
    else:
        # Use a standardized naming convention for Floriday customers
        customer_name = f"Floriday-{customer_org_id}"
    
    # Check if customer exists
    if frappe.db.exists("Customer", customer_name):
        return customer_name
    
    # Create new customer
    try:
        customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_type": "Company",
            "customer_group": "Commercial",
            "territory": "Netherlands",
            "floriday_customer": 1,
            "floriday_organization_id": customer_org_id,
        })
        customer.insert(ignore_permissions=True)
        
        frappe.log_error(f"Created new Floriday customer: {customer_name}", "Floriday Customer Created")
        return customer_name
    except Exception as e:
        frappe.log_error(f"Failed to create customer '{customer_name}': {str(e)}", "Floriday Customer Creation Error")
        # Return default customer if creation fails
        return "Floriday-Default-Customer"


def get_erpnext_item_code(floriday_trade_item_id):
    """
    Get ERPNext item code from Floriday trade item ID using dynamic mapping
    """
    try:
        # First try to get from Floriday Item Mapping doctype
        mappings = frappe.get_all(
            "Floriday Item Mapping",
            fields=["item_code", "trade_item_id"],
            filters={"trade_item_id": floriday_trade_item_id}
        )
        
        if mappings:
            item_code = mappings[0].item_code
            if frappe.db.exists("Item", item_code):
                return item_code

        # Fallback to custom field
        item = frappe.db.get_value("Item", {"floriday_trade_item_id": floriday_trade_item_id}, "name")
        if item:
            return item

        frappe.throw(f"No item mapping found for Floriday trade item ID: {floriday_trade_item_id}")
    except Exception as e:
        frappe.log_error(f"Error getting item code for {floriday_trade_item_id}: {str(e)}", "Floriday Item Mapping Error")
        raise


def parse_delivery_date(delivery_date_str):
    """
    Parses the delivery date string from Floriday.
    """
    if not delivery_date_str:
        return datetime.now(timezone.utc) + timedelta(days=1)
    
    try:
        if '.' in delivery_date_str and 'Z' in delivery_date_str:
            return datetime.strptime(delivery_date_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        elif 'T' in delivery_date_str and 'Z' in delivery_date_str:
            return datetime.strptime(delivery_date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        else:
            # Try other possible formats
            return datetime.fromisoformat(delivery_date_str.replace('Z', '+00:00'))
    except Exception as e:
        frappe.log_error(f"Error parsing delivery date {delivery_date_str}: {str(e)}", "Floriday Date Parse Error")
        return datetime.now(timezone.utc) + timedelta(days=1)


def parse_order_date(order_date_str):
    """
    Parses the order date string from Floriday.
    """
    if not order_date_str:
        return datetime.now(timezone.utc)
    
    try:
        if '.' in order_date_str and 'Z' in order_date_str:
            return datetime.strptime(order_date_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        elif 'T' in order_date_str and 'Z' in order_date_str:
            return datetime.strptime(order_date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        else:
            # Try other possible formats
            return datetime.fromisoformat(order_date_str.replace('Z', '+00:00'))
    except Exception as e:
        frappe.log_error(f"Error parsing order date {order_date_str}: {str(e)}", "Floriday Date Parse Error")
        return datetime.now(timezone.utc)


@frappe.whitelist()
def get_sync_status():
    """
    Returns the status of the last Floriday sync operation
    """
    try:
        # Get the latest error log for Floriday
        latest_log = frappe.get_all("Error Log", 
            filters={"method": ["like", "%Floriday%"]},
            fields=["name", "creation", "method", "error"],
            order_by="creation DESC",
            limit_page_length=1
        )
        
        return {
            "status": "success",
            "latest_log": latest_log[0] if latest_log else None
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}