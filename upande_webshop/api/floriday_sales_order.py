import frappe
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

def log_short(msg, title="Floriday", is_error=True):
    """Log errors and successful sales order creations"""
    # Always log successful SO creations (title contains "Success")
    if not is_error and ("Success" in title or "Created" in title or "Found" in title or "Updated" in title):
        if len(msg) > 135:
            msg = msg[:132] + "..."
        frappe.log_error(msg, title)
    # Log errors
    elif is_error or "Error" in title or "Fail" in msg or "missing" in msg.lower():
        if len(msg) > 135:
            msg = msg[:132] + "..."
        frappe.log_error(msg, title)

def generate_custom_order_name(customer_name):
    """
    Generates a custom order name in format: CustomerName-XXX
    where XXX is a sequential number for that customer
    """
    try:
        # Clean customer name
        clean_name = ''.join(c for c in customer_name if c.isalnum() or c == ' ').strip()
        clean_name = clean_name.replace(' ', '-')[:20]
        
        # Find the latest order for this customer
        latest_order = frappe.db.sql("""
            SELECT custom_order_name 
            FROM `tabSales Order` 
            WHERE customer = %s 
            AND custom_order_name LIKE %s
            AND docstatus < 2
            ORDER BY creation DESC 
            LIMIT 1
        """, (customer_name, f"{clean_name}-%"), as_dict=True)
        
        if latest_order and latest_order[0].custom_order_name:
            try:
                last_number = int(latest_order[0].custom_order_name.split('-')[-1])
                new_number = last_number + 1
            except (ValueError, IndexError):
                new_number = 1
        else:
            new_number = 1
        
        return f"{clean_name}-{new_number:03d}"
        
    except Exception as e:
        log_short(f"Order name error: {str(e)[:30]}", "Floriday Order Name Error", True)
        from frappe.utils import now_datetime
        timestamp = now_datetime().strftime("%Y%m%d%H%M%S")
        return f"ORD-{timestamp}"

