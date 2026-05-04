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
    Post one batch per (item, stem_length) row from `get_floriday_stock` against
    the Floriday warehouse (Online Available for Sale). Each batch carries the
    stem-length-specific tradeItemId and the SLE-aggregated numberOfPieces.

    Replaces the old Bin-driven flow which collapsed all stem lengths into one
    qty against a single tradeItemId — that overstated availability and lost
    the per-grade dimension.
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

    from upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings import get_floriday_stock

    stock_rows = get_floriday_stock(SOURCE_WAREHOUSE)
    if not stock_rows:
        frappe.log_error(
            f"No graded stock with Floriday mappings in {SOURCE_WAREHOUSE}",
            "Floriday Batch Creation",
        )
        return {"message": "No stock to create batches."}

    results = []

    BATCH_MULTIPLE = 200

    for row in stock_rows:
        item_code = row.get("item_code")
        stem_length = row.get("stem_length") or ""
        trade_item_id = row.get("trade_item_id")
        raw_qty = int(row.get("qty") or 0)

        if not trade_item_id:
            frappe.log_error(
                f"No trade_item_id for {item_code} {stem_length}",
                "Floriday Batch Creation - No Mapping",
            )
            results.append({
                "item_code": item_code,
                "stem_length": stem_length,
                "status": "no_mapping",
            })
            continue

        # Floriday batches must be multiples of 200; rows below 200 are skipped.
        qty = (raw_qty // BATCH_MULTIPLE) * BATCH_MULTIPLE
        if qty < BATCH_MULTIPLE:
            results.append({
                "item_code": item_code,
                "stem_length": stem_length,
                "status": "skipped_below_minimum",
                "available_qty": raw_qty,
            })
            continue
        if qty <= 0:
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

            label = f"{item_code}{f' ({stem_length})' if stem_length else ''}"
            if response.status_code in (200, 201):
                success_message = (
                    f"SUCCESS: Batch created for {label} "
                    f"(Batch ID: {batch_id}, Quantity: {qty}, Status: {response.status_code})\n"
                    f"Payload: {json.dumps(payload, indent=2)}"
                )
                frappe.log_error(success_message, "Floriday Batch Creation - Success")

                results.append({
                    "item_code": item_code,
                    "stem_length": stem_length,
                    "status": "success",
                    "batch_id": batch_id,
                    "quantity": qty,
                    "status_code": response.status_code,
                })
            else:
                resp_text = response.text
                resp_json = None
                try:
                    resp_json = response.json()
                except Exception:
                    resp_json = None

                error_message = (
                    f"FAILED: Batch creation for {label} "
                    f"(Status: {response.status_code}, Error: {str(resp_json or resp_text)[:500]})\n"
                    f"Payload: {json.dumps(payload, indent=2)}"
                )
                frappe.log_error(error_message, "Floriday Batch Creation - Failed")

                results.append({
                    "item_code": item_code,
                    "stem_length": stem_length,
                    "status": "failed",
                    "status_code": response.status_code,
                    "response": resp_json or resp_text,
                    "batch_id": batch_id,
                })

        except Exception as e:
            label = f"{item_code}{f' ({stem_length})' if stem_length else ''}"
            exception_message = (
                f"ERROR: Exception occurred for {label}: {str(e)}\n"
                f"Payload: {json.dumps(payload, indent=2)}"
            )
            frappe.log_error(exception_message, "Floriday Batch Creation - Exception")

            results.append({
                "item_code": item_code,
                "stem_length": stem_length,
                "status": "error",
                "error": str(e),
                "batch_id": batch_id,
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