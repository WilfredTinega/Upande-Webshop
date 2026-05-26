import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# Mirror the stem-length / box-type fields on Sales Order Item and the
	# delivery-side child tables so the cart's per-combo selections (length,
	# box type, total stems) survive the Quotation → Sales Order → Delivery
	# Note → Sales Invoice handoff.
	#
	# Sites without Quotation.custom_business_unit aren't running the rose-length
	# flow that needs these fields (mona, tambuzi). Skip the mirror so we don't
	# leak unused columns.
	if not frappe.db.get_value(
		"Custom Field", {"dt": "Quotation", "fieldname": "custom_business_unit"}, "name"
	):
		return

	box_type_opts = "Box Type" if frappe.db.exists("DocType", "Box Type") else None
	stem_length_opts = "Stem Length" if frappe.db.exists("DocType", "Stem Length") else None

	common_fields = []
	if stem_length_opts:
		common_fields.append({
			"fieldname": "custom_length",
			"fieldtype": "Link",
			"label": "Length",
			"options": stem_length_opts,
			"insert_after": "stock_uom",
		})
	if box_type_opts:
		common_fields.append({
			"fieldname": "custom_box_type",
			"fieldtype": "Link",
			"label": "Box Type",
			"options": box_type_opts,
			"insert_after": "custom_length" if stem_length_opts else "stock_uom",
		})
	common_fields.append({
		"fieldname": "custom_total_stems",
		"fieldtype": "Float",
		"label": "Total Stems",
		"insert_after": "custom_box_type" if box_type_opts else (
			"custom_length" if stem_length_opts else "stock_uom"
		),
		"read_only": 1,
	})

	fields = {dt: common_fields for dt in [
		"Quotation Item",
		"Sales Order Item",
		"Delivery Note Item",
		"Sales Invoice Item",
	]}
	create_custom_fields(fields, ignore_validate=True)
