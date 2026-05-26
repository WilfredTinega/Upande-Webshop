import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Stem Length"):
		return

	# These fields' visibility/required eval references Quotation.custom_business_unit.
	# Sites without that driver field can't meaningfully use these fields, so we don't
	# create them — keeps mona / tambuzi free of unused hidden columns.
	if not frappe.db.get_value(
		"Custom Field", {"dt": "Quotation", "fieldname": "custom_business_unit"}, "name"
	):
		return

	fields = {
		"Quotation Item": [
			{
				"fieldname": "custom_length",
				"fieldtype": "Link",
				"label": "Length",
				"options": "Stem Length",
				"insert_after": "stock_uom",
				"depends_on": "eval: parent.custom_business_unit == \"Roses\"",
				"mandatory_depends_on": "eval: parent.custom_business_unit == \"Roses\"",
			},
			{
				"fieldname": "custom_total_stems",
				"fieldtype": "Float",
				"label": "Total Stems",
				"insert_after": "custom_length",
				"read_only": 1,
			},
		],
	}
	create_custom_fields(fields, ignore_validate=True)
