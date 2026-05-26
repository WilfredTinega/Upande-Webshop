import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# Cart-level Line Code on Quotation/Sales Order parents. Rendered in the
	# cart sidebar below Box Type and mirrored to downstream documents so the
	# label survives the Quotation → Sales Order → Delivery Note → Sales Invoice
	# hand-off.
	parent_fields = [
		{
			"fieldname": "custom_line_code",
			"fieldtype": "Data",
			"label": "Line Code",
			"insert_after": "custom_box_type",
		},
	]
	fields = {dt: parent_fields for dt in [
		"Quotation",
		"Sales Order",
		"Delivery Note",
		"Sales Invoice",
	]}
	create_custom_fields(fields, ignore_validate=True)
