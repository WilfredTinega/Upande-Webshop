import frappe
import requests
import uuid
import json
from datetime import datetime, timezone, timedelta

# Currency configuration - Set this to either "EUR" or "USD"
SUPPLY_LINE_CURRENCY = "EUR"  # Change to "USD" if you want to use US Dollars

# East Africa Time (EAT) is UTC+3
EAT_OFFSET = timedelta(hours=3)

# Maximum log message length to prevent truncation errors
MAX_LOG_LENGTH = 100

def safe_log(message, title="Floriday Log"):
    """
    Safely log messages ensuring they never exceed length limits
    """
    if not message:
        return
    if not title:
        title = "Floriday Log"
    
    # Truncate message if too long
    if len(message) > MAX_LOG_LENGTH:
        message = message[:MAX_LOG_LENGTH-3] + "..."
    
    # Truncate title if too long
    if len(title) > 100:
        title = title[:97] + "..."
    
    try:
        frappe.log_error(message, title)
    except:
        pass

def get_item_mapping():
    """
    Fetch item mappings from Floriday Item Mapping doctype
    """
    try:
        mappings = frappe.get_all(
            "Floriday Item Mapping",
            fields=["item_code", "trade_item_id"]
        )
        
        # Create mapping dictionary from doctype records
        ITEM_MAPPING = {}
        for mapping in mappings:
            ITEM_MAPPING[mapping.item_code] = mapping.trade_item_id
        
        safe_log(f"Loaded {len(ITEM_MAPPING)} item mappings", "Floriday Item Mapping")
        return ITEM_MAPPING
        
    except Exception as e:
        safe_log("Error fetching item mappings", "Floriday Item Mapping Error")
        return {}

def get_source_warehouse():
    """
    Fetch source warehouse from Floriday Settings
    """
    try:
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            frappe.throw("Floriday Settings not configured")

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
        source_warehouse = settings.warehouse
        
        if not source_warehouse:
            frappe.throw("Warehouse not configured in Floriday Settings")
            
        safe_log(f"Using source warehouse: {source_warehouse}", "Floriday Warehouse")
        return source_warehouse
        
    except Exception as e:
        error_msg = f"Error fetching source warehouse"
        safe_log(error_msg, "Floriday Warehouse Error")
        frappe.throw(error_msg)

