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


def use_stem_length_age_bin():
	"""True when the storefront should layer the Stem Length Age Bin (harvest-age
	FIFO buckets) under the Stem Length Bin for plain-item availability.

	Plain-item stock precedence:
	  - Flag OFF: read core Bin (item + warehouse), except the per-length picker
	    which has no Bin equivalent and stays on Stem Length Bin.
	  - Flag ON : read Stem Length Bin per length, falling back to the Age Bin for
	    any length with no Stem Length Bin row.

	Guarded by the existence of the Stem Length Age Bin doctype so a site without
	the tracker never trips on a missing table even if the flag is somehow set.
	The Age Bin is always WRITTEN (every stock entry buckets by harvest date);
	this flag only switches the READ path the storefront uses.
	"""
	return age_bin_enabled("Webshop Settings")


def age_bin_enabled(settings_doctype):
	"""True when `settings_doctype` (a Single) has use_stem_length_age_bin on and the
	Stem Length Age Bin doctype exists.

	Lets non-webshop consumers (Biflorica Setting, Floriday Settings) opt into the
	same Age-Bin read path via their own flag, reusing get_age_bin_qty* below.
	"""
	if not frappe.get_cached_value(
		settings_doctype, settings_doctype, "use_stem_length_age_bin"
	):
		return False
	return bool(frappe.db.exists("DocType", "Stem Length Age Bin"))


def _qty_by_length(doctype, item_code, warehouses):
	"""{stem_length_name: actual_qty} summed for one item from a length-keyed bin
	doctype (Stem Length Bin or Stem Length Age Bin), scoped to warehouses."""
	if not warehouses:
		return {}
	rows = frappe.db.get_all(
		doctype,
		fields=["stem_length", "actual_qty"],
		filters={"item_code": item_code, "warehouse": ("in", warehouses)},
	)
	qty_by_sl = {}
	for r in rows:
		if not r.stem_length:
			continue
		qty_by_sl[r.stem_length] = qty_by_sl.get(r.stem_length, 0) + flt(r.actual_qty)
	return qty_by_sl


def get_age_bin_qty_by_length(item_code, warehouses):
	"""Per-length availability with the Age Bin as fallback.

	Reads Stem Length Bin first; for any length missing there, fills the qty from
	the Stem Length Age Bin. Used when use_stem_length_age_bin() is on.
	"""
	sl = _qty_by_length("Stem Length Bin", item_code, warehouses)
	age = _qty_by_length("Stem Length Age Bin", item_code, warehouses)
	merged = dict(age)
	merged.update(sl)  # Stem Length Bin wins; Age Bin only fills the gaps
	return merged


def get_age_bin_qty_for_items(item_codes, warehouses):
	"""{item_code: total_qty} with the Age Bin as fallback, summed across lengths.

	Per item, sums Stem Length Bin and tops up only the lengths the Stem Length
	Bin doesn't carry from the Age Bin. Used by the listing grid / item totals
	when use_stem_length_age_bin() is on."""
	if not item_codes or not warehouses:
		return {}
	item_codes = list(item_codes)
	totals = {}
	for code in item_codes:
		totals[code] = sum(get_age_bin_qty_by_length(code, warehouses).values())
	return totals


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
	# negative.
	current = flt(frappe.db.get_value("Stem Length Age Bin", name, "actual_qty"))
	new_qty = current + flt(qty_delta)
	if new_qty < 0:
		new_qty = 0
	frappe.db.set_value(
		"Stem Length Age Bin", name, "actual_qty", new_qty, update_modified=False
	)


def drawdown_age_bin_fifo(item_code, warehouse, stem_length, qty):
	"""Decrement age-bin buckets for (item, warehouse, length) oldest-harvest-first.

	Used for outbound movements that carry NO harvest batch (Material Transfer to
	Graded Sold, Delivery, Issue, etc.). Without this, those outflows used to be
	skipped entirely — the age bin only ever grew, drifting far above the real
	Bin balance. Drawing down oldest-first mirrors how the freshest stock is held
	back and the oldest sells first, and keeps the visible Day 0-3 window honest.

	`qty` is a positive number of stems to remove. Buckets are floored at 0; any
	shortfall beyond what the buckets hold is dropped (the authoritative balance
	lives in core Bin — the age bin must never block a real movement).
	"""
	qty = flt(qty)
	if not (item_code and warehouse and stem_length) or qty <= 0:
		return

	rows = frappe.get_all(
		"Stem Length Age Bin",
		filters={
			"item_code": item_code,
			"warehouse": warehouse,
			"stem_length": stem_length,
			"actual_qty": [">", 0],
		},
		fields=["name", "actual_qty"],
		order_by="harvest_date asc",  # oldest harvest first
	)

	remaining = qty
	for r in rows:
		if remaining <= 0:
			break
		take = min(flt(r.actual_qty), remaining)
		new_qty = flt(r.actual_qty) - take
		frappe.db.set_value(
			"Stem Length Age Bin", r.name, "actual_qty", new_qty, update_modified=False
		)
		remaining -= take


def restock_age_bin_fifo(item_code, warehouse, stem_length, qty):
	"""Reverse of drawdown — used to undo a no-harvest-batch outbound on cancel.

	Puts qty back into the newest existing bucket (best effort). If no bucket
	exists for the key, nothing is created: a cancel of a movement we couldn't
	attribute to a harvest date has nowhere correct to land, and inventing a
	bucket would re-inflate the tracker. The next reconciliation squares it.
	"""
	qty = flt(qty)
	if not (item_code and warehouse and stem_length) or qty <= 0:
		return

	newest = frappe.get_all(
		"Stem Length Age Bin",
		filters={
			"item_code": item_code,
			"warehouse": warehouse,
			"stem_length": stem_length,
		},
		fields=["name", "actual_qty"],
		order_by="harvest_date desc",
		limit=1,
	)
	if not newest:
		return
	r = newest[0]
	frappe.db.set_value(
		"Stem Length Age Bin",
		r.name,
		"actual_qty",
		flt(r.actual_qty) + qty,
		update_modified=False,
	)
