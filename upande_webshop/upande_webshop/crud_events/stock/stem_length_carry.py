"""Carry custom_stem_length from Stock Entry header → row → Stock Ledger Entry.

The field names are inconsistent across doctypes (legacy ERPNext customization):
  - Stock Entry             : custom_stem_length  (header, Link → Stem Length)
  - Stock Entry Detail      : custom_length       (row,    Link → Stem Length)
  - Stock Ledger Entry      : custom_stem_length  (Link → Stem Length)

ERPNext copies same-named fields automatically, but it can't copy across the
naming mismatch — so dispatches lose the length tag when SLE rows are created.

This module:
  1. Fills empty row.custom_length from header.custom_stem_length before save.
  2. After SLE rows are created (Stock Entry on_submit), copies each SLE's
     custom_stem_length from the originating Stock Entry Detail row.
  3. Provides a one-off backfill for historical data.
"""
from __future__ import annotations

import frappe


# ---------- Forward-fix hooks --------------------------------------------------


def _row_length(row):
	"""Return the stem length on a Stock Entry Detail row, preferring custom_stem_length.

	The doctype carries two custom fields for the same concept (legacy):
	  - custom_length         (Link → Stem Length, present today on most rows)
	  - custom_stem_length    (Link → Stem Length, added for the Inventory Dimension)
	We treat custom_stem_length as canonical when both exist, falling back to
	custom_length so this works before and after the rename rollout.
	"""
	for fname in ("custom_stem_length", "custom_length"):
		value = (row.get(fname) or "").strip()
		if value:
			return value
	return ""


def stock_entry_before_save(doc, method=None):
	"""Copy header custom_stem_length into every empty row, on BOTH length fields.

	Only fills empties — explicit per-row overrides are preserved. Writes to
	both row.custom_length and row.custom_stem_length so SED stays consistent
	regardless of which field downstream readers consult.
	"""
	header_length = (doc.get("custom_stem_length") or "").strip()
	if not header_length:
		# Even with no header, mirror within a row if only one side is set.
		for row in doc.get("items") or []:
			length = _row_length(row)
			if length:
				if not (row.get("custom_length") or "").strip():
					row.custom_length = length
				if not (row.get("custom_stem_length") or "").strip():
					row.custom_stem_length = length
		return

	for row in doc.get("items") or []:
		if not (row.get("custom_length") or "").strip():
			row.custom_length = header_length
		if not (row.get("custom_stem_length") or "").strip():
			row.custom_stem_length = header_length


def stock_entry_on_submit(doc, method=None):
	"""Sync custom_stem_length to SED + SLE on submit.

	Two responsibilities:
	  1. Ensure every SED row has BOTH `custom_length` and `custom_stem_length`
	     populated. `before_save` already does this on form save, but a doc
	     inserted programmatically (REST, scripts) can bypass it — so we
	     re-apply the same rule here defensively, then persist via SQL since
	     the doc is already submitted.
	  2. Backfill the matching SLE rows' `custom_stem_length` from the SED
	     row's length. SLE rows exist by the time this hook fires.
	"""
	header_length = (doc.get("custom_stem_length") or "").strip()

	# --- Step 1: ensure SED rows carry both length fields --------------------
	for row in doc.get("items") or []:
		current_length = _row_length(row)
		desired_length = current_length or header_length
		if not desired_length:
			continue

		sed_updates = {}
		if not (row.get("custom_length") or "").strip():
			row.custom_length = desired_length
			sed_updates["custom_length"] = desired_length
		if not (row.get("custom_stem_length") or "").strip():
			row.custom_stem_length = desired_length
			sed_updates["custom_stem_length"] = desired_length

		if sed_updates:
			# doc is already submitted; use db_set on the child row to persist
			frappe.db.set_value(
				"Stock Entry Detail", row.name, sed_updates, update_modified=False
			)

	# --- Step 2: backfill SLE.custom_stem_length from SED row's length -------
	for row in doc.get("items") or []:
		length = _row_length(row)
		if not length:
			continue
		# An SED row can produce up to 2 SLE rows (source + target warehouse
		# for transfers). Match by voucher_detail_no and item_code to be safe.
		frappe.db.sql(
			"""
			UPDATE `tabStock Ledger Entry`
			SET custom_stem_length = %s
			WHERE voucher_type = 'Stock Entry'
			  AND voucher_no = %s
			  AND voucher_detail_no = %s
			  AND item_code = %s
			  AND (custom_stem_length IS NULL OR custom_stem_length = '')
			""",
			(length, doc.name, row.name, row.item_code),
		)


