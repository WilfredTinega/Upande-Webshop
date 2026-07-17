import frappe
from frappe.utils import cint


def create_orders_as_quotation():
	"""True when the site is configured to keep webshop / Floriday / Biflorica
	orders as draft Quotations instead of creating Sales Orders directly.

	Read from the Webshop Settings single so every order source (cart checkout,
	Floriday import, Biflorica deals) honours the same toggle. Defaults to False
	when the field or the doctype isn't present, so behaviour is unchanged on
	sites that haven't opted in.
	"""
	try:
		return bool(cint(frappe.get_cached_doc("Webshop Settings").get("create_orders_as_quotation")))
	except Exception:
		return False
