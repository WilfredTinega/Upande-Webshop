import frappe
import requests
import uuid
import random
from datetime import datetime, timezone
from typing import Any, Dict
import json

@frappe.whitelist()
def create_batches_on_floriday():
    """
    Sends all bins from the warehouse with stock to Floriday as batches.
    Payload aligned to Floriday API expectations.
    """

    settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
    if not settings_list:
        frappe.throw("Floriday Settings not configured")

    settings = frappe.get_doc("Floriday Settings", settings_list[0].name)

    API_KEY = settings.api_key
    BASE_URL = settings.base_url
    WAREHOUSE_ID = settings.warehouse_id
    SUPPLIER_ORG_ID = settings.organization_supplier_id
    ACCESS_TOKEN = settings.access_token

    # Use the warehouse field from Floriday Settings
    SOURCE_WAREHOUSE = settings.warehouse

    if not SOURCE_WAREHOUSE:
        frappe.throw("Warehouse not configured in Floriday Settings")

    # Fetch item mappings from Floriday Item Mapping doctype
    mappings = frappe.get_all(
        "Floriday Item Mapping",
        fields=["item_code", "trade_item_id"]
    )
    
    # Create mapping dictionary from doctype records
    ITEM_MAPPING = {}
    for mapping in mappings:
        ITEM_MAPPING[mapping.item_code] = mapping.trade_item_id

    if not ITEM_MAPPING:
        frappe.throw("No item mappings found in Floriday Item Mapping doctype")

    bins = frappe.get_all(
        "Bin",
        fields=["item_code", "actual_qty"],
        filters={"warehouse": SOURCE_WAREHOUSE, "actual_qty": [">", 0]}
    )

    if not bins:
        frappe.log_error("No products in the warehouse with stock", "Floriday Batch Creation")
        return {"message": "No stock to create batches."}

    results = []

    for b in bins:
        item_code = b.item_code
        qty = int(b.actual_qty)
        trade_item_id = ITEM_MAPPING.get(item_code)

        if not trade_item_id:
            frappe.log_error(f"No mapping for ERPNext item {item_code}", "Floriday Batch Creation - No Mapping")
            results.append({"item_code": item_code, "status": "no_mapping"})
            continue

        batch_id = str(uuid.uuid4())
        batch_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # payload
        batch_payload = {
            "batchDate": batch_date,
            "batchId": batch_id,
            "tradeItemId": trade_item_id,
            "supplierOrganizationId": SUPPLIER_ORG_ID,
            "numberOfPieces": qty,
            "initialNumberOfPieces": qty,
            "packingConfiguration": {
                "piecesPerPackage": 200,
                "package": {
                    "vbnPackageCode": 884,
                    "customPackageId": None
                },
                "loadCarrier": "AUCTION_TROLLEY",
                "layersPerLoadCarrier": 2,
                "packagesPerLayer": 10
            },
            "warehouseId": WAREHOUSE_ID,
            "imageUrl": None,
            "batchReference": None,
            "customReference": None,
            "transitStatus": "UNKNOWN"
        }

        def clean_payload(obj: Any) -> Any:
            if isinstance(obj, dict):
                cleaned: Dict[str, Any] = {}
                for k, v in obj.items():
                    if v is None:
                        continue
                    if k == "vbnPackageCode":
                        try:
                            cleaned[k] = str(v)
                        except Exception:
                            continue
                        continue
                    cleaned_val = clean_payload(v)
                    if cleaned_val is None:
                        continue
                    if cleaned_val == {} or cleaned_val == []:
                        continue
                    cleaned[k] = cleaned_val
                return cleaned
            elif isinstance(obj, list):
                lst = [clean_payload(i) for i in obj]
                return [i for i in lst if i is not None]
            else:
                return obj

        payload = clean_payload(batch_payload)

        for k in ("batchReference", "customReference", "imageUrl"):
            if k not in payload:
                payload[k] = None

        try:
            pkg = payload.get("packingConfiguration", {}).get("package")
            if pkg is not None and "customPackageId" not in pkg:
                payload.setdefault("packingConfiguration", {}).setdefault("package", {})["customPackageId"] = None
        except Exception:
            pass

        try:
            response = requests.post(
                f"{BASE_URL}batches",
                json=payload,
                headers={
                    "Authorization": f"Bearer {ACCESS_TOKEN}",
                    "X-Api-Key": API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                timeout=30
            )

            if response.status_code in (200, 201):
                # Log successful batch creation with payload
                success_message = (
                    f"SUCCESS: Batch created for item {item_code} "
                    f"(Batch ID: {batch_id}, Quantity: {qty}, Status: {response.status_code})\n"
                    f"Payload: {json.dumps(payload, indent=2)}"
                )
                frappe.log_error(success_message, "Floriday Batch Creation - Success")
                
                results.append({
                    "item_code": item_code, 
                    "status": "success", 
                    "batch_id": batch_id,
                    "quantity": qty,
                    "status_code": response.status_code
                })
            else:
                resp_text = response.text
                resp_json = None
                try:
                    resp_json = response.json()
                except Exception:
                    resp_json = None

                # Log failed batch creation with payload and error details
                error_message = (
                    f"FAILED: Batch creation for item {item_code} "
                    f"(Status: {response.status_code}, Error: {str(resp_json or resp_text)[:500]})\n"
                    f"Payload: {json.dumps(payload, indent=2)}"
                )
                frappe.log_error(error_message, "Floriday Batch Creation - Failed")

                results.append({
                    "item_code": item_code,
                    "status": "failed",
                    "status_code": response.status_code,
                    "response": resp_json or resp_text,
                    "batch_id": batch_id
                })

        except Exception as e:
            # Log exception with payload
            exception_message = (
                f"ERROR: Exception occurred for item {item_code}: {str(e)}\n"
                f"Payload: {json.dumps(payload, indent=2)}"
            )
            frappe.log_error(exception_message, "Floriday Batch Creation - Exception")
            
            results.append({
                "item_code": item_code, 
                "status": "error", 
                "error": str(e),
                "batch_id": batch_id
            })

    # Log summary of batch creation results
    success_count = len([r for r in results if r.get("status") == "success"])
    failed_count = len([r for r in results if r.get("status") == "failed"])
    error_count = len([r for r in results if r.get("status") == "error"])
    no_mapping_count = len([r for r in results if r.get("status") == "no_mapping"])
    
    summary_message = (
        f"BATCH CREATION SUMMARY: "
        f"Success: {success_count}, "
        f"Failed: {failed_count}, "
        f"Errors: {error_count}, "
        f"No Mapping: {no_mapping_count}, "
        f"Total Processed: {len(results)}"
    )
    frappe.log_error(summary_message, "Floriday Batch Creation - Summary")

    return results