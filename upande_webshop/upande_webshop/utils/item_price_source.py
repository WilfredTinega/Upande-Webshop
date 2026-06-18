"""Direct Item-Price price fetching for the webshop.

The storefront/cart normally resolves a price through a Price List (ERPNext's
`erpnext.utilities.product.get_price`). On the rose sites we instead want the
rate to come straight from the **Item Price** doctype, keyed by:

  - variant items     -> the variant `item_code` alone (the variant code already
                         encodes the stem length, so there is no custom_length to
                         match on — see the variant add-to-cart flow).
  - non-variant items -> `item_code` + `custom_length` (one Item Price row per
                         stem length on the same item).

`get_price()` here is a drop-in wrapper around ERPNext's `get_price`: it tries
the direct Item Price lookup first and, only if nothing matches, falls back to
the original Price-List resolution so non-rose items keep working.
"""

import frappe
from frappe.utils import flt

from erpnext.utilities.product import get_price as _erpnext_get_price


def _item_is_variant(item_code):
	"""True when the Item is a variant (has a template via variant_of)."""
	return bool(frappe.db.get_value("Item", item_code, "variant_of"))


def get_item_price_row(item_code, custom_length=None):
	"""Return the matching Item Price row dict, or None.

	Variant items match on item_code only. Non-variant items match on
	item_code + custom_length when the column exists and a length is supplied;
	if no length is given they match on item_code alone. Only selling rows are
	considered; the most recent by valid_from wins.
	"""
	filters = {"item_code": item_code, "selling": 1}

	if not _item_is_variant(item_code):
		# Non-variant: scope to the stem length when we have one and the
		# column is present (custom_length is a Custom Field, not on every site).
		if custom_length and frappe.db.has_column("Item Price", "custom_length"):
			filters["custom_length"] = custom_length

	rows = frappe.db.get_all(
		"Item Price",
		filters=filters,
		fields=["name", "price_list_rate", "currency", "price_list", "valid_from"],
		order_by="valid_from desc, modified desc",
		limit=1,
	)
	return rows[0] if rows else None


def _format_price_dict(item_code, rate, currency):
	"""Shape a price dict the way ERPNext's get_price does, so the webshop's
	display/formatting code reads the same keys without seeing "undefined".

	Mirrors erpnext.utilities.product.get_price: formatted_price (per stock UOM),
	formatted_price_sales_uom (per sales UOM via the item's conversion factor),
	currency_symbol, formatted_mrp.
	"""
	from frappe.utils import cint, fmt_money

	rate = flt(rate)

	currency_symbol = ""
	if not cint(frappe.db.get_default("hide_currency_symbol")):
		currency_symbol = (
			frappe.db.get_value("Currency", currency, "symbol", cache=True) or currency
			if currency
			else ""
		)

	# Per-sales-UOM price: rate × (sales_uom conversion factor), as ERPNext does.
	uom_rows = frappe.db.sql(
		"""select C.conversion_factor
		from `tabUOM Conversion Detail` C
		inner join `tabItem` I on C.parent = I.name and C.uom = I.sales_uom
		where I.name = %s""",
		item_code,
	)
	conversion_factor = uom_rows[0][0] if uom_rows else 1

	return frappe._dict({
		"price_list_rate": rate,
		"currency": currency,
		"currency_symbol": currency_symbol,
		"formatted_price": fmt_money(rate, currency=currency),
		"formatted_price_sales_uom": fmt_money(rate * conversion_factor, currency=currency),
		"formatted_mrp": None,
	})


def get_price(item_code, price_list, customer_group, company, qty=1, party=None):
	"""Webshop price resolver: Item Price first, Price List as fallback.

	Signature matches erpnext.utilities.product.get_price so this is a drop-in
	replacement at the webshop call sites. `price_list`/`customer_group`/
	`company`/`qty`/`party` are only used for the fallback path.
	"""
	# custom_length isn't available at the listing/detail call sites (the bare
	# item is priced there); the length-specific reprice happens in the cart via
	# _apply_length_price_db. So here we resolve per item_code (and, for
	# non-variants with no length, the item's default Item Price row).
	row = get_item_price_row(item_code)
	if row and row.price_list_rate is not None:
		return _format_price_dict(item_code, row.price_list_rate, row.currency)

	# Nothing in Item Price for this item — fall back to Price List resolution.
	return _erpnext_get_price(item_code, price_list, customer_group, company, qty=qty, party=party)
