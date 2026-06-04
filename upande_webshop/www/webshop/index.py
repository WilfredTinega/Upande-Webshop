import frappe
from frappe.utils import cint

from upande_webshop.upande_webshop.product_data_engine.filters import ProductFiltersBuilder
from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
	apply_webshop_setup_guard,
)

sitemap = 1


def get_context(context):
	# If required custom fields are missing, show a friendly setup page instead
	# of letting the storefront error out.
	if apply_webshop_setup_guard(context):
		return

	# When Product Overview is the active storefront, /webshop redirects to it.
	# (Product Overview's own page redirects back here when the setting is off,
	# so exactly one of the two pages is ever live.)
	if frappe.get_cached_value("Webshop Settings", "Webshop Settings", "show_product_overview"):
		frappe.local.flags.redirect_location = "/product-overview"
		raise frappe.Redirect

	# Add homepage as parent
	context.body_class = "product-page"
	context.parents = [{"name": frappe._("Home"), "route": "/webshop"}]

	filter_engine = ProductFiltersBuilder()
	context.field_filters = filter_engine.get_field_filters()
	context.attribute_filters = filter_engine.get_attribute_filters()

	context.page_length = (
		cint(frappe.db.get_single_value("Webshop Settings", "products_per_page")) or 20
	)

	context.no_cache = 1
