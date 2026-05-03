# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.integrations.utils import make_post_request
from frappe.model.document import Document

SCHEDULER_TASKS = [
	("at",         "upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.refresh_access_token",    "Floriday: Refresh Access Token"),
	("fi",         "upande_webshop.upande_webshop.doctype.floriday_items.floriday_items.sync_floriday_items",            "Floriday: Sync Items"),
	("batch",      "upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.run_create_batch",         "Floriday: Create Batches"),
	("supplyline", "upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.run_supplyline",           "Floriday: Create Supply Lines"),
	("so",         "upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.run_sales_order",          "Floriday: Sync Sales Orders"),
	("of",         "upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.run_order_fullfilment",    "Floriday: Order Fulfillment"),
]


class FloridaySettings(Document):
	def onload(self):
		"""Show last_run / next_run from each Scheduled Job Type when the form loads."""
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
			# Use db_set with update_modified=False so we don't churn modified timestamps
			# every form load. These are presentation-only fields.
			self.set(f"{prefix}_last_run", last_run)
			self.set(f"{prefix}_next_run", next_run)

	@frappe.whitelist()
	def update_access_token(self):
		return _refresh_access_token(self)

	@frappe.whitelist()
	def sales_order(self):
		from upande_webshop.upande_webshop.doctype.floriday_settings.floriday_sales_order import create_sales_orders_from_floriday
		return create_sales_orders_from_floriday()

	@frappe.whitelist()
	def create_batch(self):
		from upande_webshop.upande_webshop.doctype.floriday_settings.floriday_batch import create_batches_on_floriday
		return create_batches_on_floriday()

	@frappe.whitelist()
	def create_supplyine(self):
		from upande_webshop.upande_webshop.doctype.floriday_settings.floriday_supplyline import create_supply_lines_only_from_batches
		return create_supply_lines_only_from_batches()

	@frappe.whitelist()
	def order_fullfilment(self):
		from upande_webshop.upande_webshop.doctype.floriday_settings.floriday_order_fullfillment import order_fullment
		return order_fullment()

	def on_update(self):
		self._sync_scheduled_jobs()

	def _sync_scheduled_jobs(self, force=False):
		"""Mirror the user's frequency/cron/enabled choices into Scheduled Job Type rows.

		One Scheduled Job Type per task, keyed by `method`. Same pattern Frappe's
		Server Script uses (see core/doctype/server_script/server_script.py).

		Per-task short-circuit: if none of (frequency, cron, enabled) changed for a
		task on this save, skip it entirely. Saving Floriday Settings should never
		reset last_execution or perturb a job whose schedule wasn't touched.

		Pass force=True to upsert all tasks regardless (used by after_migrate and
		the manual resync helper, since migrate wipes the rows).
		"""
		for prefix, method, _label in SCHEDULER_TASKS:
			fields = (
				f"{prefix}_event_frequency",
				f"{prefix}_cron_format",
				f"{prefix}_enabled",
			)
			if not force and not any(self.has_value_changed(f) for f in fields):
				continue  # nothing changed for this task — leave its job alone

			self._upsert_scheduled_job(prefix, method)

	def _upsert_scheduled_job(self, prefix, method):
		frequency = (self.get(f"{prefix}_event_frequency") or "").strip()
		cron_format = (self.get(f"{prefix}_cron_format") or "").strip()
		enabled = bool(self.get(f"{prefix}_enabled"))

		# Stopped if disabled, no frequency, or Cron without a cron string
		stopped = 1 if (not enabled or not frequency) else 0
		if frequency == "Cron" and not cron_format:
			stopped = 1

		job_name = frappe.db.get_value("Scheduled Job Type", {"method": method})

		if not job_name:
			if stopped:
				# Don't create a row for a task that's been off and never scheduled
				return
			job = frappe.new_doc("Scheduled Job Type")
			job.method = method
			job.create_log = frequency not in ("All", "Cron")
			job.frequency = frequency
			job.cron_format = cron_format if frequency == "Cron" else ""
			job.stopped = 0
			job.insert(ignore_permissions=True)
			return

		# Existing row — only write fields that actually differ. Avoids touching
		# last_execution / modified when the schedule didn't really change.
		new_frequency = frequency or "Daily"  # placeholder for stopped jobs (required field)
		new_cron = cron_format if frequency == "Cron" else ""

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


