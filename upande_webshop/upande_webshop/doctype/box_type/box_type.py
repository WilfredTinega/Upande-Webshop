# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document


class BoxType(Document):
	def on_update(self):
		frappe.cache().delete_key("pack_rate_cache")

	def on_trash(self):
		frappe.cache().delete_key("pack_rate_cache")


def _stems_per_bunch_from_uom(uom_name):
	"""Parse stems per bunch from a UOM name like 'Bunch (10)' -> 10.

	Mirrors the cart's authoritative logic in shopping_cart.cart so the product
	page and the Sales Order/Quotation agree on bunch size.
	"""
	if uom_name:
		m = re.search(r"\((\d+)\)", uom_name)
		if m:
			return int(m.group(1))
	return 1


@frappe.whitelist()
def get_item_uoms(item_code=None):
	"""Return the global list of Bunch UOMs ('Bunch (N)') with parsed bunch sizes.

	The dropdown is the same for every variant — bunch packing is a global set,
	not per-item. Each entry: {uom, bunch_size}, where bunch_size is the 'N' in
	the UOM name (matching the cart's _stems_per_bunch_from_uom). The smallest
	bunch is the default selection.

	item_code is accepted but unused (kept for call-site compatibility).
	"""
	rows = frappe.get_all(
		"UOM",
		filters={"name": ["like", "Bunch (%"], "enabled": 1},
		fields=["name"],
	)
	uoms = [
		{"uom": r["name"], "bunch_size": _stems_per_bunch_from_uom(r["name"])}
		for r in rows
	]
	uoms.sort(key=lambda u: u["bunch_size"])

	default_uom = uoms[0]["uom"] if uoms else None
	return {"uoms": uoms, "default_uom": default_uom}


@frappe.whitelist()
def get_item_bunch_size(item_code):
	"""Return bunch size and sales UOM for an item, derived from its UOMs.

	Bunch size is parsed from the sales_uom name ('Bunch (10)' -> 10), matching
	the cart's _stems_per_bunch_from_uom. Falls back to size 1 / stock_uom.
	"""
	if not item_code:
		return {"bunch_size": 1, "sales_uom": None}

	sales_uom, stock_uom = frappe.db.get_value(
		"Item", item_code, ["sales_uom", "stock_uom"]
	) or (None, None)

	uom = sales_uom or stock_uom
	return {
		"bunch_size": _stems_per_bunch_from_uom(uom),
		"sales_uom": uom,
	}


@frappe.whitelist()
def get_pack_rate(box_name, length_cm):
	"""Return pack rate for a box type and stem length."""
	if not box_name or not length_cm:
		return {"pack_rate": None}
	
	pack_rate = frappe.db.get_value(
		"Box Type Pack Rate",
		{"box_type": box_name, "stem_length_cm": length_cm},
		"pack_rate",
		as_dict=True
	)
	
	return {"pack_rate": pack_rate.get("pack_rate") if pack_rate else None}


@frappe.whitelist()
def get_box_types():
	"""Return list of all Box Types with name and box_type_name."""
	box_types = frappe.get_all(
		"Box Type",
		fields=["name", "box_type_name"],
		order_by="name"
	)
	return box_types or []
