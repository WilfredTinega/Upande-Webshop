import frappe
import requests
import uuid
import json
from datetime import datetime, timezone, timedelta

@frappe.whitelist()
def create_customer_offer_from_supply_line(supply_line_id, customer_organization_id=None):
    """Create a customer offer using existing supply line ID"""
    try:
        frappe.log_error(f"Starting customer offer creation for supply line: {supply_line_id}", "Floriday Customer Offer")
        
        # Get Floriday settings
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            error_msg = "Floriday Settings not configured"
            frappe.log_error(error_msg, "Floriday Settings Error")
            return {"status": "failed", "message": error_msg}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
        API_KEY = settings.api_key
        BASE_URL = settings.base_url
        ACCESS_TOKEN = settings.access_token

        # Get the specific supply line
        supply_line = get_single_supply_line(BASE_URL, API_KEY, ACCESS_TOKEN, supply_line_id)
        if not supply_line:
            error_msg = f"Supply line {supply_line_id} not found"
            frappe.log_error(error_msg, "Floriday Customer Offer")
            return {"status": "failed", "message": error_msg}

        frappe.log_error(f"Found supply line: {supply_line_id}", "Floriday Customer Offer")

        # Get batch information for this supply line
        batch_id = supply_line.get("batchId")
        if not batch_id:
            error_msg = f"No batch ID found in supply line {supply_line_id}"
            frappe.log_error(error_msg, "Floriday Customer Offer")
            return {"status": "failed", "message": error_msg}

        batch = get_single_batch(BASE_URL, API_KEY, ACCESS_TOKEN, batch_id)
        if not batch:
            error_msg = f"Batch {batch_id} not found for supply line {supply_line_id}"
            frappe.log_error(error_msg, "Floriday Customer Offer")
            return {"status": "failed", "message": error_msg}

        frappe.log_error(f"Found batch: {batch_id}", "Floriday Customer Offer")

        # Create customer offer
        result = create_customer_offer_api(
            BASE_URL, 
            API_KEY, 
            ACCESS_TOKEN, 
            supply_line, 
            batch, 
            customer_organization_id
        )

        if result.get('status') == 'success':
            frappe.log_error(f"✓ SUCCESS: Created customer offer for supply line {supply_line_id}", "Floriday Customer Offer Result")
        else:
            frappe.log_error(f"✗ FAILED: Customer offer creation: {result.get('message')}", "Floriday Customer Offer Result")

        return result

    except Exception as e:
        error_msg = f"Unexpected error in create_customer_offer_from_supply_line: {str(e)}"
        frappe.log_error(error_msg, "Floriday Customer Offer Error")
        return {"status": "error", "message": error_msg}

