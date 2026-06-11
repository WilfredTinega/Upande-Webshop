"""Date-scoped backfill for Stem Length Bin AND Stem Length Age Bin.

Adds the last N days of *Grading* stock movements to both bins as deltas,
using the SAME delta functions the live hook (update_stem_length_bin.
on_stock_entry_submit) calls. The result is therefore identical to what the
hook would have produced had it run on each of these entries.

WARNING — this ADDS deltas; it does not rebuild. If the live hook already
processed some of these Grading entries, running this will DOUBLE-COUNT them
in Stem Length Bin. Only run when you know the window was NOT hook-maintained
(e.g. the hook was deployed after these entries were submitted, or the bins
drifted and you have confirmed the gap). The Age Bin on this site started
empty, so it is the primary target.

Run:
    bench --site <site> execute \
        upande_webshop.patches.backfill_stem_length_5d.execute

Adjust the window:
    bench --site <site> execute \
        upande_webshop.patches.backfill_stem_length_5d.execute \
        --kwargs "{'days': 5, 'from_date': '2026-05-30'}"

Pass dry_run=True to only report the aggregate without writing.
"""

import frappe
from frappe.utils import add_days, getdate, nowdate

from upande_webshop.upande_webshop.doctype.stem_length_age_bin.stem_length_age_bin import (
	parse_harvest_date,
	update_age_bin_qty,
)
from upande_webshop.upande_webshop.doctype.stem_length_bin.stem_length_bin import (
	update_stem_length_bin_qty,
)


def _is_variant_or_template_set(item_codes):
	"""Return the subset of item_codes that are variants or templates.

	Mirrors update_stem_length_bin._is_variant_or_template: those items resolve
	stem length at the Item level, so core Bin already tracks per-length qty and
	the stem-length bins must skip them.
	"""
	skip = set()
	if not item_codes:
		return skip
	for it in frappe.db.get_all(
		"Item",
		filters={"name": ("in", list(item_codes))},
		fields=["name", "has_variants", "variant_of"],
	):
		if it.has_variants or it.variant_of:
			skip.add(it.name)
	return skip


def execute(days=5, from_date=None, to_date=None, dry_run=False):
	"""Backfill both stem-length bins for a posting-date window.

	days: window size in days back from today (ignored if from_date given).
	from_date / to_date: explicit inclusive bounds (YYYY-MM-DD).
	dry_run: aggregate and log only; no writes.
	"""
	days = int(days)
	to_date = getdate(to_date) if to_date else getdate(nowdate())
	from_date = getdate(from_date) if from_date else getdate(add_days(to_date, -days + 1))

	if not frappe.db.table_exists("Stem Length Bin"):
		print("Stem Length Bin table missing — aborting.")
		return

	# Pull the per-row Grading movements in the window. We keep the row-level
	# warehouse legs (s_warehouse / t_warehouse) instead of pre-summing in SQL,
	# so we can replay each leg exactly as the hook does. Length is the row's
	# custom_length, falling back to the header custom_stem_length.
	rows = frappe.db.sql(
		"""
		SELECT
			sed.item_code                                   AS item_code,
			COALESCE(NULLIF(sed.custom_length, ''),
			         se.custom_stem_length)                 AS stem_length,
			sed.s_warehouse                                 AS s_warehouse,
			sed.t_warehouse                                 AS t_warehouse,
			sed.transfer_qty                                AS transfer_qty,
			sed.qty                                         AS qty,
			se.custom_harvest_batch_no                      AS harvest_batch_no
		FROM `tabStock Entry` se
		INNER JOIN `tabStock Entry Detail` sed ON se.name = sed.parent
		WHERE
			se.stock_entry_type = 'Grading'
			AND se.docstatus = 1
			AND se.posting_date >= %(from_date)s
			AND se.posting_date <= %(to_date)s
			AND se.custom_harvest_batch_no IS NOT NULL
			AND NOT COALESCE(se.custom_scanned_packing, 0) = 1
			AND NOT COALESCE(se.custom_sold, 0) = 1
			AND NOT COALESCE(se.custom_transfered_to_local, 0) = 1
			AND NOT COALESCE(se.custom_rejected, 0) = 1
		""",
		{"from_date": from_date, "to_date": to_date},
		as_dict=True,
	)

	print(
		f"[backfill_stem_length_5d] window {from_date} .. {to_date}: "
		f"{len(rows)} grading detail rows"
	)
	if not rows:
		return

	item_codes = {r.item_code for r in rows if r.item_code}
	skip_items = _is_variant_or_template_set(item_codes)

	bin_legs = 0      # number of Stem Length Bin delta applications
	age_legs = 0      # number of Stem Length Age Bin delta applications
	total_stems = 0.0  # net stems landed in t_warehouse legs (sanity figure)

	for r in rows:
		if r.item_code in skip_items:
			continue
		stem_length = r.stem_length
		if not stem_length:
			continue
		qty = r.transfer_qty or r.qty
		if not qty:
			continue

		harvest_date = parse_harvest_date(r.harvest_batch_no)

		if dry_run:
			if r.t_warehouse:
				total_stems += float(qty)
			continue

		# Stem Length Bin: mirror on_stock_entry_submit — +t_warehouse, -s_warehouse.
		if r.t_warehouse:
			update_stem_length_bin_qty(r.item_code, r.t_warehouse, stem_length, qty)
			bin_legs += 1
		if r.s_warehouse:
			update_stem_length_bin_qty(r.item_code, r.s_warehouse, stem_length, -qty)
			bin_legs += 1

		# Stem Length Age Bin: only legs that carry a harvest date contribute.
		if harvest_date:
			if r.t_warehouse:
				update_age_bin_qty(
					r.item_code, r.t_warehouse, stem_length, harvest_date, qty
				)
				age_legs += 1
			if r.s_warehouse:
				update_age_bin_qty(
					r.item_code, r.s_warehouse, stem_length, harvest_date, -qty
				)
				age_legs += 1

		if (bin_legs + age_legs) % 4000 == 0:
			frappe.db.commit()

	if dry_run:
		print(
			f"[backfill_stem_length_5d] DRY RUN — would process "
			f"{len(rows)} rows; net inbound stems (t_warehouse legs): {total_stems}"
		)
		return

	frappe.db.commit()
	print(
		f"[backfill_stem_length_5d] done — Stem Length Bin legs: {bin_legs}, "
		f"Stem Length Age Bin legs: {age_legs}"
	)
