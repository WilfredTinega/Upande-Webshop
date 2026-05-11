

import frappe


DOCTYPE = "Biflorica Setting"

# (fieldname, default) — only applied if the field is currently empty.
DEFAULTS = [
	("offer_event_frequency",   "Daily"),
	("offer_enabled",           0),
	("deals_event_frequency",   "Daily"),
	("deals_enabled",           0),
	("deals_limit",             100),
	("predeal_event_frequency", "Daily"),
	("predeal_enabled",         0),
	("predeal_limit",           100),
	("at_event_frequency",      "Daily"),
	("at_enabled",              0),
]


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	if not frappe.db.get_value("DocType", DOCTYPE, "issingle"):
		# Should not happen — log and bail rather than corrupt non-Single data.
		print(f"[{DOCTYPE}] is not Single; skipping defaults backfill")
		return

	meta = frappe.get_meta(DOCTYPE)
	field_names = {df.fieldname for df in meta.fields}

	applied = []
	for fieldname, default in DEFAULTS:
		if fieldname not in field_names:
			continue
		current = frappe.db.get_single_value(DOCTYPE, fieldname)
		if current in (None, ""):
			frappe.db.set_single_value(DOCTYPE, fieldname, default)
			applied.append(fieldname)

	# Default token_url from base_url if it's set and token_url isn't.
	if "token_url" in field_names:
		token_url = frappe.db.get_single_value(DOCTYPE, "token_url")
		if not token_url:
			base_url = frappe.db.get_single_value(DOCTYPE, "base_url")
			if base_url:
				frappe.db.set_single_value(DOCTYPE, "token_url", base_url.rstrip("/") + "/auth/token")
				applied.append("token_url")

	if applied:
		print(f"[{DOCTYPE}] set defaults for: {', '.join(applied)}")

	frappe.clear_document_cache(DOCTYPE, DOCTYPE)

	# Create/refresh the Scheduled Job Type rows that back the four flows.
	try:
		doc = frappe.get_doc(DOCTYPE)
		doc._sync_scheduled_jobs(force=True)
	except Exception as e:
		# Don't fail the migration if the controller import or job sync chokes —
		# the defaults are already persisted and the user can resync from the UI.
		print(f"[{DOCTYPE}] scheduled-job sync skipped: {e}")

	frappe.db.commit()
