import frappe
import requests
import json
from datetime import datetime, timedelta, timezone

_logger = frappe.logger("floriday", allow_site=True)

def log_short(msg, title="Floriday", is_error=True):
    """Log errors and successful sales order creations"""
    if len(msg) > 135:
        msg = msg[:132] + "..."
    if is_error:
        frappe.log_error(msg, title)
    else:
        _logger.info(f"[{title}] {msg}")

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

def get_delivery_point_from_floriday_gln(gln_code):
    """
    Maps a Floriday GLN code to an ERPNext Delivery Point using custom_floriday_delivery_id field.
    Returns the delivery point name if found, otherwise returns None.
    """
    if not gln_code:
        frappe.log_error(
            title="Floriday - GLN Lookup Failed",
            message="No GLN code provided for delivery point lookup"
        )
        return None
    
    try:
        # Debug: Log the search attempt
        frappe.log_error(
            title="Floriday - Looking for Delivery Point",
            message=f"Searching for Delivery Point with custom_floriday_delivery_id = '{gln_code}'"
        )
        
        # Try to find delivery point by custom_floriday_delivery_id field
        delivery_points = frappe.get_all(
            "Delivery Point",
            filters={"custom_floriday_delivery_id": gln_code},
            fields=["name", "custom_floriday_delivery_id"]
        )
        
        # Debug: Log what was found
        frappe.log_error(
            title="Floriday - Delivery Point Search Results",
            message=f"Found {len(delivery_points)} delivery points for GLN {gln_code}\n"
                    f"Results: {json.dumps(delivery_points, indent=2, default=str)}"
        )
        
        if delivery_points:
            delivery_point = delivery_points[0].name
            log_short(f"Mapped Floriday GLN {gln_code} to Delivery Point: {delivery_point}", 
                     "Floriday Delivery Point Match", False)
            return delivery_point
        else:
            # Log all available delivery points for debugging
            all_delivery_points = frappe.get_all("Delivery Point", fields=["name", "custom_floriday_delivery_id"])
            frappe.log_error(
                title="Floriday - No Delivery Point Match Found",
                message=f"Could not find Delivery Point for Floriday GLN: {gln_code}\n\n"
                        f"All available Delivery Points:\n{json.dumps(all_delivery_points, indent=2, default=str)}\n\n"
                        f"Please ensure one of these Delivery Points has custom_floriday_delivery_id = '{gln_code}'"
            )
            return None
            
    except Exception as e:
        frappe.log_error(
            title="Floriday - Delivery Point Lookup Error",
            message=f"Error mapping GLN {gln_code}: {str(e)}\n\nTraceback: {frappe.get_traceback()}"
        )
        return None

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

        # Set date range for last 1 hour
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(hours=1)

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

        # Log first sales order JSON for examination
        if orders and len(orders) > 0:
            first_order = orders[0]
            first_order_json = json.dumps(first_order, indent=2, default=str)
            
            frappe.log_error(
                title="Floriday - First Sales Order JSON",
                message=f"First sales order received from Floriday API:\n\n{first_order_json}\n\n"
                        f"Total orders received: {len(orders)}\n"
                        f"Date range: {start_date.isoformat()} to {end_date.isoformat()}"
            )
            
            log_short(f"First order ID: {first_order.get('salesOrderId', 'N/A')} - Total orders: {len(orders)}", 
                     "Floriday First Order", False)

        if len(orders) >= 1000:
            log_short(f"API returned {len(orders)} orders — pagination limit may be hit", "Floriday Pagination Warning", True)

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
                order_dt = parse_floriday_datetime(order_dt_str)
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
                sales_order = create_sales_order_from_floriday(order, WAREHOUSE, settings)
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


