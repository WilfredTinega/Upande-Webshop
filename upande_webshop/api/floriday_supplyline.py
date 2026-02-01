import frappe
import requests
import uuid
import random
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

# Currency configuration - Set this to either "EUR" or "USD"
SUPPLY_LINE_CURRENCY = "EUR"  # Change to "USD" if you want to use US Dollars

# East Africa Time (EAT) is UTC+3
EAT_OFFSET = timedelta(hours=3)

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
        
        frappe.log_error(f"Loaded {len(ITEM_MAPPING)} item mappings from Floriday Item Mapping doctype", "Floriday Item Mapping")
        return ITEM_MAPPING
        
    except Exception as e:
        error_msg = f"Error fetching item mappings: {str(e)}"
        frappe.log_error(error_msg, "Floriday Item Mapping Error")
        # Return empty dict as fallback
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
            
        frappe.log_error(f"Using source warehouse: {source_warehouse}", "Floriday Warehouse")
        return source_warehouse
        
    except Exception as e:
        error_msg = f"Error fetching source warehouse: {str(e)}"
        frappe.log_error(error_msg, "Floriday Warehouse Error")
        frappe.throw(error_msg)

@frappe.whitelist()
def create_supply_lines_only_from_batches():
    """
    Create ONLY supply lines from available batches - no customer offers
    Fetches batches for CURRENT DATE only with proper EAT timezone conversion
    """
    try:
        frappe.log_error("Starting supply line creation only (no customer offers)", "Floriday Supply Lines Only")
        
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            error_msg = "Floriday Settings not configured"
            frappe.log_error(error_msg, "Floriday Settings Error")
            frappe.throw(error_msg)

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)

        API_KEY = settings.api_key
        BASE_URL = settings.base_url
        ACCESS_TOKEN = settings.access_token
        SUPPLIER_ORG_ID = settings.organization_supplier_id

        # Get current date for filtering (in EAT timezone)
        current_date = (datetime.now(timezone.utc) + EAT_OFFSET).strftime('%Y-%m-%d')
        frappe.log_error(f"Fetching batches from Floriday and filtering for EAT date: {current_date}", "Floriday Batch Retrieval")
        
        # Get ALL batches first
        all_batches = get_your_floriday_batches(BASE_URL, API_KEY, ACCESS_TOKEN, SUPPLIER_ORG_ID)
        
        if not all_batches:
            error_msg = f"No batches found for your organization"
            frappe.log_error(error_msg, "Floriday Supply Lines")
            return {"status": "failed", "message": error_msg}

        frappe.log_error(f"Retrieved {len(all_batches)} total batches", "Floriday Your Batches")

        # Filter batches for current date - USING EAT TIMEZONE VERSION
        your_batches = filter_batches_by_date_eat(all_batches, current_date)
        frappe.log_error(f"Found {len(your_batches)} batches for EAT today ({current_date})", "Floriday Today's Batches")

        if not your_batches:
            result_msg = {
                "status": "failed",
                "message": f"No batches found for EAT today ({current_date})", 
                "total_batches": len(all_batches),
                "todays_batches": 0,
                "date_applied": current_date
            }
            frappe.log_error(f"No batches for EAT today: {result_msg}", "Floriday Today's Batches Result")
            return result_msg

        frappe.log_error("Filtering batches with available pieces", "Floriday Availability Filtering")
        available_batches = filter_available_batches_fixed(your_batches)
        
        frappe.log_error(f"Found {len(available_batches)} batches with available pieces for EAT {current_date}", "Floriday Available Batches")

        if not available_batches:
            result_msg = {
                "status": "failed",
                "message": f"No batches with available pieces found for EAT today ({current_date})", 
                "total_batches": len(all_batches),
                "todays_batches": len(your_batches),
                "available_batches": 0,
                "date_applied": current_date
            }
            frappe.log_error(f"Availability filter failed: {result_msg}", "Floriday Availability Filter Result")
            return result_msg

        frappe.log_error("Creating supply lines only (no customer offers)", "Floriday Supply Line Creation")
        results = create_supply_lines_only(BASE_URL, API_KEY, ACCESS_TOKEN, available_batches)
        
        successful_supply_lines = [r for r in results if r.get('status') == 'success']
        failed_supply_lines = [r for r in results if r.get('status') != 'success']
        
        frappe.log_error(f"Supply line results: {len(successful_supply_lines)} successful, {len(failed_supply_lines)} failed", "Floriday Supply Lines")

        if not successful_supply_lines:
            result_msg = {
                "status": "failed",
                "message": "Failed to create any supply lines", 
                "details": results,
                "available_batches_processed": len(available_batches),
                "date_applied": current_date
            }
            frappe.log_error(f"Supply line creation failed: {result_msg}", "Floriday Supply Line Result")
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
        
        frappe.log_error(f"Supply line only process completed: {success_result}", "Floriday Supply Lines Success")
        return success_result

    except Exception as e:
        error_msg = f"Unexpected error in create_supply_lines_only_from_batches: {str(e)}"
        frappe.log_error(error_msg, "Floriday Supply Lines Error")
        return {"status": "error", "message": error_msg}

