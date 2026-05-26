"""
Carry the legacy single `tabWebshop Settings.warehouse` value into the new
`Webshop Warehouse` child table.

Pre-model-sync patch: runs before DocType meta is re-synced from the JSON, so
the old `warehouse` column still exists on `tabWebshop Settings` when this
reads it. After this completes, the column is dropped by model sync because
the field no longer appears in webshop_settings.json.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Webshop Settings"):
		return

	if not frappe.db.table_exists("Webshop Settings"):
		return

	columns = frappe.db.sql(
		"SHOW COLUMNS FROM `tabWebshop Settings` LIKE 'warehouse'", as_dict=True
	)
	if not columns:
		return

	row = frappe.db.sql(
		"SELECT warehouse FROM `tabWebshop Settings` WHERE name = 'Webshop Settings'",
		as_dict=True,
	)
	old_warehouse = row[0].warehouse if row else None
	if not old_warehouse:
		return

	if not frappe.db.exists("Warehouse", old_warehouse):
		return

	existing = frappe.db.exists(
		"Webshop Warehouse",
		{
			"parent": "Webshop Settings",
			"parenttype": "Webshop Settings",
			"parentfield": "warehouses",
			"warehouse": old_warehouse,
		},
	)
	if existing:
		return

	settings = frappe.get_doc("Webshop Settings", "Webshop Settings")
	settings.append("warehouses", {"warehouse": old_warehouse})
	settings.flags.ignore_validate = True
	settings.flags.ignore_permissions = True
	settings.save()
