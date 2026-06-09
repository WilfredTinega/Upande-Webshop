"""Shelf-based stock source.

When Webshop Settings → "Use Shelf Stock?" is enabled, storefront availability is
read from the kaitet `Shelf`/`Shelf Item` tables (physical stems sitting on
receiving cold-store shelves) instead of from `Stem Length Bin`.

Shelf rows model plain items only: `Shelf Item.variety` is the Item code,
`stem_length` is the Stem Length name (e.g. "52cm"), `stem_qty` is the count.
There is no variant/template concept on the shelf — every distinct length is a
plain item row, mirroring how `Stem Length Bin` is keyed.

Shelf qty is NOT filtered by the Webshop Settings warehouse set: the warehouses
table is hidden when shelf mode is on, and shelf rows carry their own
(receiving cold store) warehouse. We sum every Shelf Item row for the item.
"""

import frappe
from frappe.utils import flt


def use_shelf_stock():
	"""True when the storefront should read availability from Shelf, not Bin.

	Guarded by the existence of the `Shelf Item` doctype so sites without
	upande_kaitet (which owns Shelf) never trip on a missing table even if the
	flag is somehow set.
	"""
	return shelf_stock_enabled("Webshop Settings")


def shelf_stock_enabled(settings_doctype):
	"""True when `settings_doctype` (a Single) has use_shelf_stock on and Shelf exists.

	Lets non-webshop consumers (Biflorica Setting, Floriday Settings) opt into the
	same shelf source via their own flag, reusing the get_shelf_qty* helpers below.
	Guarded by the `Shelf Item` doctype so sites without upande_kaitet are safe.
	"""
	if not frappe.get_cached_value(settings_doctype, settings_doctype, "use_shelf_stock"):
		return False
	return bool(frappe.db.exists("DocType", "Shelf Item"))


def get_shelf_qty(item_code, stem_length=None):
	"""Total stems on shelves for an item, optionally scoped to one stem length."""
	filters = {"variety": item_code, "parenttype": "Shelf"}
	if stem_length:
		filters["stem_length"] = stem_length
	rows = frappe.db.get_all("Shelf Item", filters=filters, fields=["stem_qty"])
	return sum(flt(r.stem_qty) for r in rows)


def get_shelf_qty_by_length(item_code):
	"""Return {stem_length_name: total_stems} for one item across all shelves."""
	rows = frappe.db.get_all(
		"Shelf Item",
		filters={"variety": item_code, "parenttype": "Shelf"},
		fields=["stem_length", "stem_qty"],
	)
	qty_by_sl = {}
	for r in rows:
		if not r.stem_length:
			continue
		qty_by_sl[r.stem_length] = qty_by_sl.get(r.stem_length, 0.0) + flt(r.stem_qty)
	return qty_by_sl


def get_shelf_qty_for_items(item_codes):
	"""Return {item_code: total_stems} for many items in one query (listing use)."""
	if not item_codes:
		return {}
	rows = frappe.db.get_all(
		"Shelf Item",
		filters={"variety": ("in", list(item_codes)), "parenttype": "Shelf"},
		fields=["variety", "stem_qty"],
	)
	qty_by_code = {}
	for r in rows:
		qty_by_code[r.variety] = qty_by_code.get(r.variety, 0.0) + flt(r.stem_qty)
	return qty_by_code
