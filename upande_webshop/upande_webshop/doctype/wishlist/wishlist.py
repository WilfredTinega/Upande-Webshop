# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Wishlist(Document):
	pass


@frappe.whitelist()
def add_to_wishlist(item_code):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please login to add items to wishlist"))

	wishlist_name = frappe.db.get_value("Wishlist", {"user": frappe.session.user}, "name")

	if not wishlist_name:
		wishlist = frappe.get_doc({
			"doctype": "Wishlist",
			"user": frappe.session.user,
			"items": []
		})
		wishlist.insert(ignore_permissions=True)
		wishlist_name = wishlist.name
	else:
		wishlist = frappe.get_doc("Wishlist", wishlist_name)

	already_wished = any(d.item_code == item_code for d in wishlist.get("items", []))
	if already_wished:
		return

	web_item = frappe.db.get_value(
		"Website Item",
		{"item_code": item_code},
		["name", "web_item_name", "website_image", "route", "item_group"],
		as_dict=True
	)

	wishlist.append("items", {
		"item_code": item_code,
		"website_item": web_item.name if web_item else None,
		"web_item_name": web_item.web_item_name if web_item else item_code,
		"item_name": web_item.web_item_name if web_item else item_code,
		"item_group": web_item.item_group if web_item else None,
		"image": web_item.website_image if web_item else None,
		"route": web_item.route if web_item else None,
	})

	wishlist.save(ignore_permissions=True)
	_set_wish_count_cookie()


@frappe.whitelist()
def remove_from_wishlist(item_code):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please login"))

	wishlist_name = frappe.db.get_value("Wishlist", {"user": frappe.session.user}, "name")
	if not wishlist_name:
		return

	wishlist = frappe.get_doc("Wishlist", wishlist_name)
	items = [d for d in wishlist.get("items", []) if d.item_code != item_code]
	wishlist.set("items", items)
	wishlist.save(ignore_permissions=True)
	_set_wish_count_cookie()


def _set_wish_count_cookie():
	wishlist_name = frappe.db.get_value("Wishlist", {"user": frappe.session.user}, "name")
	count = 0
	if wishlist_name:
		count = frappe.db.count("Wishlist Item", {"parent": wishlist_name})
	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.set_cookie("wish_count", str(count))