def filter_batches_by_date_eat(batches, target_date):
    """
    Filter batches by date using EAT timezone conversion (UTC+3)
    """
    try:
        todays_batches = []
        frappe.log_error(f"EAT: Filtering {len(batches)} batches for EAT date: {target_date}", "Floriday EAT Date Filter")
        
        for batch in batches:
            batch_id = batch.get("batchId", "unknown")
            batch_date_str = batch.get("batchDate")
            
            if batch_date_str:
                frappe.log_error(f"Batch {batch_id} has batchDate: {batch_date_str}", "Floriday Batch Date Debug")
                
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
                    
                    frappe.log_error(f"Batch {batch_id}: UTC={batch_dt_utc} -> EAT={batch_dt_eat} -> EAT Date={batch_eat_date}", "Floriday EAT Date Conversion")
                    
                    if batch_eat_date == target_date:
                        todays_batches.append(batch)
                        frappe.log_error(f"✅ EAT MATCH - Batch {batch_id} is from EAT today: {batch_eat_date}", "Floriday EAT Date Filter")
                    else:
                        frappe.log_error(f"❌ EAT NO MATCH - Batch {batch_id}: {batch_eat_date} vs EAT target: {target_date}", "Floriday EAT Date Filter")
                        
                except Exception as parse_error:
                    frappe.log_error(f"Error parsing date for batch {batch_id}: {str(parse_error)}", "Floriday Date Parse Error")
                    # Fallback to simple string matching
                    if target_date in batch_date_str:
                        todays_batches.append(batch)
                        frappe.log_error(f"✅ FALLBACK MATCH - Batch {batch_id}: {batch_date_str}", "Floriday Date Filter")
            else:
                frappe.log_error(f"Batch {batch_id} has NO batchDate field", "Floriday Batch Date Debug")
        
        frappe.log_error(f"EAT Date filter result: {len(todays_batches)} batches for EAT {target_date}", "Floriday EAT Date Filter Result")
        return todays_batches
        
    except Exception as e:
        error_msg = f"Error in filter_batches_by_date_eat: {str(e)}"
        frappe.log_error(error_msg, "Floriday EAT Date Filter Error")
        return []

def filter_batches_by_date_utc(batches, target_date):
    """
    Filter batches by date using UTC comparison
    """
    try:
        todays_batches = []
        frappe.log_error(f"UTC: Filtering {len(batches)} batches for date: {target_date}", "Floriday UTC Date Filter")
        
        # Convert target_date to UTC datetime range
        target_dt = datetime.strptime(target_date, '%Y-%m-%d')
        utc_start = datetime(target_dt.year, target_dt.month, target_dt.day, 0, 0, 0, tzinfo=timezone.utc)
        utc_end = datetime(target_dt.year, target_dt.month, target_dt.day, 23, 59, 59, tzinfo=timezone.utc)
        
        frappe.log_error(f"UTC Date range: {utc_start} to {utc_end}", "Floriday UTC Date Range")
        
        for batch in batches:
            batch_id = batch.get("batchId", "unknown")
            batch_date_str = batch.get("batchDate")
            
            if batch_date_str:
                frappe.log_error(f"Batch {batch_id} has batchDate: {batch_date_str}", "Floriday Batch Date Debug")
                
                try:
                    # Parse the UTC datetime string
                    if batch_date_str.endswith('Z'):
                        batch_dt = datetime.fromisoformat(batch_date_str.replace('Z', '+00:00'))
                    else:
                        batch_dt = datetime.fromisoformat(batch_date_str)
                    
                    # Ensure it's UTC timezone aware
                    if batch_dt.tzinfo is None:
                        batch_dt = batch_dt.replace(tzinfo=timezone.utc)
                    
                    frappe.log_error(f"Batch {batch_id}: Parsed UTC datetime: {batch_dt}", "Floriday UTC Date Parsing")
                    
                    # Check if batch datetime falls within the target UTC day
                    if utc_start <= batch_dt <= utc_end:
                        todays_batches.append(batch)
                        frappe.log_error(f" UTC MATCH - Batch {batch_id}: {batch_dt} is within {utc_start} to {utc_end}", "Floriday UTC Date Filter")
                    else:
                        frappe.log_error(f" UTC NO MATCH - Batch {batch_id}: {batch_dt} not in range {utc_start} to {utc_end}", "Floriday UTC Date Filter")
                        
                except Exception as parse_error:
                    frappe.log_error(f"Error parsing date for batch {batch_id}: {str(parse_error)}", "Floriday Date Parse Error")
                    # Fallback to simple string matching
                    if target_date in batch_date_str:
                        todays_batches.append(batch)
                        frappe.log_error(f"✅ FALLBACK MATCH - Batch {batch_id}: {batch_date_str}", "Floriday Date Filter")
            else:
                frappe.log_error(f"Batch {batch_id} has NO batchDate field", "Floriday Batch Date Debug")
        
        frappe.log_error(f"UTC Date filter result: {len(todays_batches)} batches for {target_date}", "Floriday UTC Date Filter Result")
        return todays_batches
        
    except Exception as e:
        error_msg = f"Error in filter_batches_by_date_utc: {str(e)}"
        frappe.log_error(error_msg, "Floriday UTC Date Filter Error")
        return []

