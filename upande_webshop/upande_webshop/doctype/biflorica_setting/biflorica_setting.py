# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import json

import frappe
import requests
from frappe.model.document import Document

from upande_webshop.upande_webshop.doctype.biflorica_setting.biflorica_customer_offer import (
	get_biflorica_flower_variety,
	get_item_price,
	get_stem_length_from_stock_entry,
	get_warehouse_stock_items,
	post_all_items_to_biflorica,
)


SCHEDULER_TASKS = [
	("at",      "upande_webshop.upande_webshop.doctype.biflorica_setting.biflorica_setting.run_update_access_token", "Biflorica: Refresh Access Token"),
	("offer",   "upande_webshop.upande_webshop.doctype.biflorica_setting.biflorica_setting.run_post_offers",         "Biflorica: Post Offers"),
	("deals",   "upande_webshop.upande_webshop.doctype.biflorica_setting.biflorica_setting.run_get_deals",           "Biflorica: Sync Deals"),
	("predeal", "upande_webshop.upande_webshop.doctype.biflorica_setting.biflorica_setting.run_get_predeals",        "Biflorica: Sync Predeals"),
]


class BifloricaSetting(Document):
	def onload(self):
		self._populate_scheduler_run_times()

	def _populate_scheduler_run_times(self):
		for prefix, method, _label in SCHEDULER_TASKS:
			row = frappe.db.get_value(
				"Scheduled Job Type",
				{"method": method},
				["name", "last_execution"],
				as_dict=True,
			)
			last_run = row.last_execution if row else None
			next_run = None
			if row and row.name:
				try:
					job = frappe.get_cached_doc("Scheduled Job Type", row.name)
					if not job.stopped:
						next_run = job.get_next_execution()
				except Exception:
					next_run = None
			self.set(f"{prefix}_last_run", last_run)
			self.set(f"{prefix}_next_run", next_run)

	def on_update(self):
		self._sync_scheduled_jobs()

	def _sync_scheduled_jobs(self, force=False):
		for prefix, method, _label in SCHEDULER_TASKS:
			fields = (
				f"{prefix}_event_frequency",
				f"{prefix}_cron_format",
				f"{prefix}_enabled",
			)
			if not force and not any(self.has_value_changed(f) for f in fields):
				continue
			self._upsert_scheduled_job(prefix, method)

	def _upsert_scheduled_job(self, prefix, method):
		frequency = (self.get(f"{prefix}_event_frequency") or "").strip()
		cron_format = (self.get(f"{prefix}_cron_format") or "").strip()
		enabled = bool(self.get(f"{prefix}_enabled"))

		stopped = 1 if (not enabled or not frequency) else 0
		if frequency == "Cron" and not cron_format:
			stopped = 1

		effective_frequency = "Daily" if (frequency == "Cron" and not cron_format) else frequency

		job_name = frappe.db.get_value("Scheduled Job Type", {"method": method})

		if not job_name:
			if stopped:
				return
			job = frappe.new_doc("Scheduled Job Type")
			job.method = method
			job.create_log = effective_frequency not in ("All", "Cron")
			job.frequency = effective_frequency
			job.cron_format = cron_format if effective_frequency == "Cron" else ""
			job.stopped = 0
			job.insert(ignore_permissions=True)
			return

		new_frequency = effective_frequency or "Daily"
		new_cron = cron_format if effective_frequency == "Cron" else ""

		current = frappe.db.get_value(
			"Scheduled Job Type",
			job_name,
			["frequency", "cron_format", "stopped"],
			as_dict=True,
		)
		updates = {}
		if current.frequency != new_frequency:
			updates["frequency"] = new_frequency
		if (current.cron_format or "") != new_cron:
			updates["cron_format"] = new_cron
		if int(current.stopped or 0) != stopped:
			updates["stopped"] = stopped

		if updates:
			frappe.db.set_value("Scheduled Job Type", job_name, updates)


@frappe.whitelist()
def resync_scheduled_jobs():
	doc = _get_settings()
	doc._sync_scheduled_jobs(force=True)
	frappe.db.commit()
	return {
		"jobs": frappe.get_all(
			"Scheduled Job Type",
			filters={"method": ["like", "%biflorica_setting%"]},
			fields=["method", "frequency", "cron_format", "stopped"],
			order_by="method",
		)
	}


@frappe.whitelist()
def run_update_access_token():
	if not frappe.db.get_single_value("Biflorica Setting", "at_enabled"):
		return {"skipped": True, "reason": "Update Access Token disabled"}
	return update_access_token()


@frappe.whitelist()
def run_post_offers():
	if not frappe.db.get_single_value("Biflorica Setting", "offer_enabled"):
		return {"skipped": True, "reason": "Post Offers disabled"}
	return post_offers()


@frappe.whitelist()
def run_get_deals():
	if not frappe.db.get_single_value("Biflorica Setting", "deals_enabled"):
		return {"skipped": True, "reason": "Get Deals disabled"}
	return get_deals()


@frappe.whitelist()
def run_get_predeals():
	if not frappe.db.get_single_value("Biflorica Setting", "predeal_enabled"):
		return {"skipped": True, "reason": "Get Predeals disabled"}
	return get_predeals()


def _get_settings():
	settings_name = "Biflorica Setting"
	if not frappe.db.exists("Biflorica Setting", settings_name):
		frappe.throw("Biflorica Setting not found. Please configure it first.")
	return frappe.get_doc("Biflorica Setting", settings_name)


def _auth_headers(settings):
	if not settings.access_token:
		frappe.throw("Access token is missing. Click 'Update Access Token' first.")
	return {
		"Authorization": f"Bearer {settings.access_token}",
		"Content-Type": "application/json",
		"accept": "application/json",
	}


def _api_call(method, path, settings, payload=None, params=None):
	url = settings.base_url.rstrip("/") + path
	headers = _auth_headers(settings)

	try:
		http_response = requests.request(
			method=method,
			url=url,
			headers=headers,
			data=json.dumps(payload) if payload is not None else None,
			params=params,
			timeout=30,
		)
	except requests.exceptions.RequestException as e:
		frappe.log_error(f"{method} {url} request failed: {e}", "Biflorica API")
		return {"success": False, "message": str(e), "status_code": None, "data": None}

	body_preview = http_response.text[:500] if http_response.text else ""

	try:
		body = http_response.json() if http_response.text else None
	except ValueError:
		body = None

	if http_response.status_code not in (200, 201):
		frappe.log_error(
			f"{method} {url} -> {http_response.status_code}: {body_preview}",
			"Biflorica API",
		)
		return {
			"success": False,
			"message": f"API returned status {http_response.status_code}",
			"status_code": http_response.status_code,
			"data": body if body is not None else http_response.text,
		}

	return {
		"success": True,
		"message": "OK",
		"status_code": http_response.status_code,
		"data": body if body is not None else http_response.text,
	}


@frappe.whitelist()
def update_access_token():
	try:
		settings_name = "Biflorica Setting"
		settings = frappe.get_doc("Biflorica Setting", settings_name)

		base_url = settings.base_url or ""
		username = settings.username or ""
		password = settings.password or ""

		if not (base_url and username and password):
			frappe.log_error("Missing base_url, username, or password", "Biflorica Token Update")
			return {"success": False, "message": "Missing base_url, username, or password"}

		api_url = base_url.rstrip("/") + "/auth/token"
		headers = {
			"accept": "application/json",
			"Content-Type": "application/json"
		}
		payload = json.dumps({"username": username, "password": password})

		http_response = requests.post(api_url, headers=headers, data=payload, timeout=30)

		try:
			response = http_response.json()
		except ValueError:
			frappe.log_error(
				f"Non-JSON response ({http_response.status_code}): {http_response.text[:500]}",
				"Biflorica Token Update",
			)
			return {"success": False, "message": f"Non-JSON response from auth endpoint (status {http_response.status_code})"}

		if http_response.status_code not in (200, 201):
			frappe.log_error(
				f"Auth failed ({http_response.status_code}): {http_response.text[:500]}",
				"Biflorica Token Update",
			)
			return {"success": False, "message": f"Auth failed with status {http_response.status_code}"}

		token = ""
		if response:
			if response.get("model") and response["model"].get("token"):
				token = response["model"]["token"]
			elif response.get("token"):
				token = response["token"]

		if token != "":
			frappe.db.set_value("Biflorica Setting", settings_name, "access_token", token)
			frappe.db.commit()
			frappe.log_error("Access token updated", "Biflorica Token Update")
			return {"success": True, "message": "Access token updated successfully"}
		else:
			frappe.log_error("Token not found in API response", "Biflorica Token Update")
			return {"success": False, "message": "Token not found in API response"}

	except Exception as e:
		frappe.log_error(str(e), "Biflorica Token Update Error")
		return {"success": False, "message": str(e)}


@frappe.whitelist()
def refresh_stock():
	try:
		settings = _get_settings()
		if not settings.warehouse:
			return {"success": False, "message": "Warehouse not configured in Biflorica Setting"}

		items_data = get_warehouse_stock_items(settings.warehouse) or []

		settings.set("stock_items", [])
		for item in items_data:
			qty = item.get("actual_qty") or 0
			if qty <= 0:
				continue

			item_code = item.get("item_code")
			price = get_item_price(item_code)
			stem_length = get_stem_length_from_stock_entry(item_code, settings.warehouse)
			variety = get_biflorica_flower_variety(item, "Rose")
			uom = frappe.db.get_value("Item", item_code, "stock_uom")

			settings.append("stock_items", {
				"warehouse": settings.warehouse,
				"item_code": item_code,
				"item_name": item.get("item_name"),
				"variety": variety,
				"stem_length": stem_length,
				"qty": qty,
				"price_per_stem": price,
				"uom": uom,
			})

		settings.save(ignore_permissions=True)
		frappe.db.commit()

		return {
			"success": True,
			"message": f"Loaded {len(settings.stock_items)} items from {settings.warehouse}",
		}
	except Exception as e:
		frappe.log_error(str(e), "Biflorica Refresh Stock Error")
		return {"success": False, "message": str(e)}


@frappe.whitelist()
def post_offers():
	try:
		result = post_all_items_to_biflorica() or {}
		frappe.db.set_value("Biflorica Setting", "Biflorica Setting", "offer_last_run", frappe.utils.now_datetime())
		frappe.db.commit()

		api_response = result.get("api_response") or {}
		offers_payload = result.get("offers_payload") or {}
		posted_offers = offers_payload.get("data") or []

		raw_response = api_response.get("api_response")
		parsed_results = []
		if isinstance(raw_response, str):
			try:
				parsed_results = json.loads(raw_response)
			except ValueError:
				parsed_results = []
		elif isinstance(raw_response, list):
			parsed_results = raw_response

		success_varieties = []
		failed_varieties = []
		for idx, item_result in enumerate(parsed_results or []):
			if not isinstance(item_result, dict):
				continue
			variety = ""
			if idx < len(posted_offers):
				variety = posted_offers[idx].get("variety") or "(unknown)"
			if item_result.get("result") == "ok":
				success_varieties.append(variety)
			else:
				errors = item_result.get("errors") or {}
				reason_parts = []
				for field, msgs in errors.items():
					if isinstance(msgs, list):
						reason_parts.append(f"{field}: {', '.join(str(m) for m in msgs)}")
					else:
						reason_parts.append(f"{field}: {msgs}")
				failed_varieties.append({
					"variety": variety,
					"reason": "; ".join(reason_parts) or "rejected",
				})

		summary = result.get("summary") or {}
		summary["success_varieties"] = success_varieties
		summary["failed_varieties"] = failed_varieties
		summary["success_count"] = len(success_varieties)
		summary["failed_count"] = len(failed_varieties)

		api_succeeded = api_response.get("success", True)
		overall_success = bool(api_succeeded) and not failed_varieties

		if success_varieties and failed_varieties:
			message = f"Posted {len(success_varieties)}, failed {len(failed_varieties)}"
		elif success_varieties:
			message = f"Posted {len(success_varieties)} offer(s)"
		elif failed_varieties:
			message = f"All {len(failed_varieties)} offer(s) failed"
		else:
			message = api_response.get("message") or "No offers processed"

		return {
			"success": overall_success,
			"message": message,
			"summary": summary,
			"data": result,
		}
	except Exception as e:
		frappe.log_error(str(e), "Biflorica Post Offers Error")
		return {"success": False, "message": str(e)}