@frappe.whitelist()
def create_sales_orders_from_floriday():
    """
    Fetches orders from Floriday API and creates corresponding Sales Orders in ERPNext.
    Only processes orders from the last 2 hours.
    """
    try:
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            frappe.throw("Floriday Settings not configured")

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)

        API_KEY = settings.api_key
        BASE_URL = settings.base_url.rstrip('/')
        ACCESS_TOKEN = settings.access_token
        SUPPLIER_ORG_ID = settings.organization_supplier_id
        WAREHOUSE = settings.warehouse
        
        # Validate required settings
        if not all([API_KEY, BASE_URL, ACCESS_TOKEN, SUPPLIER_ORG_ID]):
            frappe.throw("Floriday Settings incomplete")
        
        if not WAREHOUSE:
            frappe.throw("Warehouse not configured in Floriday Settings")

        # Set date range for last 2 hours
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(hours=2)

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        endpoint = f"{BASE_URL}/sales-orders"
        
        params = {
            "supplierOrganizationId": SUPPLIER_ORG_ID,
            "pageSize": 100,
            "startDateTime": start_date.isoformat(),
            "endDateTime": end_date.isoformat(),
            "limitResult": 1000
        }

        response = requests.get(
            endpoint,
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            error_msg = f"API failed: {response.status_code}"
            log_short(error_msg, "Floriday Fetch Error", True)
            return {"status": "error", "message": error_msg}

        orders = response.json()
        
        if not isinstance(orders, list):
            error_msg = "Invalid response format"
            log_short(error_msg, "Floriday Format Error", True)
            frappe.throw(error_msg)

        results = []
        processed_count = 0
        skipped_count = 0
        error_count = 0
        date_filtered_count = 0

        for order in orders:
            order_dt_str = order.get("orderDateTime")
            order_id = order.get('salesOrderId', 'Unknown')[-8:]
            
            if not order_dt_str:
                skipped_count += 1
                continue

            try:
                order_dt = parse_order_date(order_dt_str)
            except ValueError:
                skipped_count += 1
                continue
            
            if not (start_date <= order_dt <= end_date):
                date_filtered_count += 1
                continue

            if order.get("status") != "COMMITTED":
                skipped_count += 1
                continue

            try:
                sales_order = create_sales_order_from_floriday(order, WAREHOUSE)
                processed_count += 1
                
                # Log successful sales order creation
                log_short(f"SO {sales_order.name} created for Floriday order {order_id}", "Floriday Success", False)
                
                results.append({
                    "floriday_order_id": order.get("salesOrderId"),
                    "sales_channel_order_id": order.get("salesChannelOrderId"),
                    "erpnext_sales_order": sales_order.name,
                    "status": "success"
                })

            except Exception as e:
                error_count += 1
                error_short = str(e)[:50] + "..." if len(str(e)) > 50 else str(e)
                log_short(f"Order {order_id}: {error_short}", "Floriday Order Error", True)
                results.append({
                    "floriday_order_id": order.get("salesOrderId"),
                    "status": "error",
                    "error": str(e)
                })

        # Log summary only if there are errors or no orders
        if error_count > 0 or processed_count == 0:
            log_short(f"Sync: P={processed_count}, F={date_filtered_count}, S={skipped_count}, E={error_count}", "Floriday Summary", True)
        else:
            # Log success summary when orders were created
            log_short(f"Success: {processed_count} orders created", "Floriday Success", False)

        return {
            "status": "success", 
            "results": results,
            "summary": {
                "total_from_api": len(orders),
                "processed": processed_count,
                "date_filtered": date_filtered_count,
                "skipped": skipped_count,
                "errors": error_count,
                "supplier_organization": SUPPLIER_ORG_ID,
                "warehouse": WAREHOUSE
            }
        }

    except Exception as e:
        error_short = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
        log_short(f"Sync failed: {error_short}", "Floriday Sync Error", True)
        return {"status": "error", "message": str(e)}


def create_sales_order_from_floriday(floriday_order, warehouse):
    """
    Creates a Sales Order in ERPNext from a Floriday order.
    """
    floriday_order_id = floriday_order.get("salesOrderId")
    if not floriday_order_id:
        frappe.throw("Floriday order missing salesOrderId")

    if frappe.db.exists("Sales Order", {"floriday_order_id": floriday_order_id}):
        frappe.throw(f"Sales Order already exists")

    # Get or create customer using Floriday ID mapping
    customer = get_or_create_customer(floriday_order)

    delivery_datetime = parse_delivery_date(floriday_order.get("delivery", {}).get("latestDeliveryDateTime"))
    order_datetime = parse_order_date(floriday_order.get("orderDateTime"))

    settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
    settings = frappe.get_doc("Floriday Settings", settings_list[0].name) if settings_list else None

    sales_order = frappe.new_doc("Sales Order")
    sales_order.customer = customer
    sales_order.transaction_date = order_datetime.date()
    sales_order.delivery_date = delivery_datetime.date()
    sales_order.order_type = "Sales"
    sales_order.po_no = floriday_order_id
    sales_order.po_date = order_datetime.date()
    sales_order.floriday_order_id = floriday_order_id
    
    sales_order.custom_sales_order_type = "Roses"
    sales_order.custom_order_name = generate_custom_order_name(customer)
    
    # Set currency
    price_info = floriday_order.get("pricePerPiece", {})
    transaction_currency = price_info.get("currency", "EUR")
    sales_order.currency = transaction_currency

    # Add delivery info to notes
    delivery = floriday_order.get("delivery", {})
    packing = floriday_order.get("packingConfiguration", {})
    
    sales_order.notes = f"""Floriday Order: {floriday_order.get("salesOrderId")}
Channel: {floriday_order.get("salesChannel")}
Supplier: {floriday_order.get("supplierOrganizationId")}"""

    # Add items
    trade_item_id = floriday_order.get("tradeItemId")
    
    if trade_item_id:
        item_code = get_erpnext_item_code(trade_item_id)
        if item_code:
            number_of_pieces = floriday_order.get("numberOfPieces", 0)
            price_per_piece = price_info.get("value", 0)
            
            calculated = floriday_order.get("calculatedFields", {})
            total_price_per_piece = calculated.get("totalPricePerPiece", {}).get("value", price_per_piece)
            
            farm, business_unit, company_from_stock_entry = get_farm_business_unit_company_from_stock_entry(trade_item_id, item_code)
            
            # Set company
            if company_from_stock_entry:
                sales_order.company = company_from_stock_entry
            elif settings and settings.company:
                sales_order.company = settings.company
            else:
                companies = frappe.get_all("Company", limit_page_length=1)
                if companies:
                    sales_order.company = companies[0].name
            
            # Use warehouse from Floriday Settings
            item_warehouse = warehouse
            
            if not item_warehouse:
                item_defaults = frappe.get_all(
                    "Item Default",
                    fields=["default_warehouse"],
                    filters={"parent": item_code, "company": sales_order.company}
                )
                if item_defaults and item_defaults[0].default_warehouse:
                    item_warehouse = item_defaults[0].default_warehouse
                else:
                    warehouses = frappe.get_all(
                        "Warehouse",
                        filters={"company": sales_order.company, "is_group": 0},
                        fields=["name"],
                        limit_page_length=1
                    )
                    if warehouses:
                        item_warehouse = warehouses[0].name
                    else:
                        frappe.throw(f"No warehouse found for item {item_code}")
            
            # Create item
            item = sales_order.append("items", {})
            item.item_code = item_code
            item.qty = number_of_pieces
            item.rate = total_price_per_piece
            item.delivery_date = delivery_datetime.date()
            item.warehouse = item_warehouse
            item.custom_ordered_quantity = number_of_pieces
            item.custom_source_warehouse = item_warehouse
            
            # Set farm and business unit
            if farm:
                sales_order.custom_farm = farm
            if business_unit:
                sales_order.custom_business_unit = business_unit

    if not sales_order.items:
        frappe.throw(f"No valid items found")

    # Set ordered stems
    total_ordered_stems = floriday_order.get("numberOfPieces", 0)
    if total_ordered_stems == 0:
        for item in sales_order.items:
            total_ordered_stems += item.qty
    
    if hasattr(sales_order, 'custom_ordered_stems'):
        sales_order.custom_ordered_stems = total_ordered_stems

    # Set conversion rate
    if sales_order.company:
        company_currency = frappe.get_cached_value('Company', sales_order.company, 'default_currency')
        
        if transaction_currency != company_currency:
            exchange_rate = get_exchange_rate(transaction_currency, company_currency, order_datetime)
            sales_order.conversion_rate = exchange_rate or 1.0

    # Validate and submit
    sales_order.run_method('validate')
    sales_order.run_method('calculate_taxes_and_totals')
    
    sales_order.insert(ignore_permissions=True)
    sales_order.submit()
    
    return sales_order


def get_farm_business_unit_company_from_stock_entry(trade_item_id, item_code):
    """
    Get farm, business unit, and company from the latest Stock Entry
    """
    try:
        farm = None
        business_unit = None
        company = None
        
        stock_entry_details = frappe.get_all(
            "Stock Entry Detail",
            fields=["parent"],
            filters={
                "item_code": item_code,
                "docstatus": 1
            },
            order_by="creation DESC",
            limit_page_length=1
        )
        
        if stock_entry_details:
            stock_entry_name = stock_entry_details[0].parent
            stock_entry = frappe.get_doc("Stock Entry", stock_entry_name)
            
            farm = stock_entry.get('custom_farm')
            business_unit = stock_entry.get('custom_business_unit')
            company = stock_entry.company
        
        if not company:
            companies = frappe.get_all("Company", limit_page_length=1)
            if companies:
                company = companies[0].name
        
        return farm, business_unit, company
        
    except Exception:
        return None, None, None


def get_exchange_rate(from_currency, to_currency, date):
    """
    Get exchange rate between currencies
    """
    try:
        exchange_rate = frappe.db.sql("""
            SELECT exchange_rate
            FROM `tabCurrency Exchange`
            WHERE from_currency = %s AND to_currency = %s AND date <= %s
            ORDER BY date DESC
            LIMIT 1
        """, (from_currency, to_currency, date), as_dict=True)

        return exchange_rate[0].exchange_rate if exchange_rate else None
    except Exception:
        return None


def get_or_create_customer(floriday_order):
    """
    Gets or creates a customer based on Floriday order data.
    Matches using custom_floriday_id field on Customer doctype.
    """
    if not floriday_order:
        frappe.throw("No order data provided")
    
    # Get the Floriday customer/organization ID (UUID format)
    customer_org_id = floriday_order.get('customerOrganizationId')
    if not customer_org_id:
        log_short("No customerOrganizationId in Floriday order", "Floriday Customer Warning", True)
        # Fallback to default customer
        return get_default_customer()
    
    log_short(f"Looking for customer with Floriday ID: {customer_org_id[:8]}...", "Floriday Customer Lookup", False)
    
    # STEP 1: Try to find customer by custom_floriday_id field
    customer_name = frappe.db.get_value(
        "Customer", 
        {"custom_floriday_id": customer_org_id}, 
        "name"
    )
    
    if customer_name:
        # Found existing customer with matching Floriday ID
        log_short(f"Found customer {customer_name} with Floriday ID", "Floriday Customer Match", False)
        return customer_name
    
    # STEP 2: If not found by ID, try to find by customer name (if available in Floriday)
    # Some Floriday orders might include the customer name
    floriday_customer_name = floriday_order.get('customerName') or floriday_order.get('consigneeName')
    
    if floriday_customer_name:
        # Check if customer exists with this exact name
        if frappe.db.exists("Customer", floriday_customer_name):
            customer_name = floriday_customer_name
            # Update this customer with the Floriday ID for future lookups
            frappe.db.set_value("Customer", customer_name, "custom_floriday_id", customer_org_id)
            log_short(f"Updated customer {customer_name} with Floriday ID", "Floriday Customer Updated", False)
            return customer_name
        
        # Try to find by partial name match (case insensitive)
        customers = frappe.get_all(
            "Customer",
            filters={"customer_name": ["like", f"%{floriday_customer_name}%"]},
            limit=1
        )
        if customers:
            customer_name = customers[0].name
            # Update with Floriday ID
            frappe.db.set_value("Customer", customer_name, "custom_floriday_id", customer_org_id)
            log_short(f"Updated customer {customer_name} with Floriday ID (partial match)", "Floriday Customer Updated", False)
            return customer_name
    
    # STEP 3: Create new customer
    return create_new_customer(floriday_order, customer_org_id)


def create_new_customer(floriday_order, customer_org_id):
    """
    Creates a new customer with Floriday ID
    """
    # Get customer name from Floriday if available
    floriday_customer_name = floriday_order.get('customerName') or floriday_order.get('consigneeName')
    
    if not floriday_customer_name:
        # If no name provided, create a placeholder name
        floriday_customer_name = f"Consignee {customer_org_id[:8]}"
    
    try:
        customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": floriday_customer_name,
            "custom_floriday_id": customer_org_id,  # Store the UUID
            "customer_type": "Company",
            "customer_group": "Commercial",  # Default, can be configured
            "territory": "Netherlands",  # Default, can be configured
        })
        customer.insert(ignore_permissions=True)
        
        log_short(f"Created new customer: {floriday_customer_name} with Floriday ID", "Floriday Customer Created", False)
        return customer.name
        
    except Exception as e:
        log_short(f"Customer creation error: {str(e)[:50]}", "Floriday Customer Error", True)
        # Return default customer as last resort
        return get_default_customer()


