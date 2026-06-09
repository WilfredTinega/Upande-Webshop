"""Reconcile the Stem Length Bin and Stem Length Age Bin trackers to core Bin.

Both custom trackers drifted far above the real ERPNext Bin ledger because, until
the forward-fix in update_stem_length_bin.py, outbound Stock Entries that carried
no harvest batch (Material Transfer to Graded Sold, Delivery, Issue) were skipped
instead of decrementing the trackers. The trackers therefore only ever grew.

Core Bin is the only authoritative balance, but it is keyed by (item, warehouse)
with NO stem length. So the reconciliation works at the level each truth exists:

  1. Stem Length Bin  -> for each (item, warehouse), scale its per-length rows so
     their SUM equals core Bin.actual_qty for that (item, warehouse). If core Bin
     has no row / zero, all length rows for that key are zeroed. Reserved_qty is
     capped to the new actual_qty.

  2. Stem Length Age Bin -> for each (item, warehouse, stem_length), scale its
     per-harvest-date buckets so their SUM equals the reconciled Stem Length Bin
     actual_qty for that (item, warehouse, stem_length). Proportional scaling
     preserves the relative age distribution (newest vs oldest harvest).

Idempotent: running it again after it has converged is a no-op (deltas are ~0).

Usage (production):
    bench --site <site> execute \
        upande_webshop.upande_webshop.patches.reconcile_stem_length_trackers.run \
        --kwargs "{'dry_run': True}"

    # review the printed summary, then:
    bench --site <site> execute \
        upande_webshop.upande_webshop.patches.reconcile_stem_length_trackers.run \
        --kwargs "{'dry_run': False}"

Scope: by default reconciles ALL warehouses present in the trackers. Pass
`warehouses=[...]` to limit (e.g. just the Available-for-Sale set).

As a Frappe patch (listed in patches.txt) the module-level execute() runs on every
`bench migrate`/deploy. It applies (not dry-run), scoped to the flower warehouses
the trackers actually represent, so the stocks are re-squared to core Bin on each
release. Because the reconciliation is idempotent, re-running it once the data has
converged is a near no-op (only sub-stem rounding moves).
"""

import frappe
from frappe.utils import flt

# Warehouses the stem-length trackers actually carry rows for. Reconciliation is
# scoped to these so unrelated stock (raw materials, WIP, Graded Sold, Receiving
# Cold Stores) is never pulled in. The trackers only hold per-length rows for the
# Available-for-Sale warehouses; the /order-stock page reads exactly this set.
# Receiving Cold Stores are pre-grading (no stem length) and Graded Sold rows carry
# no length, so both are intentionally excluded — confirmed: neither tracker has
# any rows in those warehouses.
TRACKER_WAREHOUSES = [
	"Burguret Available for Sale - TL",
	"Turaco Available for Sale - TL",
	"Pendekeza Available for Sale - TL",
]


def _core_bin_balances(warehouses=None):
	"""{(item_code, warehouse): actual_qty} from core Bin."""
	filters = {}
	if warehouses:
		filters["warehouse"] = ["in", warehouses]
	rows = frappe.get_all(
		"Bin", filters=filters, fields=["item_code", "warehouse", "actual_qty"]
	)
	return {(r.item_code, r.warehouse): flt(r.actual_qty) for r in rows}


def _reconcile_stem_length_bin(core, warehouses, dry_run):
	"""Scale Stem Length Bin per (item, warehouse) to core Bin total.

	Returns {(item, warehouse, stem_length): reconciled_actual_qty} so the age-bin
	pass can target the same per-length numbers.
	"""
	filters = {}
	if warehouses:
		filters["warehouse"] = ["in", warehouses]
	rows = frappe.get_all(
		"Stem Length Bin",
		filters=filters,
		fields=["name", "item_code", "warehouse", "stem_length", "actual_qty", "reserved_qty"],
	)

	# Group rows by (item, warehouse).
	groups = {}
	for r in rows:
		groups.setdefault((r.item_code, r.warehouse), []).append(r)

	per_length_target = {}
	stats = {"rows": 0, "changed": 0, "before": 0.0, "after": 0.0, "zeroed_groups": 0}

	for (item_code, warehouse), grp in groups.items():
		tracker_sum = sum(flt(r.actual_qty) for r in grp)
		truth = core.get((item_code, warehouse), 0.0)
		stats["before"] += tracker_sum

		if tracker_sum <= 0:
			# Nothing to scale; targets are 0.
			for r in grp:
				per_length_target[(item_code, warehouse, r.stem_length)] = 0.0
			continue

		scale = truth / tracker_sum if tracker_sum else 0.0
		if truth <= 0:
			stats["zeroed_groups"] += 1

		for r in grp:
			stats["rows"] += 1
			new_actual = round(flt(r.actual_qty) * scale, 2)
			new_reserved = min(flt(r.reserved_qty), new_actual)
			per_length_target[(item_code, warehouse, r.stem_length)] = new_actual
			stats["after"] += new_actual
			if abs(new_actual - flt(r.actual_qty)) > 0.005 or abs(
				new_reserved - flt(r.reserved_qty)
			) > 0.005:
				stats["changed"] += 1
				if not dry_run:
					frappe.db.set_value(
						"Stem Length Bin",
						r.name,
						{
							"actual_qty": new_actual,
							"reserved_qty": new_reserved,
							"projected_qty": new_actual - new_reserved,
						},
						update_modified=False,
					)

	return per_length_target, stats