@frappe.whitelist()
def create_supply_lines_only_from_batches():
    """
    Create ONLY supply lines from available batches - no customer offers
    Fetches batches for CURRENT DATE only with proper EAT timezone conversion
    """
    try:
        safe_log("Starting supply line creation", "Floriday Supply Lines")
        
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            error_msg = "Floriday Settings not configured"
            safe_log(error_msg, "Floriday Settings Error")
            frappe.throw(error_msg)

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)

        API_KEY = settings.api_key
        BASE_URL = settings.base_url
        ACCESS_TOKEN = settings.access_token
        SUPPLIER_ORG_ID = settings.organization_supplier_id

        # Get current date for filtering (in EAT timezone)
        current_date = (datetime.now(timezone.utc) + EAT_OFFSET).strftime('%Y-%m-%d')
        safe_log(f"Filtering for EAT date: {current_date}", "Floriday Date")
        
        # Get ALL batches first
        all_batches = get_your_floriday_batches(BASE_URL, API_KEY, ACCESS_TOKEN, SUPPLIER_ORG_ID)
        
        if not all_batches:
            error_msg = "No batches found for your organization"
            safe_log(error_msg, "Floriday Batches")
            return {"status": "failed", "message": error_msg}

        safe_log(f"Retrieved {len(all_batches)} total batches", "Floriday Batches")

        # Filter batches for current date - USING EAT TIMEZONE VERSION
        your_batches = filter_batches_by_date_eat(all_batches, current_date)
        safe_log(f"Found {len(your_batches)} batches for EAT today", "Floriday Today's Batches")

        if not your_batches:
            result_msg = {
                "status": "failed",
                "message": f"No batches found for EAT today ({current_date})", 
                "total_batches": len(all_batches),
                "todays_batches": 0,
                "date_applied": current_date
            }
            return result_msg

        safe_log("Filtering batches with available pieces", "Floriday Availability")
        available_batches = filter_available_batches_fixed(your_batches)
        
        safe_log(f"Found {len(available_batches)} batches with available pieces", "Floriday Available")

        if not available_batches:
            result_msg = {
                "status": "failed",
                "message": f"No batches with available pieces found for EAT today ({current_date})", 
                "total_batches": len(all_batches),
                "todays_batches": len(your_batches),
                "available_batches": 0,
                "date_applied": current_date
            }
            return result_msg

        safe_log("Creating supply lines", "Floriday Creation")
        results = create_supply_lines_only(BASE_URL, API_KEY, ACCESS_TOKEN, available_batches)
        
        successful_supply_lines = [r for r in results if r.get('status') == 'success']
        failed_supply_lines = [r for r in results if r.get('status') != 'success']
        
        safe_log(f"Results: {len(successful_supply_lines)} success, {len(failed_supply_lines)} failed", "Floriday Complete")

        if not successful_supply_lines:
            result_msg = {
                "status": "failed",
                "message": "Failed to create any supply lines", 
                "details": results,
                "available_batches_processed": len(available_batches),
                "date_applied": current_date
            }
            return result_msg

        success_result = {
            "status": "success",
            "message": f"Created {len(successful_supply_lines)} supply lines from {len(available_batches)} available batches for EAT {current_date}",
            "supply_lines_created": successful_supply_lines,
            "failed_supply_lines": failed_supply_lines,
            "total_processed": len(results),
            "total_batches": len(all_batches),
            "todays_batches": len(your_batches),
            "date_applied": current_date,
            "currency_used": SUPPLY_LINE_CURRENCY,
            "note": "SUPPLY LINES ONLY - No customer offers created - EAT CURRENT DATE BATCHES ONLY"
        }
        
        return success_result

    except Exception as e:
        error_msg = f"Unexpected error"
        safe_log(error_msg, "Floriday Error")
        return {"status": "error", "message": f"Error: {str(e)[:100]}"}

def filter_batches_by_date_eat(batches, target_date):
    """
    Filter batches by date using EAT timezone conversion (UTC+3)
    """
    try:
        todays_batches = []
        
        for batch in batches:
            batch_id = batch.get("batchId", "unknown")
            batch_date_str = batch.get("batchDate")
            
            if batch_date_str:
                try:
                    # Parse the UTC datetime string
                    if batch_date_str.endswith('Z'):
                        batch_dt_utc = datetime.fromisoformat(batch_date_str.replace('Z', '+00:00'))
                    else:
                        batch_dt_utc = datetime.fromisoformat(batch_date_str)
                    
                    # Ensure it's UTC timezone aware
                    if batch_dt_utc.tzinfo is None:
                        batch_dt_utc = batch_dt_utc.replace(tzinfo=timezone.utc)
                    
                    # Convert UTC to EAT (UTC+3)
                    batch_dt_eat = batch_dt_utc + EAT_OFFSET
                    
                    # Extract EAT date for comparison
                    batch_eat_date = batch_dt_eat.strftime('%Y-%m-%d')
                    
                    if batch_eat_date == target_date:
                        todays_batches.append(batch)
                        
                except Exception:
                    # Fallback to simple string matching
                    if target_date in batch_date_str:
                        todays_batches.append(batch)
        
        return todays_batches
        
    except Exception as e:
        return []

