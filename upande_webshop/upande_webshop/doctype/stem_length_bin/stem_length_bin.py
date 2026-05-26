import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class StemLengthBin(Document):
	def before_save(self):
		if self.get("__islocal") or not self.stock_uom:
			self.stock_uom = frappe.get_cached_value("Item", self.item_code, "stock_uom")
		self.set_projected_qty()

	def set_projected_qty(self):
		self.projected_qty = flt(self.actual_qty) - flt(self.reserved_qty)


def on_doctype_update():
	"""Mirror ERPNext Bin's natural-key uniqueness, extended with stem_length.

	Runs after every migrate; frappe.db.add_unique is a no-op if the index
	already exists.
	"""
	frappe.db.add_unique(
		"Stem Length Bin",
		["item_code", "warehouse", "stem_length"],
		constraint_name="unique_item_warehouse_stem_length",
	)


def get_stem_length_bin(item_code, warehouse, stem_length, create=False):
	"""Return Stem Length Bin name for the key, optionally creating it."""
	name = frappe.db.get_value(
		"Stem Length Bin",
		{"item_code": item_code, "warehouse": warehouse, "stem_length": stem_length},
		"name",
	)
	if name or not create:
		return name

	doc = frappe.new_doc("Stem Length Bin")
	doc.item_code = item_code
	doc.warehouse = warehouse
	doc.stem_length = stem_length
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _apply_delta(bin_name, actual_delta=0, reserved_delta=0):
	"""Atomic in-place qty update, mirroring erpnext.stock.doctype.bin.bin.update_qty.

	Reads current row, computes new values, writes with frappe.db.set_value —
	no document save, no validate, no hooks. Safe to call in hot paths.
	"""
	row = frappe.db.get_value(
		"Stem Length Bin",
		bin_name,
		["actual_qty", "reserved_qty"],
		as_dict=True,
	)
	if not row:
		return

	actual_qty = flt(row.actual_qty) + flt(actual_delta)
	reserved_qty = flt(row.reserved_qty) + flt(reserved_delta)
	projected_qty = actual_qty - reserved_qty

	if actual_qty < 0:
		frappe.log_error(
			f"Stem Length Bin {bin_name} actual_qty negative: {actual_qty}",
			"Stem Length Bin underflow",
		)
	if reserved_qty < 0:
		reserved_qty = 0
		projected_qty = actual_qty

	frappe.db.set_value(
		"Stem Length Bin",
		bin_name,
		{
			"actual_qty": actual_qty,
			"reserved_qty": reserved_qty,
			"projected_qty": projected_qty,
		},
		update_modified=True,
	)


def update_stem_length_bin_qty(item_code, warehouse, stem_length, qty_delta):
	"""Apply qty_delta to actual_qty. Creates the bin row if it doesn't exist
	and qty_delta is positive."""
	if not (item_code and warehouse and stem_length) or not qty_delta:
		return

	bin_name = get_stem_length_bin(item_code, warehouse, stem_length, create=qty_delta > 0)
	if not bin_name:
		return
	_apply_delta(bin_name, actual_delta=qty_delta)


def reserve_stem_length_qty(item_code, warehouse, stem_length, qty):
	"""Increase reserved_qty. Throws if bin missing or actual_qty - reserved_qty < qty."""
	qty = flt(qty)
	if qty <= 0:
		return

	bin_name = get_stem_length_bin(item_code, warehouse, stem_length, create=False)
	if not bin_name:
		frappe.throw(
			_("No Stem Length Bin found for {0} / {1} in {2}").format(item_code, stem_length, warehouse)
		)

	row = frappe.db.get_value(
		"Stem Length Bin", bin_name, ["actual_qty", "reserved_qty"], as_dict=True
	)
	available = flt(row.actual_qty) - flt(row.reserved_qty)
	if available < qty:
		frappe.throw(
			_("Insufficient stem-length stock for {0} {1} in {2}: need {3}, available {4}").format(
				item_code, stem_length, warehouse, qty, available
			)
		)

	_apply_delta(bin_name, reserved_delta=qty)


def release_stem_length_qty(item_code, warehouse, stem_length, qty):
	"""Decrease reserved_qty. Clamped at zero in _apply_delta to tolerate replays."""
	qty = flt(qty)
	if qty <= 0:
		return
	bin_name = get_stem_length_bin(item_code, warehouse, stem_length, create=False)
	if not bin_name:
		return
	_apply_delta(bin_name, reserved_delta=-qty)


def get_stock_by_length(item_code):
	"""Return {stem_length_name: actual_qty} for one item across the storefront set.

	Warehouse resolution uses _all_storefront_warehouses so the totals match the
	listing's "In stock (N)" badge. The fallback (per-item website_warehouse) is
	used only if Webshop Settings has no warehouses configured.

	Used by templates that need to render a length-by-length availability picker.
	"""
	from upande_webshop.upande_webshop.product_data_engine.query import (
		_all_storefront_warehouses,
	)

	ws_warehouse = frappe.db.get_value(
		"Website Item", {"item_code": item_code}, "website_warehouse"
	)
	warehouses = _all_storefront_warehouses(ws_warehouse)
	if not warehouses:
		return {}

	rows = frappe.db.get_all(
		"Stem Length Bin",
		fields=["stem_length", "actual_qty"],
		filters={"item_code": item_code, "warehouse": ("in", warehouses)},
	)
	qty_by_sl = {}
	for r in rows:
		if not r.stem_length:
			continue
		qty_by_sl[r.stem_length] = qty_by_sl.get(r.stem_length, 0) + flt(r.actual_qty)
	return qty_by_sl