def create_customer_offer_api(BASE_URL, API_KEY, ACCESS_TOKEN, supply_line, batch, customer_organization_id=None):
    """Create customer offer using Swagger documentation specification"""
    try:
        supply_line_id = supply_line.get("supplyLineId")
        batch_id = supply_line.get("batchId")
        trade_item_id = batch.get("tradeItemId")
        warehouse_id = batch.get("warehouseId")
        
        # Get number of pieces from supply line
        number_of_pieces = supply_line.get("assignedNumberOfPieces", supply_line.get("numberOfPieces", 1000))
        
        # Get price from supply line or generate default
        price_per_piece = supply_line.get("pricePerPiece", {})
        if price_per_piece and price_per_piece.get('value'):
            price_value = price_per_piece.get('value')
        else:
            # Convert EUR to cents (assuming price is in EUR)
            default_price = 1.50 * 100  # €1.50 in cents
            price_value = int(default_price)

        frappe.log_error(f"Creating customer offer for supply line {supply_line_id}", "Floriday Customer Offer API")

        # Get current time in UTC
        now = datetime.now(timezone.utc)
        
        # Set order period (next 7 days)
        order_end = now + timedelta(days=7)
        
        # Set delivery period (7-14 days from now)
        delivery_start = now + timedelta(days=7)
        delivery_end = now + timedelta(days=14)

        # Extract packing configuration from supply line or use defaults
        packing_config = supply_line.get("packingConfigurations", [{}])[0] if supply_line.get("packingConfigurations") else {}
        if not packing_config:
            # Use default packing configuration
            packing_config = {
                "piecesPerPackage": 9999,
                "vbnPackageCode": 999,
                "customPackageId": str(uuid.uuid4()),
                "packagesPerLayer": 9999,
                "layersPerLoadCarrier": 9999,
                "loadCarrier": "NONE",
                "photoUrl": "string"
            }

        # Prepare customer organization IDs
        allowed_customer_orgs = []
        if customer_organization_id:
            allowed_customer_orgs = [customer_organization_id]

        # Create customer offer payload according to Swagger documentation
        customer_offer_payload = {
            "customerOfferId": str(uuid.uuid4()),
            "allowedCustomerOrganizationIds": allowed_customer_orgs,
            "title": f"Offer from supply line {supply_line_id}",
            "description": f"Customer offer created from supply line {supply_line_id}",
            "imageId": str(uuid.uuid4()),
            "agreementReference": {
                "code": "string",
                "description": "string"
            },
            "customerOfferLines": [
                {
                    "customerOfferLineId": str(uuid.uuid4()),
                    "tradeItemId": trade_item_id,
                    "despatchWarehouseId": warehouse_id,
                    "numberOfPieces": number_of_pieces,
                    "pricePerPiece": {
                        "currency": "EUR",
                        "value": price_value
                    },
                    "volumePrices": [
                        {
                            "unit": "LAYER",
                            "pricePerPiece": 9999999
                        }
                    ],
                    "salesUnit": "PACKAGE",
                    "orderPeriod": {
                        "startDateTime": now.isoformat(),
                        "endDateTime": order_end.isoformat()
                    },
                    "deliveryPeriod": {
                        "startDateTime": delivery_start.isoformat(),
                        "endDateTime": delivery_end.isoformat()
                    },
                    "usesCatalogAvailability": True,
                    "batchId": batch_id,
                    "packingConfiguration": packing_config,
                    "includedServices": [
                        "DELIVERY"
                    ]
                }
            ]
        }

        frappe.log_error(f"Customer offer payload: {json.dumps(customer_offer_payload, indent=2)}", "Floriday Customer Offer Payload")

        # Prepare headers according to Swagger
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "text/plain"
        }

        base_url_clean = BASE_URL.rstrip('/')
        
        # Use the EXACT endpoint from Swagger documentation - WITHOUT /v2
        customer_offer_endpoint = f"{base_url_clean}/suppliers-api-2025v1/customer-offers"
        
        frappe.log_error(f"Making POST request to: {customer_offer_endpoint}", "Floriday Customer Offer API")
        frappe.log_error(f"Headers: {headers}", "Floriday Customer Offer API")

        response = requests.post(
            customer_offer_endpoint,
            json=customer_offer_payload,
            headers=headers,
            timeout=30
        )
        
        frappe.log_error(f"Customer offer response status: {response.status_code}", "Floriday Customer Offer Response")
        frappe.log_error(f"Customer offer response headers: {dict(response.headers)}", "Floriday Customer Offer Response")
        frappe.log_error(f"Customer offer response text: {response.text}", "Floriday Customer Offer Response")

        # Handle response according to Swagger documentation
        if response.status_code == 200:
            success_message = f"Customer offer created successfully for supply line {supply_line_id}"
            frappe.log_error(success_message, "Floriday Customer Offer Success")
            
            return {
                "status": "success",
                "message": success_message,
                "supply_line_id": supply_line_id,
                "batch_id": batch_id,
                "trade_item_id": trade_item_id,
                "customer_organization_ids": allowed_customer_orgs,
                "endpoint_used": customer_offer_endpoint,
                "response_data": response.text if response.text else "Empty response - check API for offer status"
            }
        else:
            error_msg = f"Customer offer creation failed: {response.status_code} - {response.text}"
            frappe.log_error(error_msg, "Floriday Customer Offer Error")
            
            # Detailed error analysis based on Swagger
            if response.status_code == 400:
                frappe.log_error("400 - Bad Request: Invalid request body", "Floriday Customer Offer Debug")
            elif response.status_code == 401:
                frappe.log_error("401 - Unauthorized: Invalid authentication", "Floriday Customer Offer Debug")
            elif response.status_code == 403:
                frappe.log_error("403 - Forbidden: Insufficient permissions", "Floriday Customer Offer Debug")
            elif response.status_code == 404:
                frappe.log_error("404 - Not Found: Endpoint not found", "Floriday Customer Offer Debug")
            elif response.status_code == 409:
                frappe.log_error("409 - Conflict: Customer offer ID already exists", "Floriday Customer Offer Debug")
            elif response.status_code == 415:
                frappe.log_error("415 - Unsupported Media Type: Wrong content type", "Floriday Customer Offer Debug")
            elif response.status_code == 500:
                frappe.log_error("500 - Internal Server Error: API server issue", "Floriday Customer Offer Debug")
            
            return {
                "status": "failed", 
                "message": error_msg, 
                "supply_line_id": supply_line_id,
                "batch_id": batch_id,
                "endpoint_used": customer_offer_endpoint
            }

    except requests.exceptions.RequestException as e:
        error_msg = f"Request exception in customer offer API: {str(e)}"
        frappe.log_error(error_msg, "Floriday Customer Offer Request Exception")
        return {"status": "error", "message": str(e)}
    except Exception as e:
        error_msg = f"Unexpected error in customer offer API: {str(e)}"
        frappe.log_error(error_msg, "Floriday Customer Offer Exception")
        return {"status": "error", "message": str(e)}