# ---------- One-off backfill ---------------------------------------------------


@frappe.whitelist()
def backfill_stem_length(
	commit_every=500,
	dry_run=0,
	days=7,
	from_date=None,
	to_date=None,
	item_codes=None,
):
	"""Backfill historical Stock Entry Detail.custom_length and SLE.custom_stem_length.

	Four passes:
	  1. SED row.custom_length / custom_stem_length filled from parent SE header.
	  2. SLE.custom_stem_length filled from originating SED row.
	  3. Untagged dispatch rows (Material Transfer / Material Issue) inferred
	     from the most-recent tagged Grading SED for same (item, warehouse).
	  4. SLE rows re-tagged after Pass 3 changed their source SED.

	Args:
	    commit_every: commit every N updates to keep transactions small.
	    dry_run: if truthy, count what would be updated but don't write.
	    days: process Stock Entries posted in the last N days (used only when
	          from_date is not supplied). Pass 0 for ALL entries.
	    from_date / to_date: explicit posting-date window (overrides `days`).
	          Strings 'YYYY-MM-DD'. Either or both. to_date is INCLUSIVE.
	    item_codes: list of item codes (or JSON string of one) to restrict to.
	          Useful for narrow testing — e.g. ["White Majolika"].

	Returns counts. Safe to re-run.
	"""
	commit_every = int(commit_every)
	dry_run = int(dry_run)
	days = int(days)

	from frappe.utils import add_days, nowdate

	# Normalise item_codes (allow JSON string from REST/CLI)
	if isinstance(item_codes, str):
		import json
		try:
			item_codes = json.loads(item_codes)
		except Exception:
			item_codes = [item_codes]
	item_codes = [c for c in (item_codes or []) if c]

	# Build SE / SLE date clauses
	se_clauses = []
	sle_clauses = []
	date_args = []

	if from_date or to_date:
		if from_date:
			se_clauses.append("AND se.posting_date >= %s")
			sle_clauses.append("AND sle.posting_date >= %s")
			date_args.append(from_date)
		if to_date:
			se_clauses.append("AND se.posting_date <= %s")
			sle_clauses.append("AND sle.posting_date <= %s")
			date_args.append(to_date)
	elif days > 0:
		cutoff = add_days(nowdate(), -days)
		se_clauses.append("AND se.posting_date >= %s")
		sle_clauses.append("AND sle.posting_date >= %s")
		date_args.append(cutoff)

	if item_codes:
		placeholders = ",".join(["%s"] * len(item_codes))
		se_clauses.append(f"AND sed.item_code IN ({placeholders})")
		sle_clauses.append(f"AND sle.item_code IN ({placeholders})")
		# Append item codes ONCE for SE-side queries; SLE-side queries get a
		# fresh copy passed alongside. We'll handle this by tracking both sets
		# explicitly below.

	# Helper builders — return (clause_str, args_tuple) for each query.
	def se_filter():
		parts = list(se_clauses)
		args = list(date_args)
		if item_codes:
			args.extend(item_codes)
		return " ".join(parts), tuple(args)

	def sle_filter():
		parts = list(sle_clauses)
		args = list(date_args)
		if item_codes:
			args.extend(item_codes)
		return " ".join(parts), tuple(args)

	se_date_clause, se_date_args = se_filter()
	sle_date_clause, sle_date_args = sle_filter()
	# Backwards-compat naming used in the rest of the function:
	date_args = se_date_args  # used for SE-joined queries
	sle_args = sle_date_args  # used for SLE-only queries

	# Detect which length columns exist on SED. custom_stem_length is added
	# when the Inventory Dimension is registered; until then only custom_length
	# exists. We fill whatever is present.
	sed_has_stem_length = frappe.db.has_column("Stock Entry Detail", "custom_stem_length")
	sed_has_length = frappe.db.has_column("Stock Entry Detail", "custom_length")

	# --- Pass 1: Stock Entry Detail rows -------------------------------------
	# Fill empty length on SED from parent SE header where possible. Also
	# mirror across the two SED length fields when one is set and the other
	# isn't (e.g. after a rename rollout).
	where_empty_clauses = []
	if sed_has_length:
		where_empty_clauses.append("(sed.custom_length IS NULL OR sed.custom_length = '')")
	if sed_has_stem_length:
		where_empty_clauses.append("(sed.custom_stem_length IS NULL OR sed.custom_stem_length = '')")
	where_empty = " OR ".join(where_empty_clauses) if where_empty_clauses else "1=1"

	pass1_rows = frappe.db.sql(
		f"""
		SELECT
			sed.name AS row_name,
			se.custom_stem_length AS header_length,
			{('sed.custom_length AS row_custom_length' if sed_has_length else "'' AS row_custom_length")},
			{('sed.custom_stem_length AS row_custom_stem_length' if sed_has_stem_length else "'' AS row_custom_stem_length")}
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry` se ON se.name = sed.parent
		WHERE se.docstatus = 1
		  {se_date_clause}
		  AND ({where_empty})
		  AND (
			(se.custom_stem_length IS NOT NULL AND se.custom_stem_length != '')
			{('OR (sed.custom_length IS NOT NULL AND sed.custom_length != "")' if sed_has_length else "")}
			{('OR (sed.custom_stem_length IS NOT NULL AND sed.custom_stem_length != "")' if sed_has_stem_length else "")}
		)
		""",
		date_args,
		as_dict=True,
	)

	pass1_updated = 0
	if not dry_run:
		for i, row in enumerate(pass1_rows, start=1):
			# Pick the best source: any non-empty value wins, header first then any row field.
			length = (
				(row.header_length or "").strip()
				or (row.row_custom_stem_length or "").strip()
				or (row.row_custom_length or "").strip()
			)
			if not length:
				continue
			sets = []
			args = []
			if sed_has_length and not (row.row_custom_length or "").strip():
				sets.append("custom_length = %s")
				args.append(length)
			if sed_has_stem_length and not (row.row_custom_stem_length or "").strip():
				sets.append("custom_stem_length = %s")
				args.append(length)
			if not sets:
				continue
			args.append(row.row_name)
			frappe.db.sql(
				f"UPDATE `tabStock Entry Detail` SET {', '.join(sets)} WHERE name = %s",
				tuple(args),
			)
			pass1_updated += 1
			if i % commit_every == 0:
				frappe.db.commit()
		frappe.db.commit()
	else:
		pass1_updated = len(pass1_rows)

	# --- Pass 2: Stock Ledger Entry rows -------------------------------------
	# Match SLE → originating SED via voucher_detail_no. Pull either length
	# field from SED — whichever is set.
	sed_length_expr = "COALESCE("
	parts = []
	if sed_has_stem_length:
		parts.append("NULLIF(sed.custom_stem_length, '')")
	if sed_has_length:
		parts.append("NULLIF(sed.custom_length, '')")
	if not parts:
		parts = ["NULL"]
	sed_length_expr += ", ".join(parts) + ")"

	pass2_rows = frappe.db.sql(
		f"""
		SELECT sle.name AS sle_name, {sed_length_expr} AS length
		FROM `tabStock Ledger Entry` sle
		JOIN `tabStock Entry Detail` sed
		  ON sed.name = sle.voucher_detail_no
		 AND sed.parent = sle.voucher_no
		WHERE sle.voucher_type = 'Stock Entry'
		  AND sle.is_cancelled = 0
		  {sle_date_clause}
		  AND (sle.custom_stem_length IS NULL OR sle.custom_stem_length = '')
		  AND {sed_length_expr} IS NOT NULL
		""",
		sle_args,
		as_dict=True,
	)

	pass2_updated = 0
	if not dry_run:
		for i, row in enumerate(pass2_rows, start=1):
			frappe.db.sql(
				"UPDATE `tabStock Ledger Entry` SET custom_stem_length = %s WHERE name = %s",
				(row.length, row.sle_name),
			)
			pass2_updated += 1
			if i % commit_every == 0:
				frappe.db.commit()
		frappe.db.commit()
	else:
		pass2_updated = len(pass2_rows)

	# --- Pass 3: dispatch SED rows inferred from prior Grading SED ----------
	# Untagged Material Transfer / Material Issue rows dispatching out of a
	# warehouse: copy the most recent tagged Grading SED row's length for the
	# same (item, warehouse). The Grading must have landed stock INTO the
	# dispatch's source warehouse (Grading.t_warehouse = dispatch.s_warehouse)
	# and posted on or before the dispatch's date.
	pass3_updated = pass3_unmatched = 0
	if not sed_has_length:
		# Cannot run inference without a length column on SED.
		return {
			"dry_run": bool(dry_run),
			"stock_entry_detail_updated": pass1_updated,
			"stock_ledger_entry_updated": pass2_updated,
			"dispatch_rows_inferred_from_grading": 0,
			"dispatch_rows_unmatched": 0,
		}

	pass3_candidates = frappe.db.sql(
		f"""
		SELECT
			sed.name AS dispatch_row,
			sed.item_code,
			sed.s_warehouse,
			se.posting_date,
			se.posting_time
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry` se ON se.name = sed.parent
		WHERE se.docstatus = 1
		  {se_date_clause}
		  AND se.stock_entry_type IN ('Material Transfer', 'Material Issue')
		  AND (sed.custom_length IS NULL OR sed.custom_length = '')
		  {('AND (sed.custom_stem_length IS NULL OR sed.custom_stem_length = "")' if sed_has_stem_length else "")}
		  AND sed.s_warehouse IS NOT NULL
		  AND sed.s_warehouse != ''
		""",
		date_args,
		as_dict=True,
	)

	# Look up the most-recent tagged Grading length per (item, s_warehouse, on-or-before posting date).
	# Cached so we don't re-query for the same (item, warehouse, date) tuple.
	grading_cache = {}
	for cand in pass3_candidates:
		key = (cand.item_code, cand.s_warehouse, cand.posting_date)
		if key in grading_cache:
			length = grading_cache[key]
		else:
			row = frappe.db.sql(
				"""
				SELECT sed.custom_length
				FROM `tabStock Entry Detail` sed
				JOIN `tabStock Entry` se ON se.name = sed.parent
				WHERE se.docstatus = 1
				  AND se.stock_entry_type = 'Grading'
				  AND sed.item_code = %s
				  AND sed.t_warehouse = %s
				  AND se.posting_date <= %s
				  AND sed.custom_length IS NOT NULL
				  AND sed.custom_length != ''
				ORDER BY se.posting_date DESC, se.posting_time DESC
				LIMIT 1
				""",
				(cand.item_code, cand.s_warehouse, cand.posting_date),
			)
			length = (row[0][0] if row else None)
			grading_cache[key] = length

		if not length:
			pass3_unmatched += 1
			continue

		if dry_run:
			pass3_updated += 1
			continue

		sets = ["custom_length = %s"]
		args = [length]
		if sed_has_stem_length:
			sets.append("custom_stem_length = %s")
			args.append(length)
		args.append(cand.dispatch_row)
		frappe.db.sql(
			f"UPDATE `tabStock Entry Detail` SET {', '.join(sets)} WHERE name = %s",
			tuple(args),
		)
		pass3_updated += 1
		if pass3_updated % commit_every == 0:
			frappe.db.commit()

	if not dry_run:
		frappe.db.commit()

	# --- Pass 4: redo SLE for any dispatch rows we just tagged --------------
	# Pass 2 already handled SED→SLE for header-derived tags. Now do it again
	# for the dispatch rows tagged via Pass 3, so the new length flows into SLE.
	pass4_updated = 0
	if pass3_updated > 0 and not dry_run:
		pass4_rows = frappe.db.sql(
			f"""
			SELECT sle.name AS sle_name, {sed_length_expr} AS length
			FROM `tabStock Ledger Entry` sle
			JOIN `tabStock Entry Detail` sed
			  ON sed.name = sle.voucher_detail_no
			 AND sed.parent = sle.voucher_no
			WHERE sle.voucher_type = 'Stock Entry'
			  AND sle.is_cancelled = 0
			  {sle_date_clause}
			  AND (sle.custom_stem_length IS NULL OR sle.custom_stem_length = '')
			  AND {sed_length_expr} IS NOT NULL
			""",
			sle_args,
			as_dict=True,
		)
		for i, row in enumerate(pass4_rows, start=1):
			frappe.db.sql(
				"UPDATE `tabStock Ledger Entry` SET custom_stem_length = %s WHERE name = %s",
				(row.length, row.sle_name),
			)
			pass4_updated += 1
			if i % commit_every == 0:
				frappe.db.commit()
		frappe.db.commit()

	return {
		"dry_run": bool(dry_run),
		"stock_entry_detail_updated": pass1_updated,
		"stock_ledger_entry_updated": pass2_updated,
		"dispatch_rows_inferred_from_grading": pass3_updated,
		"dispatch_rows_unmatched": pass3_unmatched,
		"sle_rows_tagged_after_inference": pass4_updated,
	}
