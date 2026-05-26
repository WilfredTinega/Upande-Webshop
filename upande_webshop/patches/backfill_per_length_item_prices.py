import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	"""Add Item Price.custom_length Custom Field and create one Item Price row per
	master Stem Length for every existing non-variant rose / David Austin item.

	Seeds new rows from any pre-existing flat Item Price on the same price list,
	so a single $0.24 entry becomes six $0.24 rows (one per length). After this,
	editors can adjust individual lengths through the Item Price list.
	"""
	if not frappe.db.exists("DocType", "Stem Length"):
		return
	if not frappe.db.exists("DocType", "Item Price"):
		return

	create_custom_fields(
		{
			"Item Price": [
				{
					"fieldname": "custom_length",
					"fieldtype": "Link",
					"label": "Stem Length",
					"options": "Stem Length",
					"insert_after": "item_name",
					"description": "Set for non-variant rose items priced per stem length. Variants leave this blank.",
				},
			],
		},
		ignore_validate=True,
	)

	frappe.db.commit()

	from upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices import (
		_ROSE_ITEM_GROUP_REGEXP,
		ensure_per_length_item_prices,
	)

	items = frappe.db.sql(
		"""
		SELECT name
		FROM tabItem
		WHERE disabled = 0
		  AND has_variants = 0
		  AND (variant_of IS NULL OR variant_of = '')
		  AND item_group REGEXP %s
		""",
		(_ROSE_ITEM_GROUP_REGEXP,),
		pluck="name",
	)

	created_total = 0
	for item_code in items:
		try:
			created_total += ensure_per_length_item_prices(item_code)
		except Exception as e:
			frappe.log_error(
				f"backfill_per_length_item_prices failed for {item_code}: {e}",
				"Webshop Per-Length Item Price Backfill",
			)

	frappe.db.commit()
	print(
		f"backfill_per_length_item_prices: processed {len(items)} items, "
		f"created {created_total} Item Price rows."
	)