def get_single_supply_line(BASE_URL, API_KEY, ACCESS_TOKEN, supply_line_id):
    """Get a single supply line by ID"""
    try:
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Accept": "application/json"
        }

        base_url_clean = BASE_URL.rstrip('/')
        # Try different endpoint variations for supply lines
        endpoint_variations = [
            f"{base_url_clean}/suppliers-api-2025v1/supply-lines/{supply_line_id}",
            f"{base_url_clean}/supply-lines/{supply_line_id}"
        ]
        
        for endpoint in endpoint_variations:
            frappe.log_error(f"Trying supply line endpoint: {endpoint}", "Floriday Supply Line")
            response = requests.get(endpoint, headers=headers, timeout=30)
            
            if response.status_code == 200:
                frappe.log_error(f"✓ SUCCESS: Found supply line using {endpoint}", "Floriday Supply Line")
                return response.json()
            else:
                frappe.log_error(f"✗ FAILED: {endpoint} - {response.status_code}", "Floriday Supply Line")
        
        frappe.log_error(f"All endpoints failed for supply line {supply_line_id}", "Floriday Supply Line Error")
        return None

    except Exception as e:
        error_msg = f"Error retrieving supply line {supply_line_id}: {str(e)}"
        frappe.log_error(error_msg, "Floriday Supply Line Error")
        return None

def get_single_batch(BASE_URL, API_KEY, ACCESS_TOKEN, batch_id):
    """Get a single batch by ID"""
    try:
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Accept": "application/json"
        }

        base_url_clean = BASE_URL.rstrip('/')
        # Try different endpoint variations for batches
        endpoint_variations = [
            f"{base_url_clean}/suppliers-api-2025v1/batches/{batch_id}",
            f"{base_url_clean}/batches/{batch_id}"
        ]
        
        for endpoint in endpoint_variations:
            frappe.log_error(f"Trying batch endpoint: {endpoint}", "Floriday Batch")
            response = requests.get(endpoint, headers=headers, timeout=30)
            
            if response.status_code == 200:
                frappe.log_error(f"✓ SUCCESS: Found batch using {endpoint}", "Floriday Batch")
                return response.json()
            else:
                frappe.log_error(f"✗ FAILED: {endpoint} - {response.status_code}", "Floriday Batch")
        
        frappe.log_error(f"All endpoints failed for batch {batch_id}", "Floriday Batch Error")
        return None

    except Exception as e:
        error_msg = f"Error retrieving batch {batch_id}: {str(e)}"
        frappe.log_error(error_msg, "Floriday Batch Error")
        return None

