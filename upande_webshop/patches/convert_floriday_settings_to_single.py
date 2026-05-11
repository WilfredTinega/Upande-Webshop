"""Migrate the legacy non-Single `Floriday Settings` doctype (one row of config)
into the new Single form.

Floriday Settings used to be a regular doctype with exactly one configuration
row (visible in the list view as e.g. `ep89o0jsr5`). The doctype JSON is now
`issingle: 1`. Frappe stores Single values in `tabSingles` keyed by
(doctype, field), and there is no `tabFloriday Settings` table for a Single.
Running `bench migrate` after the JSON flip leaves the legacy row stranded —
its values disappear from the UI even though the row still exists on disk.

This patch:
  1. Reads the surviving row from `tabFloriday Settings` (if the table still
     exists), preferring the most recently modified row if there are several.
  2. Copies every value whose field is present on the current (Single) doctype
     into `tabSingles`.
  3. Reparents child-table rows (`Floriday Stock View` under `stock_items` /
     `table_wtkz`) onto the Single's well-known parent name (`Floriday Settings`).
  4. Drops the legacy `tabFloriday Settings` table so future migrations don't
     re-trip this.

Safe to re-run: if there is no legacy table, or it is empty, the patch no-ops.
"""

import frappe


DOCTYPE = "Floriday Settings"

# (parentfield on Floriday Settings, child doctype name)
CHILD_TABLES = [
	("stock_items", "Floriday Stock View"),
	("table_wtkz", "Floriday Stock View"),
]


def execute():
	table = f"tab{DOCTYPE}"

	if not _table_exists(table):
		# Already cleaned up, or never installed on this site.
		return

	if not frappe.db.get_value("DocType", DOCTYPE, "issingle"):
		# The JSON change hasn't reached this site yet — skip rather than corrupt.
		print(f"[{DOCTYPE}] not yet Single in DocType meta; skipping migration")
		return

	row = _read_legacy_row(table)
	if not row:
		_drop_legacy_table(table)
		return

	current_fields = _scalar_field_names(DOCTYPE)
	values = {k: v for k, v in row.items() if k in current_fields and v not in (None, "")}

	if values:
		# Wipe any partial Singles state for this doctype before writing, so a
		# re-run of the patch lands on a clean slate.
		frappe.db.delete("Singles", {"doctype": DOCTYPE})
		for fieldname, value in values.items():
			frappe.db.sql(
				"INSERT INTO `tabSingles` (`doctype`, `field`, `value`) VALUES (%s, %s, %s)",
				(DOCTYPE, fieldname, value),
			)
		print(f"[{DOCTYPE}] migrated {len(values)} field(s) from {row.get('name')!r}")

	# Singles parent name is the doctype name itself. Reparent child rows that
	# used to point at the legacy parent (`row.name`) onto the Single's parent.
	legacy_parent = row.get("name")
	if legacy_parent and legacy_parent != DOCTYPE:
		for parentfield, child_doctype in CHILD_TABLES:
			child_table = f"tab{child_doctype}"
			if not _table_exists(child_table):
				continue
			frappe.db.sql(
				f"UPDATE `{child_table}` SET parent = %s "
				f"WHERE parent = %s AND parentfield = %s AND parenttype = %s",
				(DOCTYPE, legacy_parent, parentfield, DOCTYPE),
			)

	frappe.db.commit()
	_drop_legacy_table(table)

	# Drop the cached doc so the next reader rebuilds from Singles.
	frappe.clear_document_cache(DOCTYPE, DOCTYPE)


def _table_exists(table):
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.tables "
			"WHERE table_schema = DATABASE() AND table_name = %s",
			(table,),
		)
	)


def _read_legacy_row(table):
	# One row of config by design; if there is more than one, prefer the most
	# recently modified so the patch picks up the live values. Fall back to
	# `creation` then natural order if `modified` is missing on very old schemas.
	for order_col in ("modified", "creation", "name"):
		try:
			rows = frappe.db.sql(
				f"SELECT * FROM `{table}` ORDER BY `{order_col}` DESC LIMIT 1",
				as_dict=True,
			)
			return rows[0] if rows else None
		except Exception:
			continue
	return None


def _scalar_field_names(doctype):
	"""Names of fields on the current (Single) doctype that live in tabSingles.

	Excludes Table / Table MultiSelect (their data lives in the child table) and
	layout-only fields (Section/Column/Tab Break, Button, HTML, etc.).
	"""
	meta = frappe.get_meta(doctype)
	skip_types = {
		"Table",
		"Table MultiSelect",
		"Section Break",
		"Column Break",
		"Tab Break",
		"Button",
		"HTML",
		"Heading",
		"Image",
		"Fold",
	}
	return {df.fieldname for df in meta.fields if df.fieldtype not in skip_types}


def _drop_legacy_table(table):
	try:
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{table}`")
	except Exception as e:
		print(f"Could not drop legacy table {table}: {e}")