def create_sales_order_from_floriday(floriday_order, warehouse, settings=None):
    """
    Creates a Sales Order in ERPNext from a Floriday order.
    Extracts and saves delivery location GLN to custom_delivery_point field.
    """
    floriday_order_id = floriday_order.get("salesOrderId")
    if not floriday_order_id:
        frappe.throw("Floriday order missing salesOrderId")

    if frappe.db.exists("Sales Order", {"po_no": floriday_order_id}):
        frappe.throw(f"Sales Order already exists")

    # Get or create customer using Floriday ID mapping
    customer = get_or_create_customer(floriday_order)

    delivery_datetime = parse_floriday_datetime(floriday_order.get("delivery", {}).get("latestDeliveryDateTime"), default=datetime.now(timezone.utc) + timedelta(days=1))
    order_datetime = parse_floriday_datetime(floriday_order.get("orderDateTime"))

    # Extract delivery location GLN from Floriday order
    delivery_gln = None
    delivery_address = None
    delivery_city = None
    delivery_country = None
    delivery_postal_code = None
    
    delivery_info = floriday_order.get("delivery", {})
    if delivery_info:
        location_info = delivery_info.get("location", {})
        if location_info:
            delivery_gln = location_info.get("gln")
            
            # Extract address details if available
            address_info = location_info.get("address", {})
            if address_info:
                delivery_address = address_info.get("addressLine")
                delivery_city = address_info.get("city")
                delivery_country = address_info.get("countryCode")
                delivery_postal_code = address_info.get("postalCode")
    
    # Log the extracted GLN
    frappe.log_error(
        title="Floriday - Extracted GLN from Order",
        message=f"Order ID: {floriday_order_id}\n"
                f"Extracted GLN: {delivery_gln}\n"
                f"Full delivery info: {json.dumps(delivery_info, indent=2, default=str)}"
    )
    
    # Map Floriday GLN to Delivery Point using custom_floriday_delivery_id field
    delivery_point_name = None
    if delivery_gln:
        delivery_point_name = get_delivery_point_from_floriday_gln(delivery_gln)
        if delivery_point_name:
            frappe.log_error(
                title="Floriday - Delivery Point Found",
                message=f"Successfully mapped GLN {delivery_gln} to Delivery Point: {delivery_point_name}"
            )
        else:
            # Log specific error for missing mapping
            frappe.log_error(
                title="Floriday - Missing Delivery Point Mapping",
                message=f"Could not find Delivery Point for Floriday GLN: {delivery_gln}\n\n"
                        f"Order ID: {floriday_order_id}\n"
                        f"Please map this GLN to a Delivery Point using the custom_floriday_delivery_id field.\n\n"
                        f"To map: Update a Delivery Point record and set custom_floriday_delivery_id = '{delivery_gln}'"
            )
    else:
        frappe.log_error(
            title="Floriday - No GLN in Order",
            message=f"Order {floriday_order_id} has no delivery GLN in the payload"
        )
    
    sales_order = frappe.new_doc("Sales Order")
    sales_order.customer = customer
    sales_order.transaction_date = order_datetime.date()
    sales_order.delivery_date = delivery_datetime.date()
    sales_order.order_type = "Sales"
    sales_order.po_no = floriday_order_id
    sales_order.po_date = order_datetime.date()

    sales_order.custom_sales_order_type = "Roses"
    sales_order.custom_order_name = generate_custom_order_name(customer)
    
    # Set the delivery point if found
    if delivery_point_name:
        sales_order.custom_delivery_point = delivery_point_name
        log_short(f"Order {floriday_order_id} assigned to Delivery Point: {delivery_point_name}", 
                 "Floriday Delivery Point Assigned", False)
    else:
        # If no delivery point found, still save the GLN for reference
        sales_order.custom_floriday_delivery_gln = delivery_gln
        log_short(f"Order {sales_order.name} created WITHOUT Delivery Point mapping for GLN: {delivery_gln}", 
                 "Floriday Order Complete - Warning", True)
    
    # Optionally save address details if you have custom fields for them
    if hasattr(sales_order, 'custom_delivery_address') and delivery_address:
        sales_order.custom_delivery_address = delivery_address
    if hasattr(sales_order, 'custom_delivery_city') and delivery_city:
        sales_order.custom_delivery_city = delivery_city
    if hasattr(sales_order, 'custom_delivery_country') and delivery_country:
        sales_order.custom_delivery_country = delivery_country
    if hasattr(sales_order, 'custom_delivery_postal_code') and delivery_postal_code:
        sales_order.custom_delivery_postal_code = delivery_postal_code

    # Set currency
    price_info = floriday_order.get("pricePerPiece", {})
    transaction_currency = price_info.get("currency", "EUR")
    sales_order.currency = transaction_currency

    sales_order.notes = f"""Floriday Order: {floriday_order.get("salesOrderId")}
Channel: {floriday_order.get("salesChannel")}
Supplier: {floriday_order.get("supplierOrganizationId")}
Delivery GLN: {delivery_gln if delivery_gln else 'Not provided'}
Delivery Point: {delivery_point_name if delivery_point_name else 'Not mapped'}"""

    # Add items
    trade_item_id = floriday_order.get("tradeItemId")

    if trade_item_id:
        item_code = get_erpnext_item_code(trade_item_id)
        if item_code:
            number_of_pieces = floriday_order.get("numberOfPieces", 0)

            calculated = floriday_order.get("calculatedFields", {})
            total_price_per_piece = calculated.get("totalPricePerPiece", {}).get("value", price_info.get("value", 0))

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
    
    # Log final confirmation
    if delivery_point_name:
        log_short(f"Order {sales_order.name} created with Delivery Point: {delivery_point_name}", 
                 "Floriday Order Complete", False)
    else:
        log_short(f"Order {sales_order.name} created WITHOUT Delivery Point mapping for GLN: {delivery_gln}", 
                 "Floriday Order Complete - Warning", True)

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
    except frappe.exceptions.DuplicateEntryError:
        frappe.db.rollback()
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
            return mappings[0].item_code

        item = frappe.db.get_value("Item", {"floriday_trade_item_id": floriday_trade_item_id}, "name")
        if item:
            return item

        frappe.throw(f"No item mapping for {floriday_trade_item_id}")
    except Exception as e:
        log_short(f"Item error: {str(e)[:30]}", "Floriday Item Error", True)
        raise


