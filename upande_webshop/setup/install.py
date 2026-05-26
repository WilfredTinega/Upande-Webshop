import frappe
import click

from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
	add_custom_fields()
	navbar_add_products_link()
	say_thanks()


def _has_quotation_business_unit():
	"""The Quotation Item length fields depend on `Quotation.custom_business_unit == "Roses"`.
	On sites that don't have that driver field (e.g. mona, tambuzi) the eval is
	always falsy, so creating these fields would just leak hidden columns that
	core code might still try to populate. Skip them when the driver is absent.
	"""
	return bool(
		frappe.db.get_value(
			"Custom Field", {"dt": "Quotation", "fieldname": "custom_business_unit"}, "name"
		)
	)


def add_custom_fields():
	custom_fields = {
		"Quotation": [
			{
				"fieldname": "custom_delivery_point",
				"fieldtype": "Link",
				"label": "Delivery Point",
				"options": "Delivery Points",
				"insert_after": "shipping_address_name",
			},
		],
		"Item Price": [
			{
				"fieldname": "custom_length",
				"fieldtype": "Link",
				"label": "Stem Length",
				"options": "Stem Length",
				"insert_after": "item_name",
				"description": "Set for non-variant rose items priced per stem length. Variants leave this blank.",
			},
		],
		"Item": [
			{
				"default": 0,
				"depends_on": "published_in_website",
				"fieldname": "published_in_website",
				"fieldtype": "Check",
				"ignore_user_permissions": 1,
				"insert_after": "default_manufacturer_part_no",
				"label": "Published In Website",
				"read_only": 1,
				"no_copy": 1,
			}
		],
		"Item Group": [
			{
				"fieldname": "custom_website_settings",
				"fieldtype": "Section Break",
				"label": "Website Settings",
				"insert_after": "taxes",
			},
			{
				"default": "0",
				"description": "Make Item Group visible in website",
				"fieldname": "show_in_website",
				"fieldtype": "Check",
				"label": "Show in Website",
				"insert_after": "custom_website_settings",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "route",
				"fieldtype": "Data",
				"label": "Route",
				"no_copy": 1,
				"unique": 1,
				"insert_after": "show_in_website",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "website_title",
				"fieldtype": "Data",
				"label": "Title",
				"insert_after": "route",
			},
			{
				"depends_on": "show_in_website",
				"description": "HTML / Banner that will show on the top of product list.",
				"fieldname": "description",
				"fieldtype": "Text Editor",
				"label": "Description",
				"insert_after": "website_title",
			},
			{
				"default": "0",
				"depends_on": "show_in_website",
				"description": "Include Website Items belonging to child Item Groups",
				"fieldname": "include_descendants",
				"fieldtype": "Check",
				"label": "Include Descendants",
				"insert_after": "website_title",
			},
			{
				"fieldname": "column_break_16",
				"fieldtype": "Column Break",
				"insert_after": "include_descendants",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "weightage",
				"fieldtype": "Int",
				"label": "Weightage",
				"insert_after": "column_break_16",
			},
			{
				"depends_on": "show_in_website",
				"description": "Show this slideshow at the top of the page",
				"fieldname": "slideshow",
				"fieldtype": "Link",
				"label": "Slideshow",
				"options": "Website Slideshow",
				"insert_after": "weightage",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "website_specifications",
				"fieldtype": "Table",
				"label": "Website Specifications",
				"options": "Item Website Specification",
				"insert_after": "description",
			},
			{
				"collapsible": 1,
				"depends_on": "show_in_website",
				"fieldname": "website_filters_section",
				"fieldtype": "Section Break",
				"label": "Website Filters",
				"insert_after": "website_specifications",
			},
			{
				"fieldname": "filter_fields",
				"fieldtype": "Table",
				"label": "Item Fields",
				"options": "Website Filter Field",
				"insert_after": "website_filters_section",
			},
			{
				"fieldname": "filter_attributes",
				"fieldtype": "Table",
				"label": "Attributes",
				"options": "Website Attribute",
				"insert_after": "filter_fields",
			},
		],
	}

	if _has_quotation_business_unit():
		custom_fields["Quotation Item"] = [
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
		]

	frappe.make_property_setter(
		{
			"doctype": "Item Group",
			"doctype_or_field": "DocType",
			"fieldname": "allow_guest_to_view",
			"property": "allow_guest_to_view",
			"value": 1,
			"property_type": "Check"
		},
		is_system_generated=True,
	)

	return create_custom_fields(custom_fields)


def navbar_add_products_link():
	website_settings = frappe.get_doc("Website Settings")
	if website_settings.top_bar_items:
		return

	website_settings.append(
		"top_bar_items",
		{
			"label": _("Products"),
			"url": "/all-products",
			"right": False,
		},
	)

	website_settings.save()


def say_thanks():
	click.secho("Thank you for installing Upande Webshop!", color="green")
