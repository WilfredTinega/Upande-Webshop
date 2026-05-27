import frappe

from upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices import (
	ensure_per_length_item_prices,
)


def execute(doc, method=None):
	"""For non-variant rose / David Austin items, ensure one Item Price row
	exists per master Stem Length on the configured selling price list. Rates
	default to 0; editors fill them in afterward via the Item Price list.
	"""
	if getattr(doc, "has_variants", 0) or getattr(doc, "variant_of", None):
		return
	if getattr(doc, "disabled", 0):
		return
	try:
		ensure_per_length_item_prices(doc.item_code)
	except Exception as e:
		frappe.log_error(
			f"ensure_per_length_item_prices hook failed for {doc.item_code}: {e}",
			"Webshop Per-Length Item Price Hook",
		)
