import frappe
from upande_webshop.upande_webshop.product_data_engine.filters import ProductFiltersBuilder


@frappe.whitelist()
def get_webshop_filters():
	"""
	Return field and attribute filter options for the Upande Webshop desk page.
	Mirrors what the webshop website renders server-side in its Jinja templates.
	"""
	builder = ProductFiltersBuilder()

	field_filters_raw = builder.get_field_filters() or []
	attribute_filters_raw = builder.get_attribute_filters() or []

	# Serialize field filters: list of {label, fieldname, values}
	field_filters = []
	for df, values in field_filters_raw:
		field_filters.append({
			"fieldname": df.fieldname,
			"label": df.label or df.fieldname,
			"values": values,
		})

	# Serialize attribute filters: list of {name, item_attribute_values}
	attribute_filters = []
	for attr in attribute_filters_raw:
		attribute_filters.append({
			"attribute": attr.name,
			"values": attr.item_attribute_values,
		})

	return {
		"field_filters": field_filters,
		"attribute_filters": attribute_filters,
	}
