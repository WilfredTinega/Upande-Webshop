import frappe
import requests
from datetime import datetime, timedelta
import json
import math

@frappe.whitelist()
def post_all_items_to_biflorica():
    """
    Post all available items from the configured warehouse to Biflorica as offers
    Returns the payload of each offer to be created
    """
    try:
        # Get Biflorica Setting - using Single DocType approach
        if not frappe.db.exists("Biflorica Setting", "Biflorica Setting"):
            frappe.throw("Biflorica Setting not found. Please create the document first.")
        
        settings = frappe.get_doc("Biflorica Setting", "Biflorica Setting")
        frappe.log_error(f"Starting Biflorica sync for warehouse: {settings.warehouse}", "Biflorica Sync")

        # Validate required settings
        required_fields = {
            "warehouse": settings.warehouse,
            "access_token": settings.access_token,
            "base_url": settings.base_url,
            "platform": settings.platform,
            "farm": settings.farm
        }
        
        missing_fields = [field for field, value in required_fields.items() if not value]
        if missing_fields:
            frappe.throw(f"Missing required fields in Biflorica Setting: {', '.join(missing_fields)}")

        # First, validate the access token
        token_valid = validate_access_token(settings)
        if not token_valid:
            frappe.throw("Invalid or expired access token. Please check your Biflorica credentials.")

        # Get stock items from warehouse
        items_data = get_warehouse_stock_items(settings.warehouse)
        if not items_data:
            frappe.log_error(f"No stock found in warehouse: {settings.warehouse}", "Biflorica Sync")
            return {
                "success": True,
                "message": "No stock available to create offers.",
                "offers_payload": {"data": [], "countAll": "0"},
                "individual_offers": []
            }

        # LOG ALL AVAILABLE ITEMS TO ERROR LOG
        frappe.log_error(f"FOUND {len(items_data)} ITEMS IN WAREHOUSE:", "Biflorica Available Items")
        for i, item in enumerate(items_data, 1):
            item_price = get_item_price(item["item_code"])
            stem_length = get_stem_length_from_stock_entry(item["item_code"], settings.warehouse)
            frappe.log_error(f"Item {i}: {item.get('item_code')} - {item.get('item_name')} - Qty: {item.get('actual_qty')} - Price: {item_price} - Stem Length: {stem_length}", "Biflorica Available Items")
        
        frappe.log_error(f"Processing {len(items_data)} items with stock", "Biflorica Sync")

        # Prepare offers payload with CORRECT FORMAT and get individual offers
        offers_payload, individual_offers = prepare_offers_payload_with_details(items_data, settings)
        
        # LOG THE FINAL PAYLOAD BEING SENT
        frappe.log_error(f"FINAL PAYLOAD BEING SENT TO BIFLORICA:", "Biflorica Payload")
        frappe.log_error(json.dumps(offers_payload, indent=2), "Biflorica Payload")
        
        # Log individual offers for debugging
        frappe.log_error("INDIVIDUAL OFFERS PAYLOAD DETAILS:", "Biflorica Offers Details")
        for i, offer in enumerate(individual_offers, 1):
            frappe.log_error(f"Offer {i}: {json.dumps(offer, indent=2)}", "Biflorica Offers Details")
        
        # Post to Biflorica API
        api_response = post_to_biflorica_api(offers_payload, settings)
        
        # Return both API response and the payload details
        return {
            "api_response": api_response,
            "offers_payload": offers_payload,
            "individual_offers": individual_offers,
            "summary": {
                "total_items_processed": len(items_data),
                "offers_created": len(offers_payload["data"]),
                "items_skipped": len(items_data) - len(offers_payload["data"]),
                "skipped_items": [offer for offer in individual_offers if offer["status"] == "skipped"]
            }
        }

    except Exception as e:
        frappe.log_error(f"Biflorica sync error: {str(e)}", "Biflorica Sync Error")
        frappe.throw(f"Error posting items to Biflorica: {str(e)}")

