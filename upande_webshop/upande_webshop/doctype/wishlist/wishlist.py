# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from webshop.webshop.doctype.wishlist.wishlist import (
	add_to_wishlist as _add_to_wishlist,
	remove_from_wishlist as _remove_from_wishlist,
)


class Wishlist(Document):
	pass


@frappe.whitelist()
def add_to_wishlist(item_code):
	return _add_to_wishlist(item_code)


@frappe.whitelist()
def remove_from_wishlist(item_code):
	return _remove_from_wishlist(item_code)
