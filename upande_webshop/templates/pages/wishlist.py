# Copyright (c) 2026, Upande LTD and contributors
# License: GNU General Public License v3. See license.txt
import frappe

from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
    get_shopping_cart_settings,
)
from upande_webshop.upande_webshop.shopping_cart.cart import _set_price_list
from erpnext.utilities.product import get_price
from upande_webshop.upande_webshop.shopping_cart.cart import get_party


def get_context(context):
	is_guest = frappe.session.user == "Guest"

	settings = get_shopping_cart_settings()

	if not settings.enable_wishlist:
		frappe.local.flags.redirect_location = "/webshop"
		raise frappe.Redirect

	items = get_wishlist_items() if not is_guest else []
	selling_price_list = _set_price_list(settings) if not is_guest else None

	items = set_stock_price_details(items, settings, selling_price_list)
	items = set_default_stem_bunch(items)
	items = set_variant_flag(items)

	context.body_class = "product-page"
	context.items = items
	context.settings = settings
	# The inline variant selector markup keys off `shopping_cart.cart_settings`
	# exactly like the product detail page, so reuse the same shape here.
	context.shopping_cart = frappe._dict({"cart_settings": settings})
	context.no_cache = 1


def get_stock_availability(item_code, warehouse):
	"""Whether `item_code` has any stock for the storefront.

	Mirrors the product listing/detail logic in
	`upande_webshop.product_data_engine.query`: plain items read summed
	`Stem Length Bin` qty, templates aggregate their variants' `Bin` qty, and
	variants read `Bin` directly — all across the configured storefront
	warehouse set rather than a single `website_warehouse`. Reading only the
	per-item Bin here previously flagged in-stock plain items as out of stock.
	"""
	from upande_webshop.upande_webshop.product_data_engine.query import (
		get_item_total_qty,
		get_variants_total_qty,
	)

	if frappe.get_cached_value("Item", item_code, "has_variants"):
		stock_qty = get_variants_total_qty(item_code, warehouse)
	else:
		stock_qty = get_item_total_qty(item_code, warehouse)

	return frappe.utils.flt(stock_qty) > 0


def get_wishlist_items():
	if not frappe.db.exists("Wishlist", frappe.session.user):
		return []

	return frappe.db.get_all(
		"Wishlist Item",
		filters={"parent": frappe.session.user},
		fields=[
			"web_item_name",
			"item_code",
			"item_name",
			"website_item",
			"warehouse",
			"image",
			"item_group",
			"route",
		],
	)


def set_stock_price_details(items, settings, selling_price_list):
	for item in items:
		if settings.show_stock_availability:
			item.available = get_stock_availability(
				item.item_code, item.get("warehouse")
			)

		party = get_party()

		price_details = get_price(
			item.item_code,
			selling_price_list,
			settings.default_customer_group,
			settings.company,
			party=party,
		)

		if price_details:
			item.formatted_price = price_details.get("formatted_price")
			item.formatted_mrp = price_details.get("formatted_mrp")
			if item.formatted_mrp:
				item.discount = price_details.get(
					"formatted_discount_percent"
				) or price_details.get("formatted_discount_rate")

	return items


def set_variant_flag(items):
	"""Mark wished items that are variant templates.

	Templates can't be added to cart directly — the user must pick a length
	first — so the card renders the same inline variant selector the product
	detail page uses instead of a plain "Add to Quote" button.
	"""
	for item in items:
		item.has_variants = bool(
			frappe.get_cached_value("Item", item.item_code, "has_variants")
		)
	return items


def set_default_stem_bunch(items):
	# Fetch first stem length
	stem_lengths = frappe.get_all("Stem Length", fields=["length"], order_by="length asc", limit=1)
	default_length = stem_lengths[0].length if stem_lengths else ""

	# Fetch first bunch UOM
	all_uoms = frappe.get_all("UOM", fields=["name"], filters={"enabled": 1}, order_by="name asc")
	default_bunch = ""
	for uom in all_uoms:
		if "bunch" in uom.name.lower():
			default_bunch = uom.name
			break

	for item in items:
		item.default_length = default_length
		item.default_bunch = default_bunch

	return items