def _to_float(value):
	try:
		return float(value)
	except (TypeError, ValueError):
		return 0.0


@frappe.whitelist()
def get_offers():
	try:
		settings = _get_settings()
		result = _api_call("GET", "/offers", settings)
		if not result["success"]:
			return result

		body = result.get("data") or {}
		offers = []
		if isinstance(body, dict):
			offers = body.get("data") or []
		elif isinstance(body, list):
			offers = body

		doc = _get_settings()
		doc.set("live_offers", [])
		for offer in offers:
			if not isinstance(offer, dict):
				continue
			doc.append("live_offers", {
				"offer_id": str(offer.get("id") or ""),
				"type": offer.get("type") or "",
				"variety": offer.get("variety") or "",
				"color": offer.get("color") or "",
				"size": str(offer.get("size") or ""),
				"quantity": _to_float(offer.get("quantity")),
				"packing": str(offer.get("packing") or ""),
				"price_per_stem": _to_float(offer.get("pricePerStem")),
				"price": _to_float(offer.get("price")),
				"box_type": offer.get("boxType") or "",
				"platform": offer.get("platform") or "",
				"farm": offer.get("farm") or "",
				"date_start": offer.get("dateStart") or None,
				"date_end": offer.get("dateEnd") or None,
			})
		doc.offer_last_run = frappe.utils.now_datetime()
		doc.save(ignore_permissions=True)
		frappe.db.commit()

		result["message"] = f"Loaded {len(doc.live_offers)} live offers"
		return result
	except Exception as e:
		frappe.log_error(str(e), "Biflorica Get Offers Error")
		return {"success": False, "message": str(e)}


def _to_iso_z(value):
	if not value:
		return None
	dt = frappe.utils.get_datetime(value)
	return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_deal_params(settings, prefix):
	params = {}
	from_date = _to_iso_z(getattr(settings, f"{prefix}_from_date", None))
	to_date = _to_iso_z(getattr(settings, f"{prefix}_to_date", None))
	mutation_date = _to_iso_z(getattr(settings, f"{prefix}_mutation_date", None))
	limit = getattr(settings, f"{prefix}_limit", None)
	offset = getattr(settings, f"{prefix}_offset", None)

	if from_date:
		params["fromDate"] = from_date
	if to_date:
		params["toDate"] = to_date
	if mutation_date:
		params["mutationDate"] = mutation_date
	if limit:
		params["limit"] = int(limit)
	if offset:
		params["offset"] = int(offset)
	return params


@frappe.whitelist()
def get_deals():
	try:
		settings = _get_settings()
		params = _build_deal_params(settings, "deals")
		result = _api_call("GET", "/deals", settings, params=params)
		if result["success"]:
			frappe.db.set_value("Biflorica Setting", "Biflorica Setting", "deals_last_run", frappe.utils.now_datetime())
			frappe.db.commit()
		return result
	except Exception as e:
		frappe.log_error(str(e), "Biflorica Get Deals Error")
		return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_predeals():
	try:
		settings = _get_settings()
		params = _build_deal_params(settings, "predeal")
		result = _api_call("GET", "/deals/predeal", settings, params=params)
		if result["success"]:
			frappe.db.set_value("Biflorica Setting", "Biflorica Setting", "predeal_last_run", frappe.utils.now_datetime())
			frappe.db.commit()
		return result
	except Exception as e:
		frappe.log_error(str(e), "Biflorica Get Predeals Error")
		return {"success": False, "message": str(e)}


@frappe.whitelist()
def approve_deal(deal_id):
	try:
		if not deal_id:
			return {"success": False, "message": "Deal ID is required"}
		settings = _get_settings()
		result = _api_call("POST", "/deals/approve", settings, payload={"deal_id": deal_id})
		if result["success"]:
			frappe.db.set_value("Biflorica Setting", "Biflorica Setting", "deals_last_run", frappe.utils.now_datetime())
			frappe.db.commit()
		return result
	except Exception as e:
		frappe.log_error(str(e), "Biflorica Approve Deal Error")
		return {"success": False, "message": str(e)}
