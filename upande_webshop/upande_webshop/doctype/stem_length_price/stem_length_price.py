# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class StemLengthPrice(Document):
	def refresh_rate(self, price_list=None):
		if not (self.parent and self.stem_length):
			return False

		item_code = frappe.db.get_value("Floriday Items", self.parent, "item_code")
		if not item_code:
			return False

		filters = {"item_code": item_code, "custom_length": self.stem_length}
		if price_list:
			filters["price_list"] = price_list

		row = frappe.db.get_value("Item Price", filters, "price_list_rate")
		if row is None:
			return False

		self.rate = row
		return True

	def refresh_trade_item_id(self, article_lookup, item_name=None):
		from upande_webshop.upande_webshop.doctype.floriday_items.floriday_items import (
			_normalize_name,
			_floriday_length_for,
		)

		if not self.stem_length:
			return False

		if not item_name and self.parent:
			item_name = frappe.db.get_value("Floriday Items", self.parent, "item_name")
		if not item_name:
			return False

		name_norm = _normalize_name(item_name)
		floriday_length = _floriday_length_for(self.stem_length)
		if not name_norm or floriday_length is None:
			return False

		trade_item_id = article_lookup.get((name_norm, floriday_length))
		if not trade_item_id:
			return False

		self.trade_item_id = trade_item_id
		return True


@frappe.whitelist(allow_guest=True)
def get_item_length_price(item_code, length, currency, price_list):
	if not (item_code and length and currency and price_list):
		return None

	price_records = frappe.db.get_all(
		"Item Price",
		filters={
			"item_code": item_code,
			"price_list": price_list,
			"currency": currency,
			"custom_length": length,
		},
		fields=["price_list_rate"],
		limit=1,
	)

	if price_records:
		return {"price_list_rate": flt(price_records[0].price_list_rate)}

	return None
