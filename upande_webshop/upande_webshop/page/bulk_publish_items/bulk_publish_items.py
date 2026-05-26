import frappe
from frappe import _
from frappe.utils import cint


def _check_permission():
	if not frappe.has_permission("Website Item", "create"):
		frappe.throw(_("Not permitted to create Website Items"), frappe.PermissionError)


@frappe.whitelist()
def get_items(item_group=None, brand=None, search=None, hide_published=1, start=0, page_length=50):
	"""Return Items matching filters, flagged with whether a Website Item already exists."""
	_check_permission()

	start = cint(start)
	page_length = min(cint(page_length) or 50, 200)
	hide_published = cint(hide_published)

	conditions = ["i.disabled = 0", "i.has_variants = 0"]
	values = {}

	if item_group:
		conditions.append("i.item_group = %(item_group)s")
		values["item_group"] = item_group
	if brand:
		conditions.append("i.brand = %(brand)s")
		values["brand"] = brand
	if search:
		conditions.append("(i.item_code LIKE %(search)s OR i.item_name LIKE %(search)s)")
		values["search"] = f"%{search}%"
	if hide_published:
		conditions.append("wi.name IS NULL")

	where_clause = " AND ".join(conditions)

	total = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM `tabItem` i
		LEFT JOIN `tabWebsite Item` wi ON wi.item_code = i.item_code
		WHERE {where_clause}
		""",
		values,
	)[0][0]

	values["start"] = start
	values["page_length"] = page_length

	rows = frappe.db.sql(
		f"""
		SELECT
			i.name AS item_code,
			i.item_name,
			i.item_group,
			i.brand,
			i.image,
			CASE WHEN wi.name IS NOT NULL THEN 1 ELSE 0 END AS already_published
		FROM `tabItem` i
		LEFT JOIN `tabWebsite Item` wi ON wi.item_code = i.item_code
		WHERE {where_clause}
		ORDER BY i.item_name ASC
		LIMIT %(start)s, %(page_length)s
		""",
		values,
		as_dict=True,
	)

	return {"items": rows, "total": total}


@frappe.whitelist()
def publish_items(item_codes):
	"""Enqueue bulk publish for the given Item codes. Returns immediately."""
	_check_permission()

	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)
	item_codes = [c for c in (item_codes or []) if c]
	if not item_codes:
		frappe.throw(_("No items selected"))

	frappe.enqueue(
		"upande_webshop.upande_webshop.page.bulk_publish_items.bulk_publish_items._publish_worker",
		queue="long",
		timeout=1500,
		item_codes=item_codes,
		user=frappe.session.user,
	)
	return {"queued": len(item_codes)}


def _publish_worker(item_codes, user):
	"""Background worker: create Website Items and set published=1."""
	from upande_webshop.upande_webshop.doctype.website_item.website_item import (
		make_website_item,
	)

	total = len(item_codes)
	succeeded = 0
	skipped = 0
	failed = 0
	errors = []

	for index, item_code in enumerate(item_codes, start=1):
		try:
			if frappe.db.exists("Website Item", {"item_code": item_code}):
				skipped += 1
			else:
				item_doc = frappe.get_doc("Item", item_code)
				web_item = make_website_item(item_doc.as_dict(), save=False)
				web_item.published = 1
				web_item.flags.ignore_permissions = True
				web_item.save()
				succeeded += 1
		except Exception as exc:
			failed += 1
			if len(errors) < 20:
				errors.append(f"{item_code}: {exc}")
			frappe.log_error(
				title=f"Bulk publish failed for {item_code}",
				message=frappe.get_traceback(),
			)

		if index % 10 == 0 or index == total:
			frappe.db.commit()
			progress = int((index / total) * 100)
			frappe.publish_realtime(
				"webshop_bulk_publish_progress",
				{
					"progress": progress,
					"message": _("Publishing {0} of {1}...").format(index, total),
				},
				user=user,
				after_commit=True,
			)

	frappe.publish_realtime(
		"webshop_bulk_publish_done",
		{
			"succeeded": succeeded,
			"skipped": skipped,
			"failed": failed,
			"total": total,
			"errors": errors,
		},
		user=user,
		after_commit=True,
	)
