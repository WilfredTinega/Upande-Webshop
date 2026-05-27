# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Wishlist(Document):
	pass


def _check_wishlist_enabled():
	if not frappe.db.get_single_value("Webshop Settings", "enable_wishlist"):
		frappe.throw(_("Wishlist is disabled"), frappe.PermissionError)


def _set_wish_count_cookie(user=None):
	user = user or frappe.session.user
	count = frappe.db.count("Wishlist Item", filters={"parent": user})
	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.set_cookie("wish_count", str(count))
	return count


@frappe.whitelist()
def add_to_wishlist(item_code):
	"""Insert Item into wishlist."""
	_check_wishlist_enabled()

	if frappe.db.exists("Wishlist Item", {"item_code": item_code, "parent": frappe.session.user}):
		# Already wished — still refresh the cookie so the UI count is accurate.
		return {"wish_count": _set_wish_count_cookie()}

	web_item_data = frappe.db.get_value(
		"Website Item",
		{"item_code": item_code},
		[
			"website_image",
			"website_warehouse",
			"name",
			"web_item_name",
			"item_name",
			"item_group",
			"route",
		],
		as_dict=1,
	)

	wished_item_dict = {
		"item_code": item_code,
		"item_name": web_item_data.get("item_name"),
		"item_group": web_item_data.get("item_group"),
		"website_item": web_item_data.get("name"),
		"web_item_name": web_item_data.get("web_item_name"),
		"image": web_item_data.get("website_image"),
		"warehouse": web_item_data.get("website_warehouse"),
		"route": web_item_data.get("route"),
	}

	if not frappe.db.exists("Wishlist", frappe.session.user):
		# initialise wishlist
		wishlist = frappe.get_doc({"doctype": "Wishlist"})
		wishlist.user = frappe.session.user
		wishlist.append("items", wished_item_dict)
		wishlist.save(ignore_permissions=True)
	else:
		wishlist = frappe.get_doc("Wishlist", frappe.session.user)
		item = wishlist.append("items", wished_item_dict)
		item.db_insert()

	return {"wish_count": _set_wish_count_cookie()}


@frappe.whitelist()
def remove_from_wishlist(item_code):
	_check_wishlist_enabled()
	if frappe.db.exists("Wishlist Item", {"item_code": item_code, "parent": frappe.session.user}):
		frappe.db.delete("Wishlist Item", {"item_code": item_code, "parent": frappe.session.user})
		frappe.db.commit()  # nosemgrep

	return {"wish_count": _set_wish_count_cookie()}
