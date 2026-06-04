import frappe
from frappe.model.document import Document
from frappe.utils import flt


class StemLengthAgeBin(Document):
	pass


def on_doctype_update():
	"""One bin row per (item, warehouse, stem_length, harvest_date).

	The unique key lets us upsert qty deltas without a doc save, and keeps the
	age read (GROUP BY days-since-harvest) on an indexed Date column instead of
	parsing harvest dates out of Stock Entry batch strings on every page load.
	"""
	frappe.db.add_unique(
		"Stem Length Age Bin",
		["item_code", "warehouse", "stem_length", "harvest_date"],
		constraint_name="unique_item_wh_length_harvest",
	)


def parse_harvest_date(batch_no):
	"""Extract the harvest date (YYYY-MM-DD) from a custom_harvest_batch_no.

	Batch numbers look like '<label>/<YYYY-MM-DD HH:MM:SS.ffffff>'. Returns the
	date portion as a string, or None if it can't be parsed.
	"""
	if not batch_no or "/" not in batch_no:
		return None
	tail = batch_no.rsplit("/", 1)[-1].strip()
	# tail is a datetime string; the date is the leading 10 chars (YYYY-MM-DD).
	date_part = tail[:10]
	try:
		from frappe.utils import getdate

		return getdate(date_part).isoformat()
	except Exception:
		return None


def update_age_bin_qty(item_code, warehouse, stem_length, harvest_date, qty_delta):
	"""Apply qty_delta to the (item, warehouse, length, harvest_date) age row.

	Creates the row when it doesn't exist and qty_delta is positive. Mirrors
	Stem Length Bin's raw-delta hot path — no document save, no hooks. Rows that
	hit zero are left in place (cheap; the read filters them out via SUM).
	"""
	if not (item_code and warehouse and stem_length and harvest_date) or not qty_delta:
		return

	name = frappe.db.get_value(
		"Stem Length Age Bin",
		{
			"item_code": item_code,
			"warehouse": warehouse,
			"stem_length": stem_length,
			"harvest_date": harvest_date,
		},
		"name",
	)

	if not name:
		# A stock-out (negative delta) against a harvest bucket we never recorded
		# is a no-op: don't create a row, never go below zero. The real balance
		# lives in Stem Length Bin; the age bin is a working tracker that must
		# never interfere with it.
		if qty_delta <= 0:
			return
		doc = frappe.new_doc("Stem Length Age Bin")
		doc.item_code = item_code
		doc.warehouse = warehouse
		doc.stem_length = stem_length
		doc.harvest_date = harvest_date
		doc.actual_qty = flt(qty_delta)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		return

	# Floor at zero. When a stock-out exceeds what this bucket holds (e.g. the
	# outbound movement didn't carry the original harvest batch, so the draw-down
	# lands on the wrong bucket), the bucket bottoms out at 0 rather than going
	# negative. Over ~a month, as old batches sell through and fresh harvest
	# rebuilds the buckets, the age bin's totals converge back to the main bin.
	current = flt(frappe.db.get_value("Stem Length Age Bin", name, "actual_qty"))
	new_qty = current + flt(qty_delta)
	if new_qty < 0:
		new_qty = 0
	frappe.db.set_value(
		"Stem Length Age Bin", name, "actual_qty", new_qty, update_modified=False
	)