def get_existing_supply_lines(BASE_URL, API_KEY, ACCESS_TOKEN, limit=1000):
    """Get all existing supply lines from Floriday API"""
    try:
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Accept": "application/json"
        }

        base_url_clean = BASE_URL.rstrip('/')
        # Try different endpoint variations
        endpoint_variations = [
            f"{base_url_clean}/suppliers-api-2025v1/supply-lines?limitResult={limit}",
            f"{base_url_clean}/supply-lines?limitResult={limit}"
        ]
        
        for endpoint in endpoint_variations:
            frappe.log_error(f"Trying supply lines endpoint: {endpoint}", "Floriday Get Supply Lines")
            
            response = requests.get(endpoint, headers=headers, timeout=30)
            
            frappe.log_error(f"Supply lines response status: {response.status_code}", "Floriday Supply Lines Response")
            
            if response.status_code == 200:
                supply_lines = response.json()
                frappe.log_error(f"✓ SUCCESS: Retrieved {len(supply_lines)} supply lines from {endpoint}", "Floriday Supply Lines")
                return supply_lines
            else:
                frappe.log_error(f"✗ FAILED: {endpoint} - {response.status_code} - {response.text}", "Floriday Supply Lines Error")
        
        # If all endpoints failed
        error_msg = "All endpoint variations failed to retrieve supply lines"
        frappe.log_error(error_msg, "Floriday Supply Lines Error")
        return None

    except Exception as e:
        error_msg = f"Error retrieving supply lines: {str(e)}"
        frappe.log_error(error_msg, "Floriday Supply Lines Error")
        return None

# Additional function to create offers for multiple supply lines - LIMITED TO 5
@frappe.whitelist()
def create_customer_offers_for_all_supply_lines(customer_organization_id=None, limit=5):
    """Create customer offers for existing supply lines (limited to 5 for testing)"""
    try:
        frappe.log_error(f"Starting customer offers creation for supply lines (limit: {limit})", "Floriday Customer Offers Batch")
        
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            error_msg = "Floriday Settings not configured"
            frappe.log_error(error_msg, "Floriday Settings Error")
            return {"status": "failed", "message": error_msg}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
        API_KEY = settings.api_key
        BASE_URL = settings.base_url
        ACCESS_TOKEN = settings.access_token

        # Get all existing supply lines
        supply_lines = get_existing_supply_lines(BASE_URL, API_KEY, ACCESS_TOKEN)
        if not supply_lines:
            error_msg = "No existing supply lines found or failed to fetch supply lines"
            frappe.log_error(error_msg, "Floriday Customer Offers")
            return {"status": "failed", "message": error_msg}

        frappe.log_error(f"Found {len(supply_lines)} supply lines, processing first {limit}", "Floriday Customer Offers")

        results = []
        # Process only LIMITED number of supply lines (5 by default)
        for i, supply_line in enumerate(supply_lines[:limit]):
            supply_line_id = supply_line.get("supplyLineId")
            if not supply_line_id:
                frappe.log_error(f"Skipping supply line without ID at index {i}", "Floriday Customer Offers")
                continue
                
            frappe.log_error(f"Processing supply line {i+1}/{min(len(supply_lines), limit)}: {supply_line_id}", "Floriday Customer Offers")
            
            result = create_customer_offer_from_supply_line(supply_line_id, customer_organization_id)
            results.append(result)
            
            # Commit after each offer to ensure progress is saved
            frappe.db.commit()
            
            # Rate limiting - wait 1 second between requests
            import time
            time.sleep(1)

        successful_offers = [r for r in results if r.get('status') == 'success']
        failed_offers = [r for r in results if r.get('status') != 'success']
        
        summary_message = f"Created {len(successful_offers)} customer offers from {min(len(supply_lines), limit)} supply lines ({len(failed_offers)} failed)"
        frappe.log_error(f"✓ BATCH COMPLETE: {summary_message}", "Floriday Customer Offers Result")
        
        return {
            "status": "success",
            "message": summary_message,
            "successful_offers": successful_offers,
            "failed_offers": failed_offers,
            "total_processed": len(results),
            "limit_applied": limit,
            "total_supply_lines_available": len(supply_lines)
        }

    except Exception as e:
        error_msg = f"Unexpected error in create_customer_offers_for_all_supply_lines: {str(e)}"
        frappe.log_error(error_msg, "Floriday Customer Offers Error")
        return {"status": "error", "message": error_msg}

