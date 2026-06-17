"""Shelf / warehouse stock read helpers for the webshop publish picker.

Physical graded stems live on kaitet `Shelf` / `Shelf Item` rows. The shelf is a
standalone table with no ERPNext stock-ledger integration — `Shelf Item.stem_qty`
is just a count, never reflected in `tabBin`.

This module exposes the read-only queries that power the "enable stock → webshop"
picker on the Webshop / Floriday / Biflorica settings forms: the current shelf
rows (`get_shelf_rows`), the configured-warehouse Bin rows (`get_warehouse_rows`),
and the on-shelf item link query (`shelf_item_query`). Publishing flips the Stem
Length Price `enabled` flag — no stock is moved. (The earlier shelf↔online
Material Transfer flow was removed.)
"""

import frappe
from frappe.utils import flt

from upande_webshop.upande_webshop.doctype.box_type.box_type import (
	_stems_per_bunch_from_uom,
)


def shelf_doctype_present():
	"""True when this site has the kaitet Shelf doctypes installed."""
	return bool(frappe.db.exists("DocType", "Shelf Item"))


def _bunch_size(sales_uom, stock_uom):
	"""Stems-per-bunch step for an item, parsed from its sales UOM name.

	"Bunch (10)"/"Bunch(10)" -> 10; falls back to 1 (single stems) when neither
	UOM encodes a bunch size. Mirrors box_type._stems_per_bunch_from_uom so the
	picker's "Qty to Enable" steps in the same unit the cart sells in."""
	size = _stems_per_bunch_from_uom(sales_uom or stock_uom)
	return size if size and size > 0 else 1


@frappe.whitelist()
def get_shelf_rows():
	"""Every (shelf, variety, stem length) currently on a Shelf with positive qty.

	Returns a list of {shelf, item_code, item_name, stem_length, shelf_qty},
	one row per distinct combination, summed across the FIFO `Shelf Item` rows.
	Powers the inline "enable shelf stock → online" picker on the settings forms
	(checkbox + editable qty per row, no dialog). Empty list when the Shelf Item
	doctype isn't installed.
	"""
	if not shelf_doctype_present():
		return []

	rows = frappe.db.sql(
		"""
		SELECT si.parent AS shelf, si.variety AS item_code, i.item_name,
		       i.sales_uom, i.stock_uom,
		       si.stem_length, SUM(si.stem_qty) AS shelf_qty
		FROM `tabShelf Item` si
		JOIN `tabItem` i ON i.name = si.variety
		WHERE si.parenttype = 'Shelf' AND si.stem_qty > 0
		GROUP BY si.parent, si.variety, si.stem_length
		HAVING shelf_qty > 0
		ORDER BY si.parent, i.item_name, si.stem_length
		""",
		as_dict=True,
	)
	for r in rows:
		r["shelf_qty"] = int(flt(r.get("shelf_qty")))
		r["bunch_size"] = _bunch_size(r.get("sales_uom"), r.get("stock_uom"))
	return rows


