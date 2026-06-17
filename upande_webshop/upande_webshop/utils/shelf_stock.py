"""Shelf-based stock source.

When Webshop Settings → "Use Shelf Stock?" is enabled, storefront availability is
read from the kaitet `Shelf`/`Shelf Item` tables (physical stems sitting on
receiving cold-store shelves) instead of from core `Bin`.

Shelf rows model plain items only: `Shelf Item.variety` is the Item code,
`stem_length` is the Stem Length name (e.g. "52cm"), `stem_qty` is the count.
There is no variant/template concept on the shelf — every distinct length is a
plain item row.

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


def get_shelf_warehouse(item_code, stem_length=None):
	"""Warehouse the shelf stock for an item sits in (the source warehouse).

	An item+length can sit on shelves in more than one (receiving cold store)
	warehouse; we return the one holding the most stems, scoped to `stem_length`
	when given. This is the value the kaitet allocation path uses as a Sales Order
	line's `custom_source_warehouse` (source of the SO-approval Material Transfer).
	Returns None when nothing is on a shelf for that item.
	"""
	filters = {"variety": item_code, "parenttype": "Shelf", "stem_qty": (">", 0)}
	if stem_length:
		filters["stem_length"] = stem_length
	rows = frappe.db.get_all(
		"Shelf Item", filters=filters, fields=["warehouse", "stem_qty"]
	)
	qty_by_wh = {}
	for r in rows:
		if not r.warehouse:
			continue
		qty_by_wh[r.warehouse] = qty_by_wh.get(r.warehouse, 0.0) + flt(r.stem_qty)
	if not qty_by_wh:
		return None
	return max(qty_by_wh, key=qty_by_wh.get)


# Source warehouses a Shopping Cart Sales Order line is allowed to use, in
# fallback-priority order. These are the five warehouses actually used as
# `custom_source_warehouse` on historical Sales Orders (by volume); anything
# else (Online/Torongo/Simotwo/packhouse one-offs) is excluded so cart orders
# converge on the warehouses operations actually pick from.
ALLOWED_SOURCE_WAREHOUSES = (
	"Ravine Available for Sale - KR",
	"Kapkolia Receiving Cold Store - KR",
	"Karen Available for Sale - KR",
	"Ravine Graded Sold - KR",
	"Karen Receiving Cold Store - KR",
)


def get_history_source_warehouse(item_code):
	"""Source warehouse most used for `item_code` on previous Sales Order lines.

	Looks at submitted Sales Order Item rows for this item and returns the
	`custom_source_warehouse` that appears most often, restricted to
	ALLOWED_SOURCE_WAREHOUSES. When the item has no history with any allowed
	warehouse, falls back to the first allowed warehouse (the overall
	most-used). Always returns a value from the allowed set — never None — so a
	cart line always lands on an approved source warehouse.
	"""
	allowed = ALLOWED_SOURCE_WAREHOUSES
	rows = frappe.db.sql(
		"""
		SELECT custom_source_warehouse AS wh, COUNT(*) AS cnt
		FROM `tabSales Order Item`
		WHERE item_code = %s AND docstatus = 1
		  AND custom_source_warehouse IN %s
		GROUP BY custom_source_warehouse
		""",
		(item_code, allowed),
		as_dict=True,
	)
	if rows:
		# Tie-break on the priority order so a tie is resolved deterministically
		# toward the higher-priority warehouse.
		return max(
			rows,
			key=lambda r: (r["cnt"], -allowed.index(r["wh"])),
		)["wh"]
	return allowed[0]