def filter_batches_by_date_utc(batches, target_date):
    """
    Filter batches by date using UTC comparison
    """
    try:
        todays_batches = []
        
        # Convert target_date to UTC datetime range
        target_dt = datetime.strptime(target_date, '%Y-%m-%d')
        utc_start = datetime(target_dt.year, target_dt.month, target_dt.day, 0, 0, 0, tzinfo=timezone.utc)
        utc_end = datetime(target_dt.year, target_dt.month, target_dt.day, 23, 59, 59, tzinfo=timezone.utc)
        
        for batch in batches:
            batch_id = batch.get("batchId", "unknown")
            batch_date_str = batch.get("batchDate")
            
            if batch_date_str:
                try:
                    # Parse the UTC datetime string
                    if batch_date_str.endswith('Z'):
                        batch_dt = datetime.fromisoformat(batch_date_str.replace('Z', '+00:00'))
                    else:
                        batch_dt = datetime.fromisoformat(batch_date_str)
                    
                    # Ensure it's UTC timezone aware
                    if batch_dt.tzinfo is None:
                        batch_dt = batch_dt.replace(tzinfo=timezone.utc)
                    
                    # Check if batch datetime falls within the target UTC day
                    if utc_start <= batch_dt <= utc_end:
                        todays_batches.append(batch)
                        
                except Exception:
                    # Fallback to simple string matching
                    if target_date in batch_date_str:
                        todays_batches.append(batch)
        
        return todays_batches
        
    except Exception as e:
        return []

def filter_available_batches_fixed(batches):
    """
    FIXED: Filter batches that have available pieces
    Uses numberOfPieces field from your batch structure
    """
    try:
        available_batches = []
        
        for batch in batches:
            batch_id = batch.get("batchId", "unknown")
            
            # Use numberOfPieces field from your batch structure
            available_pieces = batch.get("numberOfPieces", 0)
            
            if available_pieces > 0:
                batch['available_pieces'] = available_pieces
                available_batches.append(batch)
        
        return available_batches
        
    except Exception as e:
        return []

# Replace the old functions with the fixed versions
def filter_batches_by_date(batches, target_date):
    """Alias for the EAT function for backward compatibility"""
    return filter_batches_by_date_eat(batches, target_date)

def filter_available_batches(batches):
    """Alias for the fixed function for backward compatibility"""
    return filter_available_batches_fixed(batches)

def create_supply_lines_only(BASE_URL, API_KEY, ACCESS_TOKEN, batches):
    """
    Create only supply lines without customer offers
    """
    try:
        results = []
        total_batches = min(len(batches), 10)  # Limit to 10 batches
        
        for i, batch in enumerate(batches[:10]):
            batch_id = batch.get("batchId")
            
            # Create supply line directly
            result = create_single_supply_line(BASE_URL, API_KEY, ACCESS_TOKEN, batch)
            results.append(result)
            
            frappe.db.commit()
            import time
            time.sleep(1)  # Small delay between API calls
        
        return results
        
    except Exception as e:
        safe_log("Error in supply line creation", "Floriday Error")
        return []

def create_single_supply_line(BASE_URL, API_KEY, ACCESS_TOKEN, batch):
    """
    Create a single supply line with proper payload structure
    """
    try:
        batch_id = batch.get("batchId")
        trade_item_id = batch.get("tradeItemId")
        available_pieces = batch.get("available_pieces", 0)
        warehouse_id = batch.get("warehouseId")
        
        if available_pieces <= 0:
            return {"status": "failed", "message": "No pieces", "batch_id": batch_id}

        if not warehouse_id:
            return {"status": "failed", "message": "No warehouse", "batch_id": batch_id}

        # Get price from ERPNext Item based on trade_item_id
        offer_price = get_item_price_from_erpnext(trade_item_id)
        if not offer_price:
            offer_price = 0.40  # Default price
            
        now = datetime.now(timezone.utc)
        order_end = now + timedelta(days=7)
        
        # Get packing configuration from batch or use default
        packing_config = batch.get("packingConfiguration", get_default_packing_config())
        
        # Create supply line payload
        supply_line_payload = {
            "supplyLineId": str(uuid.uuid4()),
            "tradeItemId": trade_item_id,
            "warehouseId": warehouse_id,
            "numberOfPieces": available_pieces,
            "pricePerPiece": {
                "currency": SUPPLY_LINE_CURRENCY,  
                "value": float(offer_price)
            },
            "orderPeriod": {
                "startDateTime": now.isoformat(),
                "endDateTime": order_end.isoformat()
            },
            "deliveryPeriod": {
                "startDateTime": now.isoformat(),
                "endDateTime": order_end.isoformat()
            },
            "allowedCustomerOrganizationIds": [],  # Empty for public
            "batchId": batch_id,
            "salesUnit": "PIECE",
            "packingConfigurations": [packing_config],
            "includedServices": ["DELIVERY"],
            "availability": "LIMITED"
        }
        
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        base_url_clean = BASE_URL.rstrip('/')
        supply_line_endpoint = f"{base_url_clean}/supply-lines"
        
        response = requests.post(
            supply_line_endpoint,
            json=supply_line_payload,
            headers=headers,
            timeout=30
        )

        # Handle 200/201 success responses
        if response.status_code in (200, 201):
            supply_line_id = supply_line_payload["supplyLineId"]
            
            return {
                "status": "success",
                "supply_line_id": supply_line_id,
                "batch_id": batch_id,
                "trade_item_id": trade_item_id,
                "offered_quantity": available_pieces,
                "offer_price": offer_price,
                "currency": SUPPLY_LINE_CURRENCY,
                "warehouse_id": warehouse_id,
                "type": "supply_line"
            }
        else:
            error_msg = f"Failed: {response.status_code}"
            return {"status": "failed", "message": error_msg, "batch_id": batch_id}

    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": "Request error", "batch_id": batch_id}
    except Exception as e:
        return {"status": "error", "message": "Error", "batch_id": batch_id}

def get_item_price_from_erpnext(trade_item_id):
    """
    Get item price from ERPNext based on trade_item_id using the ITEM_MAPPING
    """
    try:
        # Get dynamic item mapping
        ITEM_MAPPING = get_item_mapping()
        
        # Reverse lookup: find ERPNext item code from Floriday trade_item_id
        erpnext_item_code = None
        for erp_code, floriday_id in ITEM_MAPPING.items():
            if floriday_id == trade_item_id:
                erpnext_item_code = erp_code
                break
        
        if not erpnext_item_code:
            return get_fallback_price(trade_item_id)
        
        # 1. Try to get price from Item Price list first
        price_list_price = get_price_from_price_list(erpnext_item_code)
        if price_list_price:
            return price_list_price
        
        # 2. Try to get price from Item master
        item_details = frappe.get_all("Item",
            filters={"name": erpnext_item_code},
            fields=["selling_rate", "valuation_rate"],
            limit=1
        )
        
        if item_details:
            # Try selling_rate from Item master
            if item_details[0].selling_rate:
                return float(item_details[0].selling_rate)
            
            # Try valuation_rate from Item master
            if item_details[0].valuation_rate:
                return float(item_details[0].valuation_rate)
        
        # 3. Fallback pricing
        fallback_price = get_fallback_price(trade_item_id)
        if fallback_price:
            return fallback_price
        
        return None
        
    except Exception as e:
        # Final emergency fallback
        return 0.40

def get_price_from_price_list(item_code, price_list="Standard Selling"):
    """
    Get price from Item Price doctype for the given item code and price list
    """
    try:
        item_prices = frappe.get_all("Item Price",
            filters={
                "item_code": item_code,
                "price_list": price_list,
                "selling": 1
            },
            fields=["price_list_rate"],
            order_by="valid_from desc, creation desc",
            limit=1
        )
        
        if item_prices and item_prices[0].price_list_rate:
            return float(item_prices[0].price_list_rate)
        
        # Try other price lists if Standard Selling not found
        other_price_lists = frappe.get_all("Price List", 
            filters={"selling": 1, "enabled": 1},
            fields=["name"]
        )
        
        for pl in other_price_lists:
            if pl.name != price_list:
                item_prices = frappe.get_all("Item Price",
                    filters={
                        "item_code": item_code,
                        "price_list": pl.name,
                        "selling": 1
                    },
                    fields=["price_list_rate"],
                    limit=1
                )
                if item_prices and item_prices[0].price_list_rate:
                    return float(item_prices[0].price_list_rate)
        
        return None
        
    except Exception as e:
        return None

def get_fallback_price(trade_item_id):
    """
    Fallback pricing when no direct price is found
    """
    try:
        # Method 1: Get average price from all Item Price records
        all_prices = frappe.get_all("Item Price",
            filters={"selling": 1, "price_list_rate": [">", 0]},
            fields=["price_list_rate"],
            limit=50
        )
        
        if all_prices:
            prices = [float(ip.price_list_rate) for ip in all_prices if ip.price_list_rate]
            if prices:
                avg_price = sum(prices) / len(prices)
                return round(avg_price, 2)
        
        # Method 2: Use hash-based consistent pricing
        import hashlib
        hash_val = int(hashlib.md5(trade_item_id.encode()).hexdigest()[:8], 16)
        base_price = 0.40 + (hash_val % 1000) / 1000 * 1.60  # Range: 0.40 to 2.00
        price = round(base_price, 2)
        return price
        
    except Exception as e:
        return 0.40  # Absolute fallback

def get_your_floriday_batches(BASE_URL, API_KEY, ACCESS_TOKEN, SUPPLIER_ORG_ID):
    """
    Get ALL batches from Floriday (no date filtering in API call)
    """
    try:
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Accept": "application/json"
        }
        
        base_url_clean = BASE_URL.rstrip('/')
        endpoint = f"{base_url_clean}/batches?supplierOrganizationId={SUPPLIER_ORG_ID}"
        
        response = requests.get(endpoint, headers=headers, timeout=30)
        
        if response.status_code == 200:
            batches = response.json()
            if isinstance(batches, list):
                return batches
            else:
                return []
        else:
            return []

    except Exception as e:
        return []

def get_default_packing_config():
    return {
        "piecesPerPackage": 200, 
        "vbnPackageCode": 884,
        "packagesPerLayer": 10,
        "layersPerLoadCarrier": 2,
        "loadCarrier": "AUCTION_TROLLEY",
        "transportHeightInCm": 100
    }

@frappe.whitelist()
def get_available_batches():
    """
    Returns batches with available pieces for CURRENT EAT DATE only
    """
    try:
        # Get current date in EAT timezone
        current_date = (datetime.now(timezone.utc) + EAT_OFFSET).strftime('%Y-%m-%d')
        
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            return {"status": "error", "message": "Floriday Settings not configured"}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)

        API_KEY = settings.api_key
        BASE_URL = settings.base_url
        ACCESS_TOKEN = settings.access_token
        SUPPLIER_ORG_ID = settings.organization_supplier_id 

        # Get ALL batches first
        all_batches = get_your_floriday_batches(BASE_URL, API_KEY, ACCESS_TOKEN, SUPPLIER_ORG_ID)
        
        if not all_batches:
            return {
                "status": "success",
                "batches": [],
                "total_batches": 0,
                "date_applied": current_date,
                "message": "No batches found"
            }
        
        # Filter for today's batches - USING EAT VERSION
        todays_batches = filter_batches_by_date_eat(all_batches, current_date)
        
        if not todays_batches:
            return {
                "status": "success",
                "batches": [],
                "total_batches": len(all_batches),
                "todays_batches": 0,
                "date_applied": current_date,
                "message": f"No batches found for EAT today ({current_date})"
            } 
        
        # Filter available batches - USING FIXED VERSION
        available_batches = filter_available_batches_fixed(todays_batches)
        
        batch_options = []
        for batch in available_batches:
            available_quantity = batch.get("available_pieces", 0)
            batch_options.append({
                "batch_id": batch.get("batchId"),
                "trade_item_id": batch.get("tradeItemId"),
                "trade_item_name": batch.get("tradeItemName", "Unknown Item"),
                "available_quantity": available_quantity,
                "batch_date": batch.get("batchDate"),
                "warehouse": batch.get("warehouseId"),
                "label": f"{batch.get('tradeItemName', 'Unknown Item')} - {available_quantity} pieces"
            })
        
        return {
            "status": "success",
            "batches": batch_options,
            "total_batches": len(all_batches),
            "todays_batches": len(todays_batches),
            "available_batches": len(batch_options),
            "date_applied": current_date,
            "note": f"Batches with available pieces for EAT today ({current_date})"
        }

    except Exception as e:
        return {"status": "error", "message": "Error fetching batches"}