def validate_access_token(settings):
    """
    Validate if the access token is still valid by making a test API call
    """
    try:
        # Use a simple endpoint to validate token - adjust endpoint as needed
        test_endpoint = f"{settings.base_url.rstrip('/')}/auth/verify"
        headers = {
            "Authorization": f"Bearer {settings.access_token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }
        
        # Try a simple GET request to validate token
        response = requests.get(
            test_endpoint,
            headers=headers,
            timeout=15
        )
        
        if response.status_code == 200:
            frappe.log_error("Access token validation successful", "Biflorica Auth")
            return True
        else:
            frappe.log_error(f"Token validation failed: {response.status_code} - {response.text}", "Biflorica Auth")
            return False
            
    except Exception as e:
        frappe.log_error(f"Token validation error: {str(e)}", "Biflorica Auth")
        return False

def get_stem_length_from_stock_entry(item_code, warehouse):
    """
    Fetch stem length from the most recent Stock Entry for the item in the specified warehouse
    """
    try:
        # Get the most recent Stock Entry that added this item to the warehouse
        stock_entries = frappe.get_all(
            "Stock Entry",
            fields=["name", "posting_date", "custom_stem_length"],
            filters={
                "docstatus": 1,  # Only submitted entries
                "purpose": "Material Receipt",  # Only material receipts
                "items": ["like", f'%{item_code}%']  # Entries containing this item
            },
            order_by="posting_date desc",
            limit=1
        )
        
        if stock_entries:
            stem_length = stock_entries[0].get("custom_stem_length")
            if stem_length:
                cleaned_length = validate_and_clean_stem_length(stem_length)
                if cleaned_length:
                    frappe.log_error(f"Found stem length for {item_code} in Stock Entry {stock_entries[0].name}: {stem_length} -> {cleaned_length}", "Biflorica Stem Length")
                    return cleaned_length
        
        # If no stem length found in Stock Entry, check Stock Entry Detail items
        stock_entry_details = frappe.get_all(
            "Stock Entry Detail",
            fields=["parent", "item_code", "custom_stem_length"],
            filters={
                "item_code": item_code,
                "docstatus": 1,
                "t_warehouse": warehouse  # Target warehouse (where stock was added)
            },
            order_by="creation desc",
            limit=1
        )
        
        if stock_entry_details:
            stem_length = stock_entry_details[0].get("custom_stem_length")
            if stem_length:
                cleaned_length = validate_and_clean_stem_length(stem_length)
                if cleaned_length:
                    frappe.log_error(f"Found stem length for {item_code} in Stock Entry Detail {stock_entry_details[0].parent}: {stem_length} -> {cleaned_length}", "Biflorica Stem Length")
                    return cleaned_length
        
        # If still no stem length found, try to get from item master as fallback
        item_stem_length = get_stem_length_from_item_master(item_code)
        if item_stem_length and item_stem_length != "50":
            frappe.log_error(f"Using stem length from Item master for {item_code}: {item_stem_length}", "Biflorica Stem Length")
            return item_stem_length
        
        frappe.log_error(f"No stem length found for {item_code} in Stock Entry or Item master, using default 50", "Biflorica Stem Length Warning")
        return "50"
        
    except Exception as e:
        frappe.log_error(f"Error fetching stem length for {item_code}: {str(e)}", "Biflorica Stem Length Error")
        return "50"

def get_stem_length_from_item_master(item_code):
    """
    Get stem length from Item master as fallback
    """
    try:
        item = frappe.get_doc("Item", item_code)
        stem_length_fields = [
            'stem_length', 'item_length', 'length', 
            'flower_size', 'stem_size', 'size'
        ]
        
        for field in stem_length_fields:
            stem_length = item.get(field)
            if stem_length:
                cleaned_length = validate_and_clean_stem_length(stem_length)
                if cleaned_length:
                    return cleaned_length
        return "50"
    except:
        return "50"

def validate_and_clean_stem_length(stem_length):
    """
    Validate and clean stem length value, rounding to nearest tens
    Returns the cleaned stem length rounded to nearest 10 or None if invalid
    """
    if not stem_length:
        return None
    
    # Convert to string and clean
    stem_str = str(stem_length).strip()
    
    # Remove common units and whitespace
    stem_str = stem_str.replace('cm', '').replace('CM', '').strip()
    
    # Check if it's a valid number
    try:
        # Try to convert to float first to handle decimals
        stem_float = float(stem_str)
        
        # Common stem length ranges for flowers (in cm)
        if 20 <= stem_float <= 120:  # Reasonable range for flower stems
            # Round to nearest tens
            rounded_length = round_to_nearest_tens(stem_float)
            frappe.log_error(f"Rounded stem length {stem_float} to nearest tens: {rounded_length}", "Biflorica Stem Length Rounding")
            return str(rounded_length)
        else:
            frappe.log_error(f"Stem length {stem_float} outside reasonable range (20-120cm)", "Biflorica Stem Length Validation")
            return None
    except ValueError:
        # Handle ranges like "60-70"
        if '-' in stem_str:
            parts = stem_str.split('-')
            try:
                num1 = float(parts[0].strip())
                num2 = float(parts[1].strip())
                if 20 <= num1 <= 120 and 20 <= num2 <= 120:
                    # Return the average rounded to nearest tens
                    average = (num1 + num2) / 2
                    rounded_length = round_to_nearest_tens(average)
                    frappe.log_error(f"Converted stem length range {stem_str} to average: {average} and rounded to: {rounded_length}", "Biflorica Stem Length Conversion")
                    return str(rounded_length)
            except:
                pass
        
        # Try to extract first number from the string
        import re
        numbers = re.findall(r'\d+', stem_str)
        if numbers:
            try:
                first_num = float(numbers[0])
                if 20 <= first_num <= 120:
                    rounded_length = round_to_nearest_tens(first_num)
                    frappe.log_error(f"Extracted stem length {first_num} from text: {stem_str} and rounded to: {rounded_length}", "Biflorica Stem Length Extraction")
                    return str(rounded_length)
            except:
                pass
    
    return None

def round_to_nearest_tens(number):
    """
    Round a number to the nearest tens
    Examples:
    72 → 70
    75 → 80
    78 → 80
    62 → 60
    """
    return int(round(number / 10) * 10)

def get_warehouse_stock_items(warehouse):
    """
    Get all items with stock in the specified warehouse
    """
    bins = frappe.get_all(
        "Bin",
        fields=["item_code", "actual_qty"],
        filters={"warehouse": warehouse, "actual_qty": [">", 0]}
    )
    
    if not bins:
        return []
    
    # Get item details for all items with stock
    item_codes = [bin["item_code"] for bin in bins]
    
    # Define fields to fetch from Item doctype
    item_fields = [
        "item_code", "item_name", "item_group", "variant_of", 
        "packing", "box_type", "color", "image", "size", 
        "characteristics", "stem_length", "item_length", "length",
        "flower_type", "flower_variety", "flower_size", "stem_size",
        "biflorica_type", "biflorica_variety"
    ]
    
    # Filter to only existing fields
    existing_fields = [f.fieldname for f in frappe.get_meta("Item").fields]
    fetch_fields = [field for field in item_fields if field in existing_fields]
    
    items = frappe.get_all("Item", fields=fetch_fields, filters={"item_code": ["in", item_codes]})
    
    # Combine item details with stock quantities
    items_with_stock = []
    for item in items:
        bin_info = next((bin for bin in bins if bin["item_code"] == item["item_code"]), None)
        if bin_info:
            item["actual_qty"] = bin_info["actual_qty"]
            items_with_stock.append(item)
    
    return items_with_stock

def get_item_price(item_code, price_list="Standard Selling"):
    """
    Get selling price for an item with better debugging
    """
    try:
        price = frappe.get_value(
            "Item Price", 
            {"item_code": item_code, "price_list": price_list}, 
            "price_list_rate"
        )
        
        if price is None:
            # Check if there are any prices for this item
            all_prices = frappe.get_all(
                "Item Price",
                fields=["price_list", "price_list_rate"],
                filters={"item_code": item_code}
            )
            
            if all_prices:
                frappe.log_error(f"Item {item_code} has prices but not in {price_list}: {all_prices}", "Biflorica Price Debug")
                # Use the first available price as fallback
                price = all_prices[0].get("price_list_rate")
            else:
                frappe.log_error(f"No prices found for item {item_code} in any price list", "Biflorica Price Debug")
        
        return float(price or 0)
        
    except Exception as e:
        frappe.log_error(f"Error getting price for {item_code}: {str(e)}", "Biflorica Price Error")
        return 0

def get_biflorica_flower_type(item):
    """
    Get Biflorica-compatible flower type - HARDCODED as "Rose"
    """
    # HARDCODED to always return "Rose"
    return "Rose"

def get_biflorica_flower_variety(item, flower_type):
    """
    Get Biflorica-compatible flower variety
    """
    # First check for custom Biflorica variety mapping
    if item.get("biflorica_variety"):
        return item.get("biflorica_variety")
    
    # Try to get variety from various fields
    potential_varieties = [
        item.get("flower_variety"),
        item.get("variant_of"),
        item.get("item_name")
    ]
    
    for potential_variety in potential_varieties:
        if potential_variety:
            clean_variety = str(potential_variety).strip()
            
            # Common variety cleaning - remove type prefixes
            clean_variety = clean_variety.replace(flower_type, "").strip()
            clean_variety = clean_variety.replace("Rose", "").strip()
            
            # Remove common prefixes/suffixes
            for prefix in ["Variety", "Type", "Flower", "Stem"]:
                clean_variety = clean_variety.replace(prefix, "").strip()
            
            if clean_variety:
                return clean_variety[:50]  # Limit length
    
    # If no variety found, use a default based on type
    default_varieties = {
        "Rose": "Standard"
    }
    
    return default_varieties.get(flower_type, "Standard")

def prepare_offers_payload_with_details(items_data, settings):
    """
    Prepare the offers payload and return both the main payload and individual offer details
    """
    offer_duration_days = getattr(settings, 'offer_duration_days', 1)  # Default to 1 day
    
    offer_data = []
    individual_offers_details = []
    
    for item in items_data:
        quantity = item.get("actual_qty", 0)
        price_per_stem = get_item_price(item["item_code"])
        
        # Skip items with zero price with better debugging
        if price_per_stem <= 0:
            frappe.log_error(f"Skipping item {item['item_code']} with zero price. Check Item Price records.", "Biflorica Sync")
            individual_offers_details.append({
                "item_code": item["item_code"],
                "item_name": item.get("item_name"),
                "status": "skipped",
                "reason": "Zero price - no valid price found in Item Price",
                "payload": None,
                "debug_info": {
                    "quantity": quantity,
                    "price_per_stem": price_per_stem,
                    "suggestion": "Check if Item Price exists for this item in Standard Selling price list"
                }
            })
            continue
        
        # Skip items with zero quantity
        if quantity <= 0:
            frappe.log_error(f"Skipping item {item['item_code']} with zero quantity", "Biflorica Sync")
            individual_offers_details.append({
                "item_code": item["item_code"],
                "item_name": item.get("item_name"),
                "status": "skipped",
                "reason": "Zero quantity",
                "payload": None
            })
            continue
        
        # Calculate sizesStems (this seems to be stems per size, using packing as default)
        sizes_stems = 300  # HARDCODED to 300
        
        # Get ACTUAL stem length from Stock Entry (already rounded to nearest tens)
        stem_length = get_stem_length_from_stock_entry(item["item_code"], settings.warehouse)
        
        # Get Biflorica-compatible flower type and variety
        flower_type = get_biflorica_flower_type(item)  # This will always return "Rose"
        flower_variety = get_biflorica_flower_variety(item, flower_type)
        
        # Prepare characteristics array
        characteristics = get_flower_characteristics(item)
        
        # Prepare picture URL
        picture_url = get_picture_url(item)
        
        frappe.log_error(f"Processing item: {item['item_code']} - Biflorica Type: {flower_type} - Biflorica Variety: {flower_variety} - Rounded Stem Length: {stem_length} - Price: {price_per_stem} - Packing: 300 - BoxType: HB", "Biflorica Item Mapping")
        
        # Prepare offer object in EXACT API format - ALL VALUES AS STRINGS
        offer = {
            "dateStart": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
            "dateEnd": (datetime.now() + timedelta(days=offer_duration_days)).strftime("%Y-%m-%d %H:%M:%S"),
            "platform": settings.platform,
            "farm": settings.farm,
            "type": flower_type,  # This will always be "Rose"
            "variety": flower_variety,
            "color": item.get("color", "") or "",
            "pictureURL": picture_url,
            "size": stem_length,  # Using the ACTUAL stem length from Stock Entry (rounded to nearest tens)
            "pricePerStem": str(round(float(price_per_stem), 2)),
            "sizesStems": str(sizes_stems),  # HARDCODED to 300
            "price": str(round(float(price_per_stem * sizes_stems), 2)),  # Price for the pack (price_per_stem * 300)
            "packing": str(sizes_stems),  # HARDCODED to 300
            "quantity": str(float(quantity)),
            "boxType": "HB",  # HARDCODED to "HB"
            "characteristics": characteristics
        }
        
        # Remove any empty fields that might cause issues
        offer = {k: v for k, v in offer.items() if v is not None}
        
        # Add to main payload
        offer_data.append(offer)
        
        # Add to individual offers details with additional info
        individual_offer_detail = {
            "item_code": item["item_code"],
            "item_name": item.get("item_name"),
            "status": "ready_to_post",
            "reason": "Successfully mapped",
            "payload": offer,
            "source_data": {
                "original_quantity": quantity,
                "original_price_per_stem": price_per_stem,
                "stem_length_source": "Stock Entry",  # Now coming from Stock Entry
                "mapped_flower_type": flower_type,  # This will always be "Rose"
                "mapped_variety": flower_variety,
                "mapped_stem_length": stem_length,  # Cleaned and validated stem length from Stock Entry (rounded to nearest tens)
                "mapped_packing": 300,
                "mapped_box_type": "HB"
            }
        }
        individual_offers_details.append(individual_offer_detail)
    
    main_payload = {
        "data": offer_data,
        "countAll": str(len(offer_data))  # Ensure this is string as in original payload
    }
    
    return main_payload, individual_offers_details

def get_flower_characteristics(item):
    """
    Extract flower characteristics from item data
    """
    characteristics = []
    
    # Check if characteristics field exists and has data
    item_characteristics = item.get("characteristics")
    if item_characteristics:
        # If it's a string, try to parse it
        if isinstance(item_characteristics, str):
            try:
                # Try to parse as JSON
                char_list = json.loads(item_characteristics)
                if isinstance(char_list, list):
                    characteristics.extend(char_list)
            except:
                # If not JSON, split by comma or use as single value
                if ',' in item_characteristics:
                    characteristics.extend([c.strip() for c in item_characteristics.split(',')])
                else:
                    characteristics.append(item_characteristics.strip())
        elif isinstance(item_characteristics, list):
            characteristics.extend(item_characteristics)
    
    # Add additional characteristics based on item properties
    if item.get("color"):
        characteristics.append(f"{item['color']} color")
    
    # Ensure all characteristics are strings
    characteristics = [str(c) for c in characteristics if c]
    
    return characteristics

def get_picture_url(item):
    """
    Get picture URL from item image field
    """
    image_field = item.get("image")
    if image_field:
        # If it's a full URL, return as is
        if image_field.startswith(('http://', 'https://')):
            return image_field
        # Otherwise, construct the URL
        else:
            try:
                site_url = frappe.utils.get_url()
                return f"{site_url}{image_field}"
            except:
                return ""
    return ""

def post_to_biflorica_api(offers_payload, settings):
    """
    Post offers payload to Biflorica API with improved error handling
    """
    endpoint_url = f"{settings.base_url.rstrip('/')}/offers"
    
    headers = {
        "Authorization": f"Bearer {settings.access_token}",
        "Content-Type": "application/json",
        "accept": "application/json"
    }
    
    frappe.log_error(f"Posting {len(offers_payload['data'])} offers to: {endpoint_url}", "Biflorica Sync")
    
    try:
        response = requests.post(
            endpoint_url, 
            json=offers_payload, 
            headers=headers,
            timeout=30
        )
        
        # LOG THE API RESPONSE
        frappe.log_error(f"API RESPONSE STATUS: {response.status_code}", "Biflorica API Response")
        frappe.log_error(f"API RESPONSE BODY: {response.text}", "Biflorica API Response")
        
        if response.status_code in [200, 201]:
            # Check if response indicates validation errors
            if "not_validate" in response.text or "Not parsed" in response.text:
                error_msg = f"Biflorica validation failed: {response.text}"
                frappe.log_error(error_msg, "Biflorica Validation Error")
                
                # Parse the specific validation errors
                validation_errors = []
                try:
                    errors = json.loads(response.text)
                    for i, error_item in enumerate(errors):
                        if "errors" in error_item:
                            validation_errors.append({
                                "offer_index": i,
                                "errors": error_item['errors']
                            })
                            frappe.log_error(f"Item {i+1} errors: {error_item['errors']}", "Biflorica Validation Details")
                except:
                    pass
                
                return {
                    "success": False,
                    "message": "Biflorica validation failed. Check error logs for details.",
                    "validation_errors": validation_errors,
                    "api_response": response.text,
                    "status_code": response.status_code
                }
            else:
                frappe.log_error(f"Successfully posted {len(offers_payload['data'])} offers to Biflorica", "Biflorica Sync")
                return {
                    "success": True,
                    "message": f"Successfully posted {len(offers_payload['data'])} offers to Biflorica",
                    "offers_count": len(offers_payload['data']),
                    "api_response": response.text,
                    "status_code": response.status_code
                }
        else:
            error_msg = f"API Error {response.status_code}: {response.text}"
            frappe.log_error(error_msg, "Biflorica Sync")
            return {
                "success": False,
                "message": error_msg,
                "status_code": response.status_code,
                "api_response": response.text
            }
            
    except requests.exceptions.RequestException as e:
        error_msg = f"Request failed: {str(e)}"
        frappe.log_error(error_msg, "Biflorica Sync")
        return {
            "success": False,
            "message": error_msg,
            "status_code": None,
            "api_response": None
        }