def parse_floriday_datetime(date_str, default=None):
    """Parse a Floriday datetime string, returning default (or datetime.now(utc)) on failure"""
    if default is None:
        default = datetime.now(timezone.utc)
    if not date_str:
        return default
    try:
        if '.' in date_str and 'Z' in date_str:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        elif 'T' in date_str and 'Z' in date_str:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        else:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except Exception:
        return default


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


# Helper function to manually map a Floriday GLN to a Delivery Point
@frappe.whitelist()
def map_delivery_point(floriday_gln, delivery_point_name):
    """
    Manually map a Floriday GLN to an ERPNext Delivery Point.
    This updates the Delivery Point doctype with the custom_floriday_delivery_id field.
    """
    try:
        if not floriday_gln or not delivery_point_name:
            return {"status": "error", "message": "Missing GLN or Delivery Point name"}
        
        # Check if delivery point exists
        if not frappe.db.exists("Delivery Point", delivery_point_name):
            return {"status": "error", "message": f"Delivery Point {delivery_point_name} not found"}
        
        # Update the delivery point with the Floriday GLN
        frappe.db.set_value("Delivery Point", delivery_point_name, "custom_floriday_delivery_id", floriday_gln)
        
        log_short(f"Mapped Floriday GLN {floriday_gln} to Delivery Point {delivery_point_name}", 
                 "Floriday Delivery Point Mapping", False)
        
        return {"status": "success", "message": f"Mapped GLN {floriday_gln} to {delivery_point_name}"}
        
    except Exception as e:
        log_short(f"Error mapping delivery point: {str(e)[:50]}", "Floriday Mapping Error", True)
        return {"status": "error", "message": str(e)}


# Helper function to check what GLNs are currently mapped
@frappe.whitelist()
def get_mapped_delivery_points():
    """
    Returns all Delivery Points that have custom_floriday_delivery_id set
    """
    try:
        delivery_points = frappe.get_all(
            "Delivery Point",
            filters={"custom_floriday_delivery_id": ["!=", ""]},
            fields=["name", "custom_floriday_delivery_id"]
        )
        return {
            "status": "success",
            "mappings": delivery_points,
            "count": len(delivery_points)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}