def get_default_customer():
    """
    Returns a default customer for orders without valid customer mapping
    """
    default_customer = "Floriday-Default-Customer"
    
    # Create default customer if it doesn't exist
    if not frappe.db.exists("Customer", default_customer):
        try:
            customer = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": default_customer,
                "customer_type": "Company",
                "customer_group": "Commercial",
                "territory": "Netherlands",
            })
            customer.insert(ignore_permissions=True)
            log_short("Created default Floriday customer", "Floriday Customer Created", False)
        except Exception as e:
            log_short(f"Default customer creation error: {str(e)[:30]}", "Floriday Customer Error", True)
    
    return default_customer


def get_erpnext_item_code(floriday_trade_item_id):
    """
    Get ERPNext item code from Floriday trade item ID
    """
    try:
        mappings = frappe.get_all(
            "Floriday Item Mapping",
            fields=["item_code"],
            filters={"trade_item_id": floriday_trade_item_id}
        )
        
        if mappings:
            item_code = mappings[0].item_code
            if frappe.db.exists("Item", item_code):
                return item_code

        item = frappe.db.get_value("Item", {"floriday_trade_item_id": floriday_trade_item_id}, "name")
        if item:
            return item

        frappe.throw(f"No item mapping for {floriday_trade_item_id}")
    except Exception as e:
        log_short(f"Item error: {str(e)[:30]}", "Floriday Item Error", True)
        raise


