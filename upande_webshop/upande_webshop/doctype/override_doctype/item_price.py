import frappe
from frappe import _
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Cast_

from erpnext.stock.doctype.item_price.item_price import ItemPrice, ItemPriceDuplicateItem


class WebshopItemPrice(ItemPrice):
	"""Extends ERPNext's duplicate check so that Item Price rows differing only
	in `custom_length` are treated as distinct. This is what lets non-variant
	rose items hold one Item Price row per stem length on the same price list.
	"""

	def check_duplicates(self):
		item_price = frappe.qb.DocType("Item Price")

		query = (
			frappe.qb.from_(item_price)
			.select(item_price.price_list_rate)
			.where(
				(item_price.item_code == self.item_code)
				& (item_price.price_list == self.price_list)
				& (item_price.name != self.name)
			)
		)

		data_fields = (
			"uom",
			"valid_from",
			"valid_upto",
			"customer",
			"supplier",
			"batch_no",
		)
		number_fields = ("packing_unit",)
		# Treat custom_length as part of the uniqueness key when the column exists.
		if frappe.db.has_column("Item Price", "custom_length"):
			data_fields = data_fields + ("custom_length",)

		for field in data_fields:
			if self.get(field):
				query = query.where(item_price[field] == self.get(field))
			else:
				query = query.where(
					Criterion.any(
						[
							item_price[field].isnull(),
							Cast_(item_price[field], "varchar") == "",
						]
					)
				)

		for field in number_fields:
			if self.get(field):
				query = query.where(item_price[field] == self.get(field))
			else:
				query = query.where(
					Criterion.any(
						[
							item_price[field].isnull(),
							item_price[field] == 0,
						]
					)
				)

		if query.run(as_dict=True):
			frappe.throw(
				_(
					"Item Price appears multiple times based on Price List, "
					"Supplier/Customer, Currency, Item, Batch, UOM, Qty, "
					"Stem Length, and Dates."
				),
				ItemPriceDuplicateItem,
			)