def filter_available_batches_fixed(batches):
    """
    FIXED: Filter batches that have available pieces
    Uses numberOfPieces field from your batch structure
    """
    try:
        available_batches = []
        frappe.log_error(f"FIXED: Filtering {len(batches)} batches for available pieces", "Floriday Availability Filter")
        
        for batch in batches:
            batch_id = batch.get("batchId", "unknown")
            
            # FIX: Use numberOfPieces field from your batch structure
            available_pieces = batch.get("numberOfPieces", 0)
            
            if available_pieces > 0:
                batch['available_pieces'] = available_pieces
                available_batches.append(batch)
                frappe.log_error(f"Available batch: {batch_id} - {available_pieces} pieces", "Floriday Availability Filter")
            else:
                frappe.log_error(f"Skip batch: {batch_id} - {available_pieces} pieces (no availability)", "Floriday Availability Filter")
        
        frappe.log_error(f"FIXED Availability result: {len(available_batches)} batches", "Floriday Availability Filter Result")
        return available_batches
        
    except Exception as e:
        error_msg = f"Error in filter_available_batches_fixed: {str(e)}"
        frappe.log_error(error_msg, "Floriday Availability Filter Error")
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
        
        frappe.log_error(f"Starting supply line creation for {total_batches} batches", "Floriday Supply Line Creation Start")
        
        for i, batch in enumerate(batches[:10]):
            batch_num = i + 1
            batch_id = batch.get("batchId")
            frappe.log_error(f"Processing batch {batch_num}/{total_batches}: {batch_id}", "Floriday Batch Processing")
            
            # Create supply line directly (no customer offer attempt)
            result = create_single_supply_line(BASE_URL, API_KEY, ACCESS_TOKEN, batch)
            results.append(result)
            
            if result.get('status') == 'success':
                frappe.log_error(f"Batch {batch_num} supply line success: {result.get('supply_line_id')}", "Floriday Supply Line Result")
            else:
                frappe.log_error(f"Batch {batch_num} supply line failed: {result.get('message')}", "Floriday Supply Line Result")
            
            frappe.db.commit()
            import time
            time.sleep(1)  # Small delay between API calls
        
        frappe.log_error(f"Completed processing {len(results)} supply lines", "Floriday Supply Line Creation Complete")
        return results
        
    except Exception as e:
        error_msg = f"Error in create_supply_lines_only: {str(e)}"
        frappe.log_error(error_msg, "Floriday Supply Line Creation Error")
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
        
        frappe.log_error(f"Creating supply line for batch {batch_id}", "Floriday Single Supply Line")
        
        if available_pieces <= 0:
            error_msg = f"Batch {batch_id} has no available pieces"
            frappe.log_error(error_msg, "Floriday Single Supply Line")
            return {"status": "failed", "message": error_msg, "batch_id": batch_id}

        if not warehouse_id:
            error_msg = f"Batch {batch_id} has no warehouseId"
            frappe.log_error(error_msg, "Floriday Single Supply Line")
            return {"status": "failed", "message": error_msg, "batch_id": batch_id}

        # Get price from ERPNext Item based on trade_item_id
        offer_price = get_item_price_from_erpnext(trade_item_id)
        if not offer_price:
            error_msg = f"No price found in ERPNext for trade item {trade_item_id}"
            frappe.log_error(error_msg, "Floriday Supply Line Pricing")
            return {"status": "failed", "message": error_msg, "batch_id": batch_id}
            
        frappe.log_error(f"Using ERPNext price: {SUPPLY_LINE_CURRENCY} {offer_price} for batch {batch_id}", "Floriday Supply Line Pricing")
        
        now = datetime.now(timezone.utc)
        order_end = now + timedelta(days=7)
        
        # Get packing configuration from batch or use default
        packing_config = batch.get("packingConfiguration", get_default_packing_config())
        
        # Create supply line payload with floating point value (no cents conversion)
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
        
        frappe.log_error(f"Supply line payload for batch {batch_id}: {json.dumps(supply_line_payload, indent=2)}", "Floriday Supply Line Payload")
        
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        base_url_clean = BASE_URL.rstrip('/')
        supply_line_endpoint = f"{base_url_clean}/supply-lines"
        
        frappe.log_error(f"Making POST request to: {supply_line_endpoint}", "Floriday Supply Line API")
        
        response = requests.post(
            supply_line_endpoint,
            json=supply_line_payload,
            headers=headers,
            timeout=30
        )
        
        frappe.log_error(f"Supply line response status: {response.status_code}", "Floriday Supply Line Response")
        frappe.log_error(f"Supply line response text: {response.text}", "Floriday Supply Line Response")

        # Handle 200/201 success responses
        if response.status_code in (200, 201):
            supply_line_id = supply_line_payload["supplyLineId"]
            
            # For empty responses, assume success
            if not response.text.strip():
                frappe.log_error(f"Empty response - SUPPLY LINE CREATED: {supply_line_id}", "Floriday Supply Line Empty Success")
            else:
                try:
                    response_data = response.json()
                    supply_line_id = response_data.get("supplyLineId", supply_line_id)
                    frappe.log_error(f"Response received - SUPPLY LINE CREATED: {supply_line_id}", "Floriday Supply Line Success")
                except json.JSONDecodeError:
                    frappe.log_error(f"Non-JSON response - SUPPLY LINE CREATED: {supply_line_id}", "Floriday Supply Line Text Success")
            
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
            error_msg = f"Supply line creation failed: {response.status_code} - {response.text}"
            frappe.log_error(error_msg, "Floriday Supply Line Error")
            return {"status": "failed", "message": error_msg, "batch_id": batch_id}

    except requests.exceptions.RequestException as e:
        error_msg = f"Request exception in supply line: {str(e)}"
        frappe.log_error(error_msg, "Floriday Supply Line Request Exception")
        return {"status": "error", "message": str(e), "batch_id": batch_id}
    except Exception as e:
        error_msg = f"Unexpected error in supply line: {str(e)}"
        frappe.log_error(error_msg, "Floriday Supply Line Exception")
        return {"status": "error", "message": str(e), "batch_id": batch_id}