@frappe.whitelist()
def get_warehouse_rows():
	"""Same shape as get_shelf_rows(), but sourced from the configured Webshop
	warehouses' Bin stock instead of Shelves.

	Returns {shelf, item_code, item_name, stem_length, shelf_qty} where `shelf` is
	the warehouse name and `stem_length` is "" (warehouse items are variants — the
	length is encoded in the item code, so it isn't a separate column). One row per
	(warehouse, item) with positive actual_qty. This lets the exact same picker
	panel + enable flow drive warehouse stock.
	"""
	from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses
	from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
		get_configured_warehouses,
	)

	warehouses = get_configured_warehouses()
	if not warehouses:
		return []

	# Expand group warehouses to leaves but report stock under the configured name.
	name_by_leaf = {}
	for wh in warehouses:
		if frappe.get_cached_value("Warehouse", wh, "is_group") == 1:
			leaves = get_child_warehouses(wh) or []
		else:
			leaves = [wh]
		for leaf in leaves:
			name_by_leaf.setdefault(leaf, wh)

	if not name_by_leaf:
		return []

	placeholders = ",".join(["%s"] * len(name_by_leaf))
	bins = frappe.db.sql(
		f"""
		SELECT b.warehouse, b.item_code, i.item_name,
		       i.sales_uom, i.stock_uom, b.actual_qty
		FROM `tabBin` b
		JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.warehouse IN ({placeholders}) AND b.actual_qty > 0
		""",
		tuple(name_by_leaf.keys()),
		as_dict=True,
	)

	# Aggregate leaf qty up to the configured warehouse name.
	agg = {}
	for b in bins:
		shelf = name_by_leaf.get(b.warehouse, b.warehouse)
		key = (shelf, b.item_code)
		row = agg.get(key)
		if not row:
			row = {
				"shelf": shelf,
				"item_code": b.item_code,
				"item_name": b.item_name or b.item_code,
				"stem_length": "",
				"shelf_qty": 0,
				"bunch_size": _bunch_size(b.get("sales_uom"), b.get("stock_uom")),
			}
			agg[key] = row
		row["shelf_qty"] += int(flt(b.actual_qty))

	rows = [r for r in agg.values() if r["shelf_qty"] > 0]
	rows.sort(key=lambda r: (r["shelf"], r["item_name"]))
	return rows


def _canon_length(value):
	"""Canonical "<n>cm" stem-length, or "" when there's no number.

	Matches enabled_stock._canon_length so available-qty keys line up with the
	published Stem Length Price rows."""
	import re

	if value is None:
		return ""
	m = re.search(r"\d+", str(value))
	return f"{int(m.group(0))}cm" if m else ""


def available_qty_by_key():
	"""{(item_code, canonical_length): available_qty} across the active source.

	Used to cap what can be published to the webshop — you can never enable more
	than is physically available. Reads BOTH shelf and warehouse rows so the cap
	holds regardless of which source the panel is showing; an item present in both
	is summed. Length is "" for warehouse rows (no length dimension)."""
	out = {}
	for r in get_shelf_rows() + get_warehouse_rows():
		key = (r.get("item_code"), _canon_length(r.get("stem_length")))
		out[key] = out.get(key, 0.0) + flt(r.get("shelf_qty"))
	return out


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def shelf_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link-field query: Items present on a given Shelf (with positive qty).

	`filters.shelf` scopes the result to one Shelf. Used by the Webshop Settings
	move dialog so the Item picker only offers what's actually on the shelf.
	"""
	shelf = (filters or {}).get("shelf")
	if not shelf:
		return []
	like = f"%{txt}%" if txt else "%"
	return frappe.db.sql(
		"""
		SELECT si.variety, i.item_name
		FROM `tabShelf Item` si
		JOIN `tabItem` i ON i.name = si.variety
		WHERE si.parenttype = 'Shelf' AND si.parent = %(shelf)s
		  AND si.stem_qty > 0
		  AND (si.variety LIKE %(txt)s OR i.item_name LIKE %(txt)s)
		GROUP BY si.variety, i.item_name
		ORDER BY si.variety
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"shelf": shelf,
			"txt": like,
			"start": int(start or 0),
			"page_len": int(page_len or 20),
		},
	)


def online_warehouse_qty_for_items(warehouse, item_codes):
	"""{item_code: actual_qty} in `warehouse` for many items (one Bin query)."""
	if not warehouse or not item_codes:
		return {}
	rows = frappe.db.get_all(
		"Bin",
		filters={"item_code": ("in", list(item_codes)), "warehouse": warehouse},
		fields=["item_code", "actual_qty"],
	)
	out = {}
	for r in rows:
		out[r.item_code] = out.get(r.item_code, 0.0) + flt(r.actual_qty)
	return out
