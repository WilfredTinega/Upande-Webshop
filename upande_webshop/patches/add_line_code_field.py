import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# Per-row Line Code on the cart's child Items. Superseded by the
	# cart-level Line Code field — see add_cart_line_code_parent_field.
	# Kept as a no-op so already-applied patch entries stay consistent.
	common_fields = [
		{
			"fieldname": "custom_line_code",
			"fieldtype": "Data",
			"label": "Line Code",
			"insert_after": "custom_box_type",
		},
	]
	fields = {dt: common_fields for dt in [
		"Quotation Item",
		"Sales Order Item",
		"Delivery Note Item",
		"Sales Invoice Item",
	]}
	create_custom_fields(fields, ignore_validate=True)