@frappe.whitelist()
def test_customer_offer_endpoint_connectivity():
    """Test if we can reach the customer offer endpoint"""
    try:
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            return {"status": "failed", "message": "Floriday Settings not configured"}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
        API_KEY = settings.api_key
        BASE_URL = settings.base_url
        ACCESS_TOKEN = settings.access_token

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Accept": "text/plain"
        }

        base_url_clean = BASE_URL.rstrip('/')
        # Updated endpoint without /v2
        test_endpoint = f"{base_url_clean}/suppliers-api-2025v1/customer-offers"
        
        frappe.log_error(f"Testing connectivity to: {test_endpoint}", "Floriday Connectivity Test")
        
        # Try a simple GET request to see if endpoint exists
        response = requests.get(test_endpoint, headers=headers, timeout=10)
        
        frappe.log_error(f"Connectivity test response: {response.status_code}", "Floriday Connectivity Test")
        frappe.log_error(f"Response headers: {dict(response.headers)}", "Floriday Connectivity Test")
        
        if response.status_code != 404:
            return {
                "status": "success", 
                "message": f"Endpoint exists with status: {response.status_code}",
                "response_preview": response.text[:200] if response.text else "No response body"
            }
        else:
            return {
                "status": "failed",
                "message": "Endpoint returned 404 - Route not found",
                "tested_endpoint": test_endpoint,
                "base_url_used": BASE_URL
            }
            
    except Exception as e:
        error_msg = f"Connectivity test failed: {str(e)}"
        frappe.log_error(error_msg, "Floriday Connectivity Test")
        return {"status": "error", "message": error_msg}

@frappe.whitelist()
def debug_supply_line_data(supply_line_id):
    """Debug function to check supply line and batch data"""
    try:
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            return {"status": "failed", "message": "Floriday Settings not configured"}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
        API_KEY = settings.api_key
        BASE_URL = settings.base_url
        ACCESS_TOKEN = settings.access_token

        # Get supply line data
        supply_line = get_single_supply_line(BASE_URL, API_KEY, ACCESS_TOKEN, supply_line_id)
        if not supply_line:
            return {"status": "failed", "message": f"Supply line {supply_line_id} not found"}

        # Get batch data
        batch_id = supply_line.get("batchId")
        batch = None
        if batch_id:
            batch = get_single_batch(BASE_URL, API_KEY, ACCESS_TOKEN, batch_id)

        return {
            "status": "success",
            "supply_line": supply_line,
            "batch": batch,
            "batch_id": batch_id,
            "has_batch_data": bool(batch),
            "supply_line_keys": list(supply_line.keys()) if supply_line else []
        }

    except Exception as e:
        error_msg = f"Debug failed: {str(e)}"
        frappe.log_error(error_msg, "Floriday Debug")
        return {"status": "error", "message": error_msg}

@frappe.whitelist()
def diagnose_404_error():
    """Diagnose the 404 error with customer offer creation"""
    try:
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            return {"status": "failed", "message": "Floriday Settings not configured"}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
        API_KEY = settings.api_key
        BASE_URL = settings.base_url
        ACCESS_TOKEN = settings.access_token

        # Test 1: Check base URL format
        base_url_clean = BASE_URL.rstrip('/')
        # Updated endpoint without /v2
        test_endpoint = f"{base_url_clean}/suppliers-api-2025v1/customer-offers"
        
        # Test 2: Check if we can access other endpoints
        test_supply_lines = get_existing_supply_lines(BASE_URL, API_KEY, ACCESS_TOKEN, limit=1)
        
        diagnosis = {
            "status": "success",
            "diagnosis": {
                "base_url": BASE_URL,
                "cleaned_base_url": base_url_clean,
                "customer_offer_endpoint": test_endpoint,
                "supply_lines_accessible": bool(test_supply_lines),
                "supply_lines_count": len(test_supply_lines) if test_supply_lines else 0,
                "api_key_exists": bool(API_KEY),
                "access_token_exists": bool(ACCESS_TOKEN),
                "possible_issues": [
                    "1. API permissions - user may not have permission to create customer offers",
                    "2. Endpoint version mismatch",
                    "3. Authentication token might be expired or invalid",
                    "4. Base URL might be incorrect for customer offers endpoint"
                ]
            }
        }
        
        return diagnosis

    except Exception as e:
        error_msg = f"Diagnosis failed: {str(e)}"
        frappe.log_error(error_msg, "Floriday Diagnosis")
        return {"status": "error", "message": error_msg}

