import frappe
from frappe import _

from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
	apply_webshop_setup_guard,
)

sitemap = 1


def get_context(context):
	if apply_webshop_setup_guard(context):
		return

	# Check the setting before the Guest gate: when disabled the storefront is
	# /webshop, so send everyone (incl. Guests) there directly — no login detour.
	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.get("show_product_overview"):
		# Product Overview disabled → the storefront is /webshop; redirect there
		# rather than 404 (mirrors /webshop redirecting here when it's enabled).
		frappe.local.flags.redirect_location = "/webshop"
		raise frappe.Redirect

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/product-overview"
		raise frappe.Redirect

	context.body_class = "product-page product-overview-page"
	context.parents = []
	context.show_sidebar = 0
	context.no_breadcrumbs = 1
	context.no_cache = 1

	from upande_webshop.upande_webshop.api import _product_overview_warehouses

	from frappe.utils import cint

	word_limit = cint(settings.get("po_warehouse_display_words"))

	def _label(wh_name):
		if word_limit > 0:
			return " ".join((wh_name or "").split()[:word_limit]) or wh_name
		return wh_name

	context.display_warehouses = [
		{"label": _label(wh), "name": wh}
		for wh in _product_overview_warehouses(settings)
	]

	view = (settings.get("po_default_view") or "Grid").lower()
	context.po_default_view = "list" if view == "list" else "grid"
