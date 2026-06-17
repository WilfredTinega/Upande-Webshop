"""Clear the description on the Webshop Settings "Enable Variant Selector"
(`enable_variants`) Custom Field.

The field shipped with a long helper description ("Render the variant selector
…") that's no longer wanted under the checkbox. The field is a Custom Field on
sites where it's already installed, so we blank its `description` in place rather
than editing any JSON. Idempotent: a no-op once the description is already empty
or the field is absent.
"""

import frappe


def execute():
	name = frappe.db.get_value(
		"Custom Field",
		{"dt": "Webshop Settings", "fieldname": "enable_variants"},
		"name",
	)
	if not name:
		return

	if not frappe.db.get_value("Custom Field", name, "description"):
		return

	frappe.db.set_value("Custom Field", name, "description", "")
	frappe.clear_cache(doctype="Webshop Settings")