@frappe.whitelist()
def verify_swagger_documentation():
    """Verify the Swagger documentation is accessible and check the exact endpoint"""
    try:
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            return {"status": "failed", "message": "Floriday Settings not configured"}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
        BASE_URL = settings.base_url

        base_url_clean = BASE_URL.rstrip('/')
        
        # Check if Swagger documentation is accessible
        swagger_url = f"{base_url_clean}/suppliers-api-2025v1/swagger/index.html"
        
        frappe.log_error(f"Checking Swagger documentation: {swagger_url}", "Floriday Swagger Check")
        
        response = requests.get(swagger_url, timeout=10)
        
        if response.status_code == 200:
            return {
                "status": "success",
                "message": "Swagger documentation is accessible",
                "swagger_url": swagger_url,
                "customer_offer_endpoint": f"{base_url_clean}/suppliers-api-2025v1/customer-offers",
                "expected_method": "POST",
                "expected_content_type": "application/json",
                "expected_accept": "text/plain"
            }
        else:
            return {
                "status": "failed",
                "message": f"Swagger documentation not accessible: {response.status_code}",
                "swagger_url": swagger_url
            }
            
    except Exception as e:
        error_msg = f"Swagger verification failed: {str(e)}"
        frappe.log_error(error_msg, "Floriday Swagger Check")
        return {"status": "error", "message": error_msg}

@frappe.whitelist()
def discover_correct_endpoint():
    """Comprehensive endpoint discovery to find the exact customer offer endpoint"""
    try:
        settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
        if not settings_list:
            return {"status": "failed", "message": "Floriday Settings not configured"}

        settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
        API_KEY = settings.api_key
        BASE_URL = settings.base_url
        ACCESS_TOKEN = settings.access_token

        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "X-Api-Key": API_KEY,
            "Accept": "text/plain"
        }

        base_url_clean = BASE_URL.rstrip('/')
        
        # Comprehensive list of endpoint variations to test
        endpoint_variations = [
            # Current attempt and variations
            f"{base_url_clean}/suppliers-api-2025v1/customer-offers",
            f"{base_url_clean}/suppliers-api-2025v1/customer-offers/v2",
            
            # Common API patterns
            f"{base_url_clean}/customer-offers",
            f"{base_url_clean}/customer-offers/v2",
            f"{base_url_clean}/offers", 
            f"{base_url_clean}/offers/v2",
            
            # API version patterns
            f"{base_url_clean}/api/v2/customer-offers",
            f"{base_url_clean}/api/v1/customer-offers",
            f"{base_url_clean}/api/customer-offers",
        ]

        results = []
        
        for endpoint in endpoint_variations:
            try:
                frappe.log_error(f"Testing endpoint: {endpoint}", "Floriday Endpoint Discovery")
                
                # Test with OPTIONS method first (more likely to work for discovery)
                response = requests.options(endpoint, headers=headers, timeout=10)
                
                result = {
                    "endpoint": endpoint,
                    "status_code": response.status_code,
                    "exists": response.status_code not in [404, 405],
                    "method": "OPTIONS",
                    "headers": dict(response.headers),
                    "response_preview": response.text[:200] if response.text else "No response"
                }
                
                # If OPTIONS doesn't work, try GET
                if response.status_code == 405:  # Method Not Allowed
                    get_response = requests.get(endpoint, headers=headers, timeout=10)
                    result = {
                        "endpoint": endpoint,
                        "status_code": get_response.status_code,
                        "exists": get_response.status_code != 404,
                        "method": "GET",
                        "headers": dict(get_response.headers),
                        "response_preview": get_response.text[:200] if get_response.text else "No response"
                    }
                
                results.append(result)
                frappe.log_error(f"Endpoint {endpoint}: Status {result['status_code']} (Method: {result['method']})", "Floriday Endpoint Discovery")
                
            except Exception as e:
                frappe.log_error(f"Error testing {endpoint}: {str(e)}", "Floriday Endpoint Discovery")
                results.append({
                    "endpoint": endpoint,
                    "status_code": "Error",
                    "exists": False,
                    "error": str(e)
                })

        # Find working endpoints
        working_endpoints = [r for r in results if r['exists']]
        
        return {
            "status": "success",
            "working_endpoints": working_endpoints,
            "all_tested_endpoints": results,
            "recommendation": f"Found {len(working_endpoints)} working endpoints. Try the first one: {working_endpoints[0]['endpoint'] if working_endpoints else 'None found'}"
        }

    except Exception as e:
        error_msg = f"Endpoint discovery failed: {str(e)}"
        frappe.log_error(error_msg, "Floriday Endpoint Discovery")
        return {"status": "error", "message": error_msg}