def get_item_price_from_erpnext(trade_item_id):
    """
    Get item price from ERPNext based on trade_item_id using the ITEM_MAPPING
    """
    try:
        frappe.log_error(f"Looking up price for Floriday trade_item_id: {trade_item_id}", "Floriday Price Lookup")
        
        # Get dynamic item mapping
        ITEM_MAPPING = get_item_mapping()
        
        # Reverse lookup: find ERPNext item code from Floriday trade_item_id
        erpnext_item_code = None
        for erp_code, floriday_id in ITEM_MAPPING.items():
            if floriday_id == trade_item_id:
                erpnext_item_code = erp_code
                break
        
        if not erpnext_item_code:
            frappe.log_error(f"No ERPNext item mapping found for Floriday trade_item_id: {trade_item_id}", "Floriday Price Lookup")
            return get_fallback_price(trade_item_id)
        
        frappe.log_error(f"Found ERPNext item: {erpnext_item_code} for Floriday trade_item_id: {trade_item_id}", "Floriday Price Lookup")
        
        # 1. Try to get price from Item Price list first
        price_list_price = get_price_from_price_list(erpnext_item_code)
        if price_list_price:
            frappe.log_error(f"Using price list price: {SUPPLY_LINE_CURRENCY} {price_list_price} for {erpnext_item_code}", "Floriday Price Lookup")
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
                price = float(item_details[0].selling_rate)
                frappe.log_error(f"Using selling_rate: {SUPPLY_LINE_CURRENCY} {price} for {erpnext_item_code}", "Floriday Price Lookup")
                return price
            
            # Try valuation_rate from Item master
            if item_details[0].valuation_rate:
                price = float(item_details[0].valuation_rate)
                frappe.log_error(f"Using valuation_rate: {SUPPLY_LINE_CURRENCY} {price} for {erpnext_item_code}", "Floriday Price Lookup")
                return price
        
        # 3. Fallback pricing
        fallback_price = get_fallback_price(trade_item_id)
        if fallback_price:
            frappe.log_error(f"Using fallback price: {SUPPLY_LINE_CURRENCY} {fallback_price} for {erpnext_item_code}", "Floriday Price Lookup")
            return fallback_price
        
        frappe.log_error(f"No price found for item: {erpnext_item_code}", "Floriday Price Lookup")
        return None
        
    except Exception as e:
        error_msg = f"Error in get_item_price_from_erpnext: {str(e)}"
        frappe.log_error(error_msg, "Floriday Price Lookup Error")
        
        # Final emergency fallback
        emergency_price = 0.40
        frappe.log_error(f"Using emergency default price: {SUPPLY_LINE_CURRENCY} {emergency_price} due to error", "Floriday Price Lookup")
        return emergency_price

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
        frappe.log_error(f"Error getting price from price list: {str(e)}", "Floriday Price List Lookup")
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
        frappe.log_error(f"Error in get_fallback_price: {str(e)}", "Floriday Fallback Price Error")
        return 0.40  # Absolute fallback

