import frappe
from frappe.utils import flt


@frappe.whitelist(allow_guest=True)
def get_item_length_price(item_code, length, currency, price_list):
	"""
	Guest-accessible endpoint to fetch per-bunch price for a flower item
	filtered by stem length (custom_length field on Item Price).
	Returns: { price_list_rate: <bunch_price> }
	"""
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
