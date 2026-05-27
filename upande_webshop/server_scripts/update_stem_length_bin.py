import frappe

from upande_webshop.upande_webshop.doctype.stem_length_bin.stem_length_bin import (
	release_stem_length_qty,
	reserve_stem_length_qty,
	update_stem_length_bin_qty,
)


def _row_stem_length(item, header_stem_length):
	"""Stock Entry Detail.custom_length is authoritative; the header field is a fallback
	for entries created before the row field was being populated."""
	return item.get("custom_length") or header_stem_length


def _is_variant_or_template(item_code):
	"""Return True if item_code is a variant or a template.

	Variants and templates both resolve stem length at the Item level (each
	variant is a distinct item_code), so core Bin already tracks per-length
	qty for them. Stem Length Bin is only meaningful for plain items where
	one item_code covers multiple lengths.

	Cache is request-scoped via frappe.local to avoid repeated DB lookups
	within a single hook invocation across many items.
	"""
	cache = getattr(frappe.local, "_stem_length_bin_variant_cache", None)
	if cache is None:
		cache = {}
		frappe.local._stem_length_bin_variant_cache = cache

	if item_code in cache:
		return cache[item_code]

	row = frappe.db.get_value(
		"Item", item_code, ["has_variants", "variant_of"], as_dict=True
	)
	if not row:
		# Unknown item — be conservative and skip; the hook will no-op.
		cache[item_code] = True
		return True

	result = bool(row.has_variants) or bool(row.variant_of)
	cache[item_code] = result
	return result


def on_stock_entry_submit(doc, method=None):
	"""Mirror what Stock Entry already did to core Bin, but at (item, warehouse, stem_length)
	granularity. Runs for every entry type — rows without custom_length are skipped
	(receiving / pre-grading entries don't have length info yet). Variant and template
	items are also skipped — core Bin already tracks per-length qty for them via
	distinct item_codes."""
	header_sl = doc.get("custom_stem_length")

	for item in doc.items:
		if _is_variant_or_template(item.item_code):
			continue

		stem_length = _row_stem_length(item, header_sl)
		if not stem_length:
			continue

		qty = item.transfer_qty or item.qty
		if not qty:
			continue

		if item.t_warehouse:
			update_stem_length_bin_qty(item.item_code, item.t_warehouse, stem_length, qty)
		if item.s_warehouse:
			update_stem_length_bin_qty(item.item_code, item.s_warehouse, stem_length, -qty)


def on_stock_entry_cancel(doc, method=None):
	header_sl = doc.get("custom_stem_length")

	for item in doc.items:
		if _is_variant_or_template(item.item_code):
			continue

		stem_length = _row_stem_length(item, header_sl)
		if not stem_length:
			continue

		qty = item.transfer_qty or item.qty
		if not qty:
			continue

		if item.t_warehouse:
			update_stem_length_bin_qty(item.item_code, item.t_warehouse, stem_length, -qty)
		if item.s_warehouse:
			update_stem_length_bin_qty(item.item_code, item.s_warehouse, stem_length, qty)


def on_sales_order_submit(doc, method=None):
	for item in doc.items:
		if _is_variant_or_template(item.item_code):
			continue

		stem_length = item.get("custom_length")
		warehouse = item.get("custom_source_warehouse") or item.get("warehouse")
		if stem_length and warehouse and item.stock_qty:
			reserve_stem_length_qty(item.item_code, warehouse, stem_length, item.stock_qty)


def on_sales_order_cancel(doc, method=None):
	for item in doc.items:
		if _is_variant_or_template(item.item_code):
			continue

		stem_length = item.get("custom_length")
		warehouse = item.get("custom_source_warehouse") or item.get("warehouse")
		if stem_length and warehouse and item.stock_qty:
			release_stem_length_qty(item.item_code, warehouse, stem_length, item.stock_qty)