def get_your_floriday_batches(BASE_URL, API_KEY, ACCESS_TOKEN, SUPPLIER_ORG_ID):
    """
    Get ALL batches from Floriday (no date filtering in API call)
    """
    try:
        frappe.log_error(f"Getting ALL batches for supplier: {SUPPLIER_ORG_ID}", "Floriday Batch API")
        
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Accept": "application/json"
        }
        
        base_url_clean = BASE_URL.rstrip('/')
        endpoint = f"{base_url_clean}/batches?supplierOrganizationId={SUPPLIER_ORG_ID}"
        
        frappe.log_error(f"API Endpoint: {endpoint}", "Floriday Batch API")
        
        response = requests.get(endpoint, headers=headers, timeout=30)
        frappe.log_error(f"API Response Status: {response.status_code}", "Floriday Batch API Response")
        
        if response.status_code == 200:
            batches = response.json()
            if isinstance(batches, list):
                frappe.log_error(f"Retrieved {len(batches)} total batches", "Floriday Your Batches")
                return batches
            else:
                error_msg = f"Unexpected response format: {type(batches)}"
                frappe.log_error(error_msg, "Floriday Your Batches Error")
                return []
        else:
            error_msg = f"Failed to retrieve batches: {response.status_code} - {response.text}"
            frappe.log_error(error_msg, "Floriday Your Batches Error")
            return []

    except Exception as e:
        error_msg = f"Error retrieving batches: {str(e)}"
        frappe.log_error(error_msg, "Floriday Your Batches Error")
        return []

def get_default_packing_config():
    return {
        "piecesPerPackage": 200, 
        "vbnPackageCode": 884,
        "packagesPerLayer": 10,
        "layersPerLoadCarrier": 2,
        "loadCarrier": "AUCTION_TROLLEY",
        "transportHeightInCm": 100  # Make sure this is at least 1
    }

@frappe.whitelist()
def get_available_batches():
    """
    Returns batches with available pieces for CURRENT EAT DATE only
    """
    try:
        # Get current date in EAT timezone
        current_date = (datetime.now(timezone.utc) + EAT_OFFSET).strftime('%Y-%m-%d')
        frappe.log_error(f"Getting available batches for UI for EAT date: {current_date}", "Floriday UI Batch Fetch")
        
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
            frappe.log_error(f"No batches found for UI", "Floriday UI Batches")
            return {
                "status": "success",
                "batches": [],
                "total_batches": 0,
                "date_applied": current_date,
                "message": f"No batches found"
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
                "label": f"{batch.get('tradeItemName', 'Unknown Item')} - {available_quantity} pieces - Batch: {batch.get('batchId')}"
            })
        
        frappe.log_error(f"Returning {len(batch_options)} batches for UI for EAT {current_date}", "Floriday UI Batch Result")
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
        error_msg = f"Error in get_available_batches: {str(e)}"
        frappe.log_error(error_msg, "Floriday Available Batches Error")
        return {"status": "error", "message": str(e)} 