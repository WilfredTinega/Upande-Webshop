import frappe
from frappe.utils import cint

from upande_webshop.upande_webshop.product_data_engine.filters import ProductFiltersBuilder

sitemap = 1


def get_context(context):
	# Add homepage as parent
	context.body_class = "product-page"
	context.parents = [{"name": frappe._("Home"), "route": "/webshop"}]

	filter_engine = ProductFiltersBuilder()
	context.field_filters = filter_engine.get_field_filters()
	context.attribute_filters = filter_engine.get_attribute_filters()

	context.page_length = (
		cint(frappe.db.get_single_value("Webshop Settings", "products_per_page")) or 20
	)

	meta = frappe.get_meta("Webshop Settings")
	if meta.has_field("full_width"):
		context.full_width = cint(
			frappe.db.get_single_value("Webshop Settings", "full_width")
		)

	context.no_cache = 1