def _reconcile_age_bin(per_length_target, warehouses, dry_run):
	"""Scale Stem Length Age Bin buckets per (item, warehouse, length) to target."""
	filters = {}
	if warehouses:
		filters["warehouse"] = ["in", warehouses]
	rows = frappe.get_all(
		"Stem Length Age Bin",
		filters=filters,
		fields=["name", "item_code", "warehouse", "stem_length", "harvest_date", "actual_qty"],
	)

	groups = {}
	for r in rows:
		groups.setdefault((r.item_code, r.warehouse, r.stem_length), []).append(r)

	stats = {"rows": 0, "changed": 0, "before": 0.0, "after": 0.0}

	for key, grp in groups.items():
		bucket_sum = sum(flt(r.actual_qty) for r in grp)
		# Target: the reconciled Stem Length Bin per-length value. If that key has
		# no Stem Length Bin row at all, treat truth as 0 (the age bin holds stock
		# the per-length balance doesn't know about -> drift to remove).
		truth = per_length_target.get(key, 0.0)
		stats["before"] += bucket_sum

		scale = (truth / bucket_sum) if bucket_sum > 0 else 0.0
		for r in grp:
			stats["rows"] += 1
			new_qty = round(flt(r.actual_qty) * scale, 2)
			stats["after"] += new_qty
			if abs(new_qty - flt(r.actual_qty)) > 0.005:
				stats["changed"] += 1
				if not dry_run:
					frappe.db.set_value(
						"Stem Length Age Bin",
						r.name,
						"actual_qty",
						new_qty,
						update_modified=False,
					)

	return stats


def run(dry_run=True, warehouses=None):
	"""Reconcile both trackers to core Bin. dry_run=True computes without writing."""
	if isinstance(dry_run, str):
		dry_run = dry_run.lower() not in ("false", "0", "no", "")

	core = _core_bin_balances(warehouses)

	sl_target, sl_stats = _reconcile_stem_length_bin(core, warehouses, dry_run)
	age_stats = _reconcile_age_bin(sl_target, warehouses, dry_run)

	if not dry_run:
		frappe.db.commit()

	mode = "DRY RUN (no writes)" if dry_run else "APPLIED"
	print(f"\n=== Stem Length tracker reconciliation — {mode} ===")
	print(f"Scope: {'ALL warehouses' if not warehouses else warehouses}")
	print(
		"\nStem Length Bin:"
		f"\n  rows seen      : {sl_stats['rows']}"
		f"\n  rows changed   : {sl_stats['changed']}"
		f"\n  groups zeroed  : {sl_stats['zeroed_groups']} (no core Bin balance)"
		f"\n  qty before     : {round(sl_stats['before'])}"
		f"\n  qty after      : {round(sl_stats['after'])}"
	)
	print(
		"\nStem Length Age Bin:"
		f"\n  rows seen      : {age_stats['rows']}"
		f"\n  rows changed   : {age_stats['changed']}"
		f"\n  qty before     : {round(age_stats['before'])}"
		f"\n  qty after      : {round(age_stats['after'])}"
	)
	core_total = round(sum(core.values()))
	print(f"\nCore Bin total (target, scoped): {core_total}")
	print("=== end ===\n")

	return {
		"dry_run": dry_run,
		"stem_length_bin": sl_stats,
		"stem_length_age_bin": age_stats,
		"core_bin_total": core_total,
	}


def execute():
	"""Frappe patch entry point — runs on every `bench migrate`/deploy.

	Applies the reconciliation (not dry-run) scoped to TRACKER_WAREHOUSES so the
	Stem Length Bin and Stem Length Age Bin trackers are re-squared to core Bin on
	each release. Idempotent: once converged, re-runs only nudge sub-stem rounding.

	patches.txt re-runs an entry only when its line changes, so this fires once per
	deploy that bumps it. The forward-fix in update_stem_length_bin.py keeps the
	trackers honest between deploys; this is the periodic safety net that erases any
	residual drift (e.g. movements made before the forward-fix shipped, or edge-case
	entries that bypass the Stock Entry hook).
	"""
	run(dry_run=False, warehouses=TRACKER_WAREHOUSES)