def _get_settings_doc():
	if frappe.get_meta("Floriday Settings").issingle:
		return frappe.get_single("Floriday Settings")
	settings_list = frappe.get_all("Floriday Settings", fields=["name"], limit_page_length=1)
	if not settings_list:
		frappe.throw("Floriday Settings doc not found. Please create it first.")
	return frappe.get_doc("Floriday Settings", settings_list[0].name)


def _refresh_access_token(doc=None):
	try:
		settings = doc or _get_settings_doc()

		if not (settings.token_url and settings.client_id and settings.client_secret and settings.scope):
			frappe.throw("token_url, client_id, client_secret, and scope are required on Floriday Settings.")

		payload = {
			"grant_type": settings.grant_type or "client_credentials",
			"client_id": settings.client_id,
			"client_secret": settings.client_secret,
			"scope": settings.scope,
		}
		headers = {"Content-Type": "application/x-www-form-urlencoded"}

		response = make_post_request(settings.token_url, data=payload, headers=headers)

		if not (response and response.get("access_token")):
			frappe.throw(f"Token endpoint returned no access_token. Response: {response}")

		settings.access_token = response["access_token"]
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		return {"status": "success"}

	except Exception as e:
		frappe.log_error(message=str(e), title="Floriday Token Exception")
		raise


@frappe.whitelist()
def refresh_access_token():
	if not frappe.db.get_single_value("Floriday Settings", "at_enabled"):
		return {"skipped": True, "reason": "Update Access Token is disabled (at_enabled = 0)"}
	return _refresh_access_token()


@frappe.whitelist()
def run_sales_order():
	if not frappe.db.get_single_value("Floriday Settings", "so_enabled"):
		return {"skipped": True, "reason": "Sales Order is disabled (so_enabled = 0)"}
	from upande_webshop.upande_webshop.doctype.floriday_settings.floriday_sales_order import create_sales_orders_from_floriday
	return create_sales_orders_from_floriday()


@frappe.whitelist()
def run_create_batch():
	if not frappe.db.get_single_value("Floriday Settings", "batch_enabled"):
		return {"skipped": True, "reason": "Create Batch is disabled (batch_enabled = 0)"}
	from upande_webshop.upande_webshop.doctype.floriday_settings.floriday_batch import create_batches_on_floriday
	return create_batches_on_floriday()


@frappe.whitelist()
def run_supplyline():
	if not frappe.db.get_single_value("Floriday Settings", "supplyline_enabled"):
		return {"skipped": True, "reason": "Supplyline is disabled (supplyline_enabled = 0)"}
	from upande_webshop.upande_webshop.doctype.floriday_settings.floriday_supplyline import create_supply_lines_only_from_batches
	return create_supply_lines_only_from_batches()


@frappe.whitelist()
def run_order_fullfilment():
	if not frappe.db.get_single_value("Floriday Settings", "of_enabled"):
		return {"skipped": True, "reason": "Order Fullfilment is disabled (of_enabled = 0)"}
	from upande_webshop.upande_webshop.doctype.floriday_settings.floriday_order_fullfillment import order_fullment
	return order_fullment()


@frappe.whitelist()
def resync_scheduled_jobs():
	"""Re-upsert ALL Floriday-driven scheduled jobs from current settings.

	Wired into hooks.after_migrate because Frappe's sync_jobs deletes any
	Scheduled Job Type whose method isn't declared in scheduler_events.
	"""
	doc = _get_settings_doc()
	doc._sync_scheduled_jobs(force=True)
	frappe.db.commit()
	return {
		"jobs": frappe.get_all(
			"Scheduled Job Type",
			filters={"method": ["like", "%upande_webshop%"]},
			fields=["method", "frequency", "cron_format", "stopped"],
			order_by="method",
		)
	}


@frappe.whitelist()
def preview_scheduler_run_times():
	"""Diagnostic: show what the form will display in last_run/next_run for each task."""
	doc = _get_settings_doc()
	doc._populate_scheduler_run_times()
	out = {}
	for prefix, method, label in SCHEDULER_TASKS:
		out[label] = {
			"method": method,
			"last_run": doc.get(f"{prefix}_last_run"),
			"next_run": doc.get(f"{prefix}_next_run"),
		}
	return out