def parse_delivery_date(delivery_date_str):
    """Parse delivery date"""
    if not delivery_date_str:
        return datetime.now(timezone.utc) + timedelta(days=1)
    
    try:
        if '.' in delivery_date_str and 'Z' in delivery_date_str:
            return datetime.strptime(delivery_date_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        elif 'T' in delivery_date_str and 'Z' in delivery_date_str:
            return datetime.strptime(delivery_date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        else:
            return datetime.fromisoformat(delivery_date_str.replace('Z', '+00:00'))
    except Exception:
        return datetime.now(timezone.utc) + timedelta(days=1)


def parse_order_date(order_date_str):
    """Parse order date"""
    if not order_date_str:
        return datetime.now(timezone.utc)
    
    try:
        if '.' in order_date_str and 'Z' in order_date_str:
            return datetime.strptime(order_date_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        elif 'T' in order_date_str and 'Z' in order_date_str:
            return datetime.strptime(order_date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        else:
            return datetime.fromisoformat(order_date_str.replace('Z', '+00:00'))
    except Exception:
        return datetime.now(timezone.utc)


@frappe.whitelist()
def get_sync_status():
    """
    Returns the status of the last Floriday sync operation
    """
    try:
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


# Optional: One-time migration script to update existing customers
@frappe.whitelist()
def migrate_existing_customers():
    """
    One-time script to list existing Floriday customers that need mapping
    """
    customers = frappe.get_all(
        "Customer", 
        filters={
            "name": ["like", "Floriday-%"],
        },
        fields=["name", "custom_floriday_id"]
    )
    
    migrated = 0
    for cust in customers:
        log_short(f"Customer to migrate: {cust.name} with ID: {cust.custom_floriday_id[:8] if cust.custom_floriday_id else 'None'}", 
                 "Floriday Migration", False)
        migrated += 1
    
    return f"Found {migrated} customers to potentially migrate"


