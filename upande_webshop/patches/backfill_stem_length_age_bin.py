import frappe


def execute():
	"""Backfill Stem Length Age Bin from existing Grading Stock Entries.

	Going forward the age bin is maintained incrementally by the stock-movement
	hook (update_stem_length_bin.on_stock_entry_submit/cancel). This one-off
	seeds it from history so harvest-age data is available on day one.

	Mirrors the exclusion logic the age filter previously used (scanned / sold /
	rejected / locally-transferred batches are excluded), groups by harvest date,
	and resolves the length string (e.g. '53CM') to its Stem Length doc name.
	Variant/template items are skipped — core Bin already tracks per-length qty
	for them, matching the live hook's behaviour.
	"""
	if not frappe.db.table_exists("Stem Length Age Bin"):
		return

	# The whole Grading harvest-age flow is owned by upande_tambuzi: the header
	# flags below (custom_harvest_batch_no, custom_scanned_packing, custom_sold,
	# custom_transfered_to_local, custom_rejected) and the per-row custom_length
	# are Custom Fields that only exist where that app is installed. On a site
	# without it (e.g. mona) there is nothing to backfill and the columns are
	# absent, so referencing them in SQL would hard-error — bail out cleanly.
	required_header_cols = (
		"custom_harvest_batch_no",
		"custom_scanned_packing",
		"custom_sold",
		"custom_transfered_to_local",
		"custom_rejected",
		"custom_stem_length",
	)
	if not all(frappe.db.has_column("Stock Entry", c) for c in required_header_cols):
		return

	# Stock Entry Detail.custom_length is the authoritative per-row length, but it
	# is a Custom Field that not every site has installed. Where it's missing, fall
	# back to the header field alone — mirroring the live hook's item.get() default.
	if frappe.db.has_column("Stock Entry Detail", "custom_length"):
		length_expr = "COALESCE(sed.custom_length, se.custom_stem_length)"
	else:
		length_expr = "se.custom_stem_length"

	# Aggregate net qty into each warehouse, per (item, length_str, harvest_date).
	rows = frappe.db.sql(
		f"""
		SELECT
			sed.item_code AS item_code,
			{length_expr} AS length_str,
			sed.t_warehouse AS warehouse,
			DATE(SUBSTRING_INDEX(se.custom_harvest_batch_no, '/', -1)) AS harvest_date,
			SUM(sed.transfer_qty) AS qty
		FROM `tabStock Entry` se
		INNER JOIN `tabStock Entry Detail` sed ON se.name = sed.parent
		WHERE
			se.stock_entry_type = 'Grading'
			AND se.docstatus = 1
			AND se.custom_harvest_batch_no IS NOT NULL
			AND NOT COALESCE(se.custom_scanned_packing, 0) = 1
			AND NOT COALESCE(se.custom_sold, 0) = 1
			AND NOT COALESCE(se.custom_transfered_to_local, 0) = 1
			AND NOT COALESCE(se.custom_rejected, 0) = 1
			AND sed.t_warehouse IS NOT NULL
			AND sed.t_warehouse != ''
		GROUP BY item_code, length_str, warehouse, harvest_date
		HAVING qty > 0
		""",
		as_dict=True,
	)
	if not rows:
		return

	# Resolve length strings → Stem Length doc names once.
	length_strs = list({r.length_str for r in rows if r.length_str})
	length_to_stem = {}
	if length_strs:
		for sl in frappe.db.get_all(
			"Stem Length",
			filters={"length": ("in", length_strs)},
			fields=["name", "length"],
		):
			length_to_stem[sl.length] = sl.name

	# Skip variant/template items — consistent with the live hook.
	item_codes = list({r.item_code for r in rows})
	variant_or_template = set()
	for it in frappe.db.get_all(
		"Item",
		filters={"name": ("in", item_codes)},
		fields=["name", "has_variants", "variant_of"],
	):
		if it.has_variants or it.variant_of:
			variant_or_template.add(it.name)

	created = 0
	for r in rows:
		if r.item_code in variant_or_template:
			continue
		stem_name = length_to_stem.get(r.length_str)
		if not stem_name or not r.harvest_date or not r.qty:
			continue
		# Upsert (a clean install has none; re-running merges by unique key).
		existing = frappe.db.get_value(
			"Stem Length Age Bin",
			{
				"item_code": r.item_code,
				"warehouse": r.warehouse,
				"stem_length": stem_name,
				"harvest_date": r.harvest_date,
			},
			"name",
		)
		if existing:
			frappe.db.set_value(
				"Stem Length Age Bin", existing, "actual_qty", float(r.qty),
				update_modified=False,
			)
			continue
		doc = frappe.new_doc("Stem Length Age Bin")
		doc.item_code = r.item_code
		doc.warehouse = r.warehouse
		doc.stem_length = stem_name
		doc.harvest_date = r.harvest_date
		doc.actual_qty = float(r.qty)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created += 1
		if created % 2000 == 0:
			frappe.db.commit()

	frappe.db.commit()
