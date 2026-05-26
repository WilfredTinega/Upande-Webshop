import frappe
import frappe.defaults
from frappe import _, throw
from frappe.contacts.doctype.address.address import get_address_display
from frappe.contacts.doctype.contact.contact import get_contact_name
from frappe.utils import add_days, cint, cstr, flt, get_fullname, getdate, nowdate
from frappe.utils.nestedset import get_root_of

from erpnext.accounts.utils import get_account_name
from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
    get_shopping_cart_settings,
)
from upande_webshop.upande_webshop.utils.product import get_web_item_qty_in_stock
from erpnext.selling.doctype.quotation.quotation import _make_sales_order


class WebsitePriceListMissingError(frappe.ValidationError):
    pass


def _cart_doctype():
	"""Return the doctype currently configured as the cart container.

	`enable_checkout` (payment-gateway flow) takes precedence and always uses
	Quotation, because the gateway path converts Quotation→Sales Order itself.
	"""
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	if cint(cart_settings.enable_checkout):
		return "Quotation"
	if cint(getattr(cart_settings, "use_sales_order_as_cart", 0)):
		return "Sales Order"
	return "Quotation"


def _cart_item_doctype():
	return "Sales Order Item" if _cart_doctype() == "Sales Order" else "Quotation Item"


def _cart_party_name(quotation):
	"""Return the party name from a cart doc, regardless of doctype.

	Quotation stores it in `party_name` (+ `quotation_to` for Lead/Customer).
	Sales Order stores it in `customer` (always Customer).
	"""
	if quotation.doctype == "Sales Order":
		return quotation.get("customer")
	return quotation.get("party_name")


def set_cart_count(quotation=None):
	if cint(frappe.db.get_singles_value("Webshop Settings", "enabled")):
		if not quotation:
			quotation = _get_cart_quotation()
		cart_count = cstr(cint(quotation.get("total_qty")))

		if hasattr(frappe.local, "cookie_manager"):
			frappe.local.cookie_manager.set_cookie("cart_count", cart_count)



def _get_transit_days_for_party(party=None):
        """Get transit days from Customer record. Returns int (default 1 — next-day delivery to JKIA)."""
        if not party:
                party = get_party()
        if party and party.doctype == "Customer":
                transit_days = frappe.db.get_value("Customer", party.name, "custom_transit_days")
                if transit_days:
                        return cint(transit_days)
        return 1


@frappe.whitelist()
def get_cart_quotation(doc=None):
	party = get_party()

	if not doc:
		quotation = _get_cart_quotation(party)
		doc = quotation
		set_cart_count(quotation)

	addresses = get_address_docs(party=party)

	if not doc.customer_address and addresses:
		update_cart_address("billing", addresses[0].name)

	_ensure_default_delivery_date(doc)
	_decorate_items_with_stock_cap(doc)

	return {
		"doc": decorate_quotation_doc(doc),
		"shipping_addresses": get_shipping_addresses(party),
		"billing_addresses": get_billing_addresses(party),
		"shipping_rules": get_applicable_shipping_rules(party),
		"cart_settings": frappe.get_cached_doc("Webshop Settings"),
		"transit_days": _get_transit_days_for_party(party),
	}


def _ensure_default_delivery_date(doc):
	"""Make sure the cart doc has a delivery date set to at least tomorrow.

	The template renders the date input from `custom_delivery_date` (Quotation
	custom field) or `delivery_date` (Sales Order standard field). Either way,
	if it's blank we set it to tomorrow and persist so the input shows a value
	on first render instead of forcing the user to pick one before anything.
	"""
	from frappe.utils import add_days, nowdate, getdate
	tomorrow = add_days(nowdate(), 1)
	updates = {}

	if doc.meta.has_field("delivery_date"):
		current = doc.get("delivery_date")
		if not current or getdate(current) < getdate(tomorrow):
			doc.delivery_date = tomorrow
			updates["delivery_date"] = tomorrow

	if doc.meta.has_field("custom_delivery_date"):
		current_custom = doc.get("custom_delivery_date")
		if not current_custom or getdate(current_custom) < getdate(tomorrow):
			doc.custom_delivery_date = tomorrow
			updates["custom_delivery_date"] = tomorrow

	if updates and not doc.get("__islocal"):
		frappe.db.set_value(doc.doctype, doc.name, updates, update_modified=False)


@frappe.whitelist()
def get_shipping_addresses(party=None):
	if not party:
		party = get_party()
	addresses = get_address_docs(party=party)
	return [
		{
			"name": address.name,
			"title": address.address_title,
			"display": address.display,
		}
		for address in addresses
		if address.address_type == "Shipping"
	]


@frappe.whitelist()
def get_billing_addresses(party=None):
	if not party:
		party = get_party()
	addresses = get_address_docs(party=party)
	return [
		{
			"name": address.name,
			"title": address.address_title,
			"display": address.display,
		}
		for address in addresses
		if address.address_type == "Billing"
	]


def _fmt_qty(q):
	q = flt(q)
	return int(q) if q == int(q) else q


def _check_box_type_min_order_qty(quotation):
	"""Return error message (string) if any line fails the box-type minimum, else None.

	Box Type is optional — lines without one skip the minimum-order check entirely
	(no Box Type → no min qty to enforce).
	"""
	min_qty_cache = {}
	for item in quotation.get("items") or []:
		box_type = getattr(item, "custom_box_type", None)
		if not box_type:
			continue
		if box_type not in min_qty_cache:
			min_qty_cache[box_type] = flt(
				frappe.db.get_value("Box Type", box_type, "min_order_qty") or 0
			)
		min_qty = min_qty_cache[box_type]
		qty = flt(item.qty)
		if min_qty and qty < min_qty:
			deficit = min_qty - qty
			return _("{0} ({1}, Box Type {2}) needs {3} more bunch(es) to request a quote. You have {4}, the minimum is {5}.").format(
				item.item_code,
				item.custom_length or _("no length"),
				box_type,
				_fmt_qty(deficit),
				_fmt_qty(qty),
				_fmt_qty(min_qty),
			)
	return None


def _decorate_items_with_stock_cap(doc):
	"""Stamp each cart row with `_max_stock_bunches` so the template can
	disable the qty `+` button when the row would exceed available stock.

	Cap is computed per (item, length) and *excludes* other cart rows for
	the same key — matching server-side enforcement in `update_cart`, where
	`other_rows_stock_qty` reduces the remaining headroom. The result is
	whole bunches: floor((available - other) / stems_per_bunch).

	Non-stock items, free items, and carts with `allow_items_not_in_stock`
	enabled are left at sentinel `0` (template treats 0 as "no cap").
	"""
	if not doc or not doc.get("items"):
		return

	cart_settings = frappe.get_cached_doc("Webshop Settings")
	if cint(cart_settings.get("allow_items_not_in_stock")):
		return

	avail_cache = {}
	for item in doc.get("items"):
		try:
			item._max_stock_bunches = 0
			if getattr(item, "is_free_item", 0):
				continue
			if not frappe.db.get_value("Item", item.item_code, "is_stock_item"):
				continue

			key = (item.item_code, item.get("custom_length") or "")
			if key not in avail_cache:
				avail_cache[key] = flt(
					_stock_uom_qty_available(item.item_code, key[1] or None)
				)
			available = avail_cache[key]

			other_rows_stock_qty = sum(
				flt(i.stock_qty)
				for i in doc.get("items")
				if i.name != item.name
				and i.item_code == item.item_code
				and (i.get("custom_length") or "") == key[1]
			)
			remaining = max(0.0, available - other_rows_stock_qty)
			stems_per_bunch = flt(_stems_per_bunch_from_uom(item.uom)) or 1
			item._max_stock_bunches = int(remaining // stems_per_bunch)
		except Exception:
			item._max_stock_bunches = 0


def _assign_sequential_box_ids(doc):
	"""Stamp `custom_box_id` on each item row with a sequential integer (1..N)
	in idx order, but only when the doctype actually has the field.

	Tambuzi marks Sales Order Item.custom_box_id as reqd=1; the cart has no UI
	to set it. Downstream pick-list automation re-derives box ids during
	packing, so the values written here are just placeholders to clear the
	mandatory validator.
	"""
	items = doc.get("items") or []
	if not items:
		return
	child_meta = frappe.get_meta(items[0].doctype)
	if not child_meta.has_field("custom_box_id"):
		return
	for idx, item in enumerate(items, start=1):
		if not item.get("custom_box_id"):
			item.custom_box_id = idx


def _validate_cart_stock(doc):
	"""Throw if the cart's total demand per (item, length) exceeds available stock.

	Aggregates across all rows so that splitting one item across multiple cart
	rows (different box types / UOMs but same item+length) cannot collectively
	oversell. Skips items where `is_stock_item` is 0. No-op if the cart setting
	`allow_items_not_in_stock` is enabled — that toggle is the caller's check.
	"""
	stock_qty_by_key = {}
	for item in doc.get("items") or []:
		if not frappe.db.get_value("Item", item.item_code, "is_stock_item"):
			continue
		key = (item.item_code, item.get("custom_length") or "")
		stock_qty_by_key[key] = stock_qty_by_key.get(key, 0.0) + flt(item.stock_qty)

	for (item_code, custom_length), requested in stock_qty_by_key.items():
		item_stock = get_web_item_qty_in_stock(item_code, "website_warehouse")
		if not cint(item_stock.in_stock):
			throw(_("{0} Not in Stock").format(item_code))

		available_stock_qty = flt(
			_stock_uom_qty_available(item_code, custom_length or None)
		)
		if requested > available_stock_qty:
			stock_uom = frappe.db.get_value("Item", item_code, "stock_uom") or ""
			length_label = custom_length or _("any length")
			throw(
				_("Only {0} {1} of {2} ({3}) available in stock — your cart has {4} {1}.").format(
					_fmt_qty(available_stock_qty),
					stock_uom,
					item_code,
					length_label,
					_fmt_qty(requested),
				)
			)


def _check_required_cart_fields(quotation):
	"""Cart-level required fields (Delivery Point, Line Code). Returns an error
	dict the place_order / request_for_quotation endpoints surface to the UI,
	or None when everything is filled in."""
	if quotation.meta.has_field("custom_delivery_point") and not (quotation.get("custom_delivery_point") or "").strip():
		return _("Please select a Delivery Point before placing your order.")
	if quotation.meta.has_field("custom_line_code") and not (quotation.get("custom_line_code") or "").strip():
		return _("Please enter a Line Code before placing your order.")
	return None


@frappe.whitelist()
def place_order():
	quotation = _get_cart_quotation()
	required_err = _check_required_cart_fields(quotation)
	if required_err:
		return {"error": required_err}
	box_err = _check_box_type_min_order_qty(quotation)
	if box_err:
		return {"error": box_err}
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	quotation.company = cart_settings.company

	quotation.flags.ignore_permissions = True
	quotation.submit()

	if quotation.quotation_to == "Lead" and quotation.party_name:
		# company used to create customer accounts
		frappe.defaults.set_user_default("company", quotation.company)

	if not (quotation.shipping_address_name or quotation.customer_address):
		frappe.throw(_("Set Shipping Address or Billing Address"))

	sales_order = frappe.get_doc(
		_make_sales_order(
			quotation.name, ignore_permissions=True
		)
	)
	sales_order.payment_schedule = []
	_assign_sequential_box_ids(sales_order)

	# Ensure delivery_date is at least tomorrow (next day from today).
	# Sales Order requires a future date; if the quotation didn't carry a fresh
	# date, fall back to tomorrow on both the header and every line item.
	tomorrow = add_days(nowdate(), 1)
	if not sales_order.delivery_date or getdate(sales_order.delivery_date) < getdate(tomorrow):
		sales_order.delivery_date = tomorrow
	for so_item in sales_order.get("items") or []:
		if not so_item.delivery_date or getdate(so_item.delivery_date) < getdate(tomorrow):
			so_item.delivery_date = tomorrow

	if not cint(cart_settings.get("allow_items_not_in_stock")):
		# Refresh warehouse pointers before validating; the cart UI doesn't always
		# set them on append.
		for item in sales_order.get("items"):
			item.warehouse = frappe.db.get_value(
				"Website Item", {"item_code": item.item_code}, "website_warehouse"
			)
		_validate_cart_stock(sales_order)

	sales_order.flags.ignore_permissions = True
	sales_order.insert()
	sales_order.submit()

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return sales_order.name


@frappe.whitelist()
def request_for_quotation():
	quotation = _get_cart_quotation()
	required_err = _check_required_cart_fields(quotation)
	if required_err:
		return {"error": required_err}
	box_err = _check_box_type_min_order_qty(quotation)
	if box_err:
		return {"error": box_err}

	cart_settings = frappe.get_cached_doc("Webshop Settings")
	if not cint(cart_settings.get("allow_items_not_in_stock")):
		_validate_cart_stock(quotation)

	# When the cart container is Sales Order, Tambuzi's reqd=1
	# `custom_box_id` on Sales Order Item must be populated before save.
	# Helper is a no-op when the field doesn't exist (Quotation, Kaitet, etc).
	_assign_sequential_box_ids(quotation)

	quotation.flags.ignore_permissions = True
	quotation.flags.ignore_validate = True
	quotation.save()

	cart_settings = frappe.get_cached_doc("Webshop Settings")
	# In Sales-Order-as-cart mode, always leave the SO in draft. Sales staff
	# submit it from the desk; the webshop never auto-submits orders.
	if quotation.doctype == "Quotation" and not cint(cart_settings.save_quotations_as_draft):
		quotation.submit()

	return quotation.name


def _get_per_stem_rate(item_code, custom_length, currency, price_list, uom=None):
	"""Fetch per-stem price from Item Price.
	First tries matching by uom (bunch-specific price), then falls back to stock_uom (Stems) price.
	"""
	base_filters = {
		"item_code": item_code,
		"price_list": price_list,
		"currency": currency,
	}
	# Try bunch-specific price first
	if uom:
		price_records = frappe.db.get_all(
			"Item Price",
			filters={**base_filters, "uom": uom},
			fields=["price_list_rate"],
			limit=1,
		)
		if price_records:
			# Bunch-specific price is per-bunch; divide by conversion_factor to get per-stem
			conversion_factor = flt(frappe.db.get_value(
				"UOM Conversion Detail",
				{"parent": item_code, "uom": uom},
				"conversion_factor"
			) or 1)
			return flt(price_records[0].price_list_rate) / conversion_factor if conversion_factor else flt(price_records[0].price_list_rate)

	# Fall back to stock UOM (Stems) price — already per-stem
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	price_records = frappe.db.get_all(
		"Item Price",
		filters={**base_filters, "uom": stock_uom},
		fields=["price_list_rate"],
		limit=1,
	)
	if price_records:
		return flt(price_records[0].price_list_rate)

	# Last resort: any price for this item
	price_records = frappe.db.get_all(
		"Item Price",
		filters=base_filters,
		fields=["price_list_rate"],
		limit=1,
	)
	if price_records:
		return flt(price_records[0].price_list_rate)
	return None


def _stems_per_bunch_from_uom(uom_name):
	"""Parse stems per bunch from UOM name like 'Bunch (10)' → 10."""
	import re
	if uom_name:
		m = re.search(r'\((\d+)\)', uom_name)
		if m:
			return int(m.group(1))
	return 1


def _stock_uom_qty_available(item_code, custom_length=None):
	"""Total actual_qty available in stock UOM, optionally scoped to a stem length.

	Warehouse resolution uses the storefront warehouse set (Webshop Settings →
	Warehouses, group-expanded) — same as the listing card and product detail
	page — so the qty surfaced to the cart matches what users see elsewhere.
	Falls back to the per-item website_warehouse if Webshop Settings is empty.

	Source-of-truth choice:
	  - Variant or template items resolve length at the item level, so core Bin
	    already tracks per-length qty. Always read from Bin.
	  - Plain items (the case Stem Length Bin was built for) read from
	    Stem Length Bin: a specific length if given, summed across all lengths
	    in the warehouse(s) otherwise.
	"""
	from upande_webshop.upande_webshop.product_data_engine.query import (
		_all_storefront_warehouses,
	)

	warehouse = frappe.db.get_value(
		"Website Item", {"item_code": item_code}, "website_warehouse"
	)
	if not warehouse:
		template = frappe.db.get_value("Item", item_code, "variant_of")
		if template and template != item_code:
			warehouse = frappe.db.get_value(
				"Website Item", {"item_code": template}, "website_warehouse"
			)

	warehouses = _all_storefront_warehouses(warehouse)
	if not warehouses:
		return 0

	item_meta = frappe.db.get_value(
		"Item", item_code, ["has_variants", "variant_of"], as_dict=True
	) or frappe._dict()
	is_variant_or_template = bool(item_meta.has_variants) or bool(item_meta.variant_of)

	if is_variant_or_template:
		total = frappe.db.sql(
			"""SELECT COALESCE(SUM(actual_qty), 0)
			   FROM `tabBin`
			   WHERE item_code = %s AND warehouse IN ({})""".format(
				",".join(["%s"] * len(warehouses))
			),
			[item_code, *warehouses],
		)
		return flt(total[0][0]) if total else 0

	if custom_length:
		total = frappe.db.sql(
			"""SELECT COALESCE(SUM(actual_qty), 0)
			   FROM `tabStem Length Bin`
			   WHERE item_code = %s AND stem_length = %s AND warehouse IN ({})""".format(
				",".join(["%s"] * len(warehouses))
			),
			[item_code, custom_length, *warehouses],
		)
		return flt(total[0][0]) if total else 0

	total = frappe.db.sql(
		"""SELECT COALESCE(SUM(actual_qty), 0)
		   FROM `tabStem Length Bin`
		   WHERE item_code = %s AND warehouse IN ({})""".format(
			",".join(["%s"] * len(warehouses))
		),
		[item_code, *warehouses],
	)
	return flt(total[0][0]) if total else 0


def _apply_length_price_db(quotation):
	"""After quotation.save(), directly update rate/amount in DB for length-priced items.
	This bypasses ERPNext's calculate_taxes_and_totals which overwrites our values.
	Item Price.price_list_rate is already per-stem.
	qty is in bunches; stock_qty = qty × conversion_factor = total stems.
	rate = per_stem price, amount = per_stem × total_stems.

	Works against either Quotation/Quotation Item or Sales Order/Sales Order Item;
	the relevant custom fields (custom_length, custom_total_stems) exist on both.
	"""
	parent_dt = quotation.doctype
	child_dt = "Sales Order Item" if parent_dt == "Sales Order" else "Quotation Item"
	price_list = quotation.selling_price_list
	currency = quotation.currency
	net_total = flt(0)
	any_changed = False
	# Sites without the rose/length flow (mona, tambuzi) won't have custom_length /
	# custom_total_stems on Quotation/Sales Order Item. Drop those keys from the
	# DB write so we don't 1146 the cart on a missing column.
	has_custom_length = frappe.db.has_column(child_dt, "custom_length")
	has_total_stems = frappe.db.has_column(child_dt, "custom_total_stems")

	for item in quotation.get("items"):
		# Derive conversion_factor from the UOM name (e.g. "Bunch (15)" → 15).
		# This is the authoritative source — UOM Conversion Detail may be missing entries
		# and ERPNext resets conversion_factor to 1 during calculate_taxes_and_totals.
		cf = flt(_stems_per_bunch_from_uom(item.uom)) if item.uom else flt(item.conversion_factor or 1)
		item.conversion_factor = cf
		total_stems = flt(item.qty) * cf
		if item.name:
			length_for_price = item.get("custom_length") if has_custom_length else None
			per_stem = _get_per_stem_rate(item.item_code, length_for_price, currency, price_list, uom=item.uom)
			db_fields = {"conversion_factor": cf, "stock_qty": total_stems}
			if has_total_stems:
				db_fields["custom_total_stems"] = total_stems
				item.custom_total_stems = total_stems
			item.stock_qty = total_stems
			if per_stem is not None:
				amount = flt(per_stem * total_stems, 9)
				db_fields.update({"rate": per_stem, "amount": amount})
				item.rate = per_stem
				item.amount = amount
				any_changed = True
			frappe.db.set_value(child_dt, item.name, db_fields, update_modified=False)
		net_total += flt(item.amount)

	if any_changed:
		# Update parent totals in DB and in-memory so template context is correct
		frappe.db.set_value(
			parent_dt, quotation.name,
			{"total": net_total, "net_total": net_total, "grand_total": net_total},
			update_modified=False
		)
		quotation.total = net_total
		quotation.net_total = net_total
		quotation.grand_total = net_total


@frappe.whitelist()
def update_cart(item_code, qty, additional_notes=None, uom=None, custom_length=None, custom_box_type=None, with_items=False, child_docname=None):
	quotation = _get_cart_quotation()

	# Sites without the rose/length flow (mona, tambuzi) won't have custom_length /
	# custom_box_type on Quotation/Sales Order Item — fall back to getattr/None.
	child_dt = "Sales Order Item" if quotation.doctype == "Sales Order" else "Quotation Item"
	has_custom_length = frappe.db.has_column(child_dt, "custom_length")
	has_custom_box_type = frappe.db.has_column(child_dt, "custom_box_type")

	empty_card = False
	qty = flt(qty)

	if qty > 0:
		cart_settings = frappe.get_cached_doc("Webshop Settings")
		if not cint(cart_settings.get("allow_items_not_in_stock")):
			is_stock_item = frappe.db.get_value("Item", item_code, "is_stock_item")
			if is_stock_item:
				item_stock = get_web_item_qty_in_stock(item_code, "website_warehouse")
				if not cint(item_stock.in_stock):
					throw(_("{0} is not in stock").format(item_code))

				# Cap the requested qty at what's actually available in the warehouse.
				# Compare in stock UOM so it works across bunch UOMs of different sizes.
				# Include other rows already in the cart for the same item so users can't
				# split a request across multiple (length/box type) rows to bypass the limit.
				requested_stock_qty = qty * flt(_stems_per_bunch_from_uom(uom)) if uom else qty

				def _is_row_being_replaced(i):
					if child_docname:
						return i.name == child_docname
					if i.item_code != item_code:
						return False
					if has_custom_length and (i.get("custom_length") or "") != (custom_length or ""):
						return False
					if has_custom_box_type and (i.get("custom_box_type") or "") != (custom_box_type or ""):
						return False
					return (i.uom or "") == (uom or "")

				other_rows_stock_qty = sum(
					flt(i.stock_qty)
					for i in quotation.get("items", [])
					if i.item_code == item_code
					and (not has_custom_length or (i.get("custom_length") or "") == (custom_length or ""))
					and not _is_row_being_replaced(i)
				)
				available_stock_qty = flt(_stock_uom_qty_available(item_code, custom_length))
				if requested_stock_qty + other_rows_stock_qty > available_stock_qty:
					remaining = max(0, available_stock_qty - other_rows_stock_qty)
					stock_uom = frappe.db.get_value("Item", item_code, "stock_uom") or ""
					if other_rows_stock_qty > 0:
						msg = _("Only {0} {1} of {2} available in stock — you already have {3} {1} in your cart.").format(
							_fmt_qty(remaining), stock_uom, item_code, _fmt_qty(other_rows_stock_qty)
						)
					else:
						msg = _("Only {0} {1} of {2} available in stock.").format(
							_fmt_qty(remaining), stock_uom, item_code
						)
					throw(msg)

	if qty == 0:
		# Remove specific row by child_docname if provided, otherwise remove all rows for item_code
		if child_docname:
			remaining = [i for i in quotation.get("items") if i.name != child_docname]
		else:
			remaining = quotation.get("items", {"item_code": ["!=", item_code]})
		if remaining:
			quotation.set("items", remaining)
		else:
			empty_card = True

	else:

		warehouse = frappe.get_cached_value(
			"Website Item", {"item_code": item_code}, "website_warehouse"
		)

		# Match by child_docname (update), or by item_code + custom_length +
		# custom_box_type + uom (existing row), else append new.
		# Box type is part of the dedup key so each (length, box type) combo
		# selected on the product page gets its own cart row, and carries
		# through to Quotation / Sales Order independently.
		if child_docname:
			matched = [i for i in quotation.get("items") if i.name == child_docname]
		else:
			def _matches(i):
				if i.item_code != item_code:
					return False
				if has_custom_length and (i.get("custom_length") or "") != (custom_length or ""):
					return False
				if has_custom_box_type and (i.get("custom_box_type") or "") != (custom_box_type or ""):
					return False
				return (i.uom or "") == (uom or "")

			matched = [i for i in quotation.get("items") if _matches(i)]

		has_total_stems = frappe.db.has_column(child_dt, "custom_total_stems")

		if not matched:
			# New combination — append a new row
			if not uom:
				uom = frappe.db.get_value("Item", item_code, "stock_uom")
			# Parse stems from UOM name (e.g. "Bunch (15)" → 15) as primary source.
			# UOM Conversion Detail may be missing entries for custom bunch UOMs.
			conversion_factor = flt(_stems_per_bunch_from_uom(uom))
			total_stems = qty * conversion_factor
			new_row = {
				"doctype": child_dt,
				"item_code": item_code,
				"qty": qty,
				"uom": uom,
				"conversion_factor": conversion_factor,
				"stock_qty": total_stems,
				"additional_notes": additional_notes,
				"warehouse": warehouse,
			}
			if has_total_stems:
				new_row["custom_total_stems"] = total_stems
			if has_custom_length:
				new_row["custom_length"] = custom_length
			if has_custom_box_type:
				new_row["custom_box_type"] = custom_box_type
			quotation.append("items", new_row)
		else:
			item = matched[0]
			item.qty = qty
			if uom:
				item.uom = uom
			if has_custom_length and custom_length:
				item.custom_length = custom_length
			if has_custom_box_type and custom_box_type:
				item.custom_box_type = custom_box_type
			item.warehouse = warehouse
			item.additional_notes = additional_notes
			# Always re-derive conversion_factor from the (possibly updated) UOM
			# so qty × cf produces the right stem count even when a legacy row
			# (uom="Nos", cf=1) is being migrated to a bunch UOM.
			cf = flt(_stems_per_bunch_from_uom(item.uom))
			if not cf:
				cf = flt(item.conversion_factor or 1)
			item.conversion_factor = cf
			total_stems = qty * cf
			item.stock_qty = total_stems
			if has_total_stems:
				item.custom_total_stems = total_stems

	# Row removal must always succeed, even if pricing/FX is misconfigured.
	# On qty==0 we delete the Quotation Item directly via DB and skip the full
	# quotation.save() (which re-runs validators that fetch exchange rates and
	# can 500 when USD→KES is unavailable for the quotation's transaction_date).
	if qty == 0:
		parent_dt = quotation.doctype
		child_dt = "Sales Order Item" if parent_dt == "Sales Order" else "Quotation Item"
		if empty_card:
			frappe.delete_doc(parent_dt, quotation.name, ignore_permissions=True, force=True)
			quotation = None
		else:
			# Delete the row(s) directly; recompute totals without touching FX.
			kept_names = {i.name for i in quotation.get("items")}
			frappe.db.sql(
				"""DELETE FROM `tab{child}`
				   WHERE parent=%s AND name NOT IN ({placeholders})""".format(
					   child=child_dt,
					   placeholders=",".join(["%s"] * len(kept_names)) if kept_names else "''",
				   ),
				[quotation.name, *kept_names] if kept_names else [quotation.name],
			)
			# Recompute net/grand totals from remaining rows; skip FX/pricing.
			net_total = sum(flt(i.amount) for i in quotation.get("items"))
			frappe.db.set_value(
				parent_dt,
				quotation.name,
				{
					"total_qty": sum(flt(i.qty) for i in quotation.get("items")),
					"total": net_total,
					"net_total": net_total,
					"grand_total": net_total,
					"rounded_total": net_total,
				},
				update_modified=False,
			)
			frappe.db.commit()
			# Reload so downstream rendering sees fresh state.
			quotation = frappe.get_doc(parent_dt, quotation.name)
	else:
		apply_cart_settings(quotation=quotation)
		# Tambuzi's Sales Order Item.custom_box_id is reqd=1; `ignore_validate`
		# doesn't skip mandatory checks, so every cart save needs ids stamped.
		# Helper is a no-op when the field doesn't exist on this cart's child doctype.
		_assign_sequential_box_ids(quotation)
		quotation.flags.ignore_permissions = True
		quotation.flags.ignore_validate = True
		quotation.payment_schedule = []
		quotation.save()
		_apply_length_price_db(quotation)

	set_cart_count(quotation)

	# Include cart_count in the response so the client can update the badge
	# without depending on cookie propagation timing (cookies set via
	# Set-Cookie are usually visible by the callback, but returning the count
	# directly is more reliable and avoids a stale-badge race).
	cart_count = cint(quotation.get("total_qty")) if quotation else 0

	if cint(with_items):
		context = get_cart_quotation(quotation)
		return {
			"items": frappe.render_template(
				"templates/includes/cart/cart_items.html", context
			),
			"total": frappe.render_template(
				"templates/includes/cart/cart_items_total.html", context
			),
			"taxes_and_totals": frappe.render_template(
				"templates/includes/cart/cart_payment_summary.html", context
			),
			"cart_count": cart_count,
		}
	else:
		return {"name": quotation.name, "cart_count": cart_count}


@frappe.whitelist()
def get_shopping_cart_menu(context=None):
	if not context:
		context = get_cart_quotation()

	return frappe.render_template("templates/includes/cart/cart_dropdown.html", context)


@frappe.whitelist()
def add_new_address(doc):
	doc = frappe.parse_json(doc)
	doc.update({"doctype": "Address"})
	address = frappe.get_doc(doc)
	address.save(ignore_permissions=True)

	return address


@frappe.whitelist(allow_guest=True)
def create_lead_for_item_inquiry(lead, subject, message):
	lead = frappe.parse_json(lead)
	lead_doc = frappe.new_doc("Lead")
	for fieldname in ("lead_name", "company_name", "email_id", "phone"):
		lead_doc.set(fieldname, lead.get(fieldname))

	lead_doc.set("lead_owner", "")

	if not frappe.db.exists("Lead Source", "Product Inquiry"):
		frappe.get_doc(
			{"doctype": "Lead Source", "source_name": "Product Inquiry"}
		).insert(ignore_permissions=True)

	lead_doc.set("source", "Product Inquiry")

	try:
		lead_doc.save(ignore_permissions=True)
	except frappe.exceptions.DuplicateEntryError:
		frappe.clear_messages()
		lead_doc = frappe.get_doc("Lead", {"email_id": lead["email_id"]})

	lead_doc.add_comment(
		"Comment",
		text="""
		<div>
			<h5>{subject}</h5>
			<p>{message}</p>
		</div>
	""".format(
			subject=subject, message=message
		),
	)

	return lead_doc


@frappe.whitelist()
def get_terms_and_conditions(terms_name):
	return frappe.db.get_value("Terms and Conditions", terms_name, "terms")


@frappe.whitelist()
def update_cart_address(address_type, address_name):
	quotation = _get_cart_quotation()
	address_doc = frappe.get_doc("Address", address_name).as_dict()
	address_display = get_address_display(address_doc)

	if address_type.lower() == "billing":
		quotation.customer_address = address_name
		quotation.address_display = address_display
		quotation.shipping_address_name = (
			quotation.shipping_address_name or address_name
		)
		address_doc = next(
			(doc for doc in get_billing_addresses() if doc["name"] == address_name),
			None,
		)
	elif address_type.lower() == "shipping":
		quotation.shipping_address_name = address_name
		quotation.shipping_address = address_display
		quotation.customer_address = quotation.customer_address or address_name
		address_doc = next(
			(doc for doc in get_shipping_addresses() if doc["name"] == address_name),
			None,
		)
	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()

	context = get_cart_quotation(quotation)
	context["address"] = address_doc

	return {
		"taxes": frappe.render_template(
			"templates/includes/order/order_taxes.html", context
		),
		"address": frappe.render_template(
			"templates/includes/cart/address_card.html", context
		),
	}


def guess_territory():
	territory = None
	geoip_country = frappe.session.get("session_country")
	if geoip_country:
		territory = frappe.db.get_value("Territory", geoip_country)

	return (
		territory
		or get_root_of("Territory")
	)


def decorate_quotation_doc(doc):
	for d in doc.get("items", []):
		item_code = d.item_code
		fields = ["web_item_name", "thumbnail", "website_image", "description", "route"]

		# Variant Item
		if not frappe.db.exists("Website Item", {"item_code": item_code}):
			variant_data = frappe.db.get_values(
				"Item",
				filters={"item_code": item_code},
				fieldname=["variant_of", "item_name", "image"],
				as_dict=True,
			)[0]
			item_code = variant_data.variant_of
			fields = fields[1:]
			d.web_item_name = variant_data.item_name

			if variant_data.image:  # get image from variant or template web item
				d.thumbnail = variant_data.image
				fields = fields[2:]

		d.update(
			frappe.db.get_value(
				"Website Item", {"item_code": item_code}, fields, as_dict=True
			)
		)

		website_warehouse = frappe.get_cached_value(
			"Website Item", {"item_code": item_code}, "website_warehouse"
		)

		d.warehouse = website_warehouse

	return doc


def _get_cart_quotation(party=None):
	"""Return the open cart document (Quotation or Sales Order) or make a new one.

	Kept under the historical name as a thin shim so callers across this module
	keep working. The actual cart doctype is chosen by `_cart_doctype()`.
	"""
	return _get_cart_doc(party=party)


def _get_cart_doc(party=None):
	"""Return the open draft cart document of the configured doctype.

	For "Sales Order" mode, the party must be a Customer (Sales Order has no
	`quotation_to`). If `get_party()` returns a Lead, we still need a Customer —
	we fall back to Quotation mode for that session rather than silently
	promoting the Lead, which is a destructive side-effect for a cart action.
	"""
	if not party:
		party = get_party()

	target_doctype = _cart_doctype()

	# Sales Order can't accept a Lead. If we don't have a Customer in hand,
	# degrade to Quotation for this request so the cart still works.
	if target_doctype == "Sales Order" and (not party or party.doctype != "Customer"):
		target_doctype = "Quotation"

	if target_doctype == "Sales Order":
		filters = {
			"customer": party.name,
			"contact_email": frappe.session.user,
			"order_type": "Shopping Cart",
			"docstatus": 0,
		}
	else:
		filters = {
			"party_name": party.name,
			"contact_email": frappe.session.user,
			"order_type": "Shopping Cart",
			"docstatus": 0,
		}

	existing = frappe.get_all(
		target_doctype,
		fields=["name"],
		filters=filters,
		order_by="modified desc",
		limit_page_length=1,
	)

	if existing:
		qdoc = frappe.get_doc(target_doctype, existing[0].name)
	else:
		cart_settings = frappe.get_cached_doc("Webshop Settings")
		company = cart_settings.company

		# Default delivery to the next day from the order date (tomorrow).
		# The cart UI may overwrite this via update_cart_delivery_date once the
		# customer picks a date, but the doc must be valid before that happens.
		default_delivery_date = add_days(nowdate(), 1)

		if target_doctype == "Sales Order":
			qdoc = frappe.get_doc(
				{
					"doctype": "Sales Order",
					"naming_series": cart_settings.get("quotation_series")
					or "SAL-ORD-.YYYY.-",
					"customer": party.name,
					"company": company,
					"order_type": "Shopping Cart",
					"delivery_date": default_delivery_date,
					"status": "Draft",
					"docstatus": 0,
					"__islocal": 1,
				}
			)
		else:
			qdoc = frappe.get_doc(
				{
					"doctype": "Quotation",
					"naming_series": get_shopping_cart_settings().quotation_series
					or "QTN-CART-",
					"quotation_to": party.doctype,
					"company": company,
					"order_type": "Shopping Cart",
					"delivery_date": default_delivery_date,
					"status": "Draft",
					"docstatus": 0,
					"__islocal": 1,
					"party_name": party.name,
				}
			)

		qdoc.contact_person = frappe.db.get_value(
			"Contact", {"email_id": frappe.session.user}
		)
		qdoc.contact_email = frappe.session.user

		qdoc.flags.ignore_permissions = True
		qdoc.run_method("set_missing_values")
		apply_cart_settings(party, qdoc)

	return qdoc


def update_party(fullname, company_name=None, mobile_no=None, phone=None):
	party = get_party()

	party.customer_name = company_name or fullname
	party.customer_type = "Company" if company_name else "Individual"

	contact_name = frappe.db.get_value("Contact", {"email_id": frappe.session.user})
	contact = frappe.get_doc("Contact", contact_name)
	contact.first_name = fullname
	contact.last_name = None
	contact.customer_name = party.customer_name
	contact.mobile_no = mobile_no
	contact.phone = phone
	contact.flags.ignore_permissions = True
	contact.save()

	party_doc = frappe.get_doc(party.as_dict())
	party_doc.flags.ignore_permissions = True
	party_doc.save()

	qdoc = _get_cart_quotation(party)
	if not qdoc.get("__islocal"):
		qdoc.customer_name = company_name or fullname
		qdoc.run_method("set_missing_lead_customer_details")
		qdoc.flags.ignore_permissions = True
		qdoc.save()


def apply_cart_settings(party=None, quotation=None):
	if not party:
		party = get_party()
	if not quotation:
		quotation = _get_cart_quotation(party)

	cart_settings = frappe.get_cached_doc("Webshop Settings")

	set_price_list_and_rate(quotation, cart_settings)

	quotation.run_method("calculate_taxes_and_totals")

	set_taxes(quotation, cart_settings)

	_apply_shipping_rule(party, quotation, cart_settings)


def set_price_list_and_rate(quotation, cart_settings):
	"""set price list based on billing territory"""

	_set_price_list(cart_settings, quotation)

	# reset values
	quotation.price_list_currency = (
		quotation.currency
	) = quotation.plc_conversion_rate = quotation.conversion_rate = None
	for item in quotation.get("items"):
		item.price_list_rate = item.discount_percentage = item.rate = item.amount = None

	# refetch values
	quotation.run_method("set_price_list_and_item_details")

	if hasattr(frappe.local, "cookie_manager"):
		# set it in cookies for using in product page
		frappe.local.cookie_manager.set_cookie(
			"selling_price_list", quotation.selling_price_list
		)


def _set_price_list(cart_settings, quotation=None):
	"""Set price list based on customer or shopping cart default"""
	from erpnext.accounts.party import get_default_price_list

	party_name = _cart_party_name(quotation) if quotation else get_party().get("name")
	selling_price_list = None

	# check if default customer price list exists
	if party_name and frappe.db.exists("Customer", party_name):
		selling_price_list = get_default_price_list(
			frappe.get_doc("Customer", party_name)
		)

	# check default price list in shopping cart
	if not selling_price_list:
		selling_price_list = cart_settings.price_list

	if quotation:
		quotation.selling_price_list = selling_price_list

	return selling_price_list


def set_taxes(quotation, cart_settings):
	"""set taxes based on billing territory"""
	from erpnext.accounts.party import set_taxes

	party_name = _cart_party_name(quotation)
	customer_group = frappe.db.get_value(
		"Customer", party_name, "customer_group"
	)

	quotation.taxes_and_charges = set_taxes(
		party_name,
		"Customer",
		quotation.transaction_date,
		quotation.company,
		customer_group=customer_group,
		supplier_group=None,
		tax_category=quotation.tax_category,
		billing_address=quotation.customer_address,
		shipping_address=quotation.shipping_address_name,
		use_for_shopping_cart=1,
	)
	#
	# 	# clear table
	quotation.set("taxes", [])
	#
	# 	# append taxes
	quotation.append_taxes_from_master()
	quotation.append_taxes_from_item_tax_template()


def get_party(user=None):
	if not user:
		user = frappe.session.user

	contact_name = get_contact_name(user)
	party = None

	if contact_name:
		contact = frappe.get_doc("Contact", contact_name)
		for link in contact.links:
			if frappe.db.exists(link.link_doctype, link.link_name):
				party_doctype = link.link_doctype
				party = link.link_name
				break

	cart_settings = frappe.get_cached_doc("Webshop Settings")

	debtors_account = ""

	if cart_settings.enable_checkout:
		debtors_account = get_debtors_account(cart_settings)

	if party:
		doc = frappe.get_doc(party_doctype, party)
		if doc.doctype in ["Customer", "Supplier"]:
			if not frappe.db.exists("Portal User", {"parent": doc.name, "user": user}):
				doc.append("portal_users", {"user": user})
				doc.flags.ignore_permissions = True
				doc.flags.ignore_mandatory = True
				doc.save()

		return doc

	elif not frappe.db.exists("Portal User", {"user": user}):
		if not cart_settings.enabled:
			frappe.local.flags.redirect_location = "/contact"
			raise frappe.Redirect
		customer = frappe.new_doc("Customer")
		fullname = get_fullname(user)
		customer.update(
			{
				"customer_name": fullname,
				"customer_type": "Individual",
				"customer_group": get_shopping_cart_settings().default_customer_group,
				"territory": get_root_of("Territory"),
			}
		)

		customer.append("portal_users", {"user": user})

		if debtors_account:
			customer.update(
				{
					"accounts": [
						{"company": cart_settings.company, "account": debtors_account}
					]
				}
			)

		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)

		contact = frappe.new_doc("Contact")
		contact.update(
			{"first_name": fullname, "email_ids": [{"email_id": user, "is_primary": 1}]}
		)
		contact.append("links", dict(link_doctype="Customer", link_name=customer.name))
		contact.flags.ignore_mandatory = True
		contact.insert(ignore_permissions=True)

		return customer
	else:
		customer = frappe.db.get_value(
			"Portal User", {"user": user}, ["parent"]
		)

		if frappe.db.exists("Customer", customer):
			return frappe.get_doc("Customer", customer)


def get_debtors_account(cart_settings):
	if not cart_settings.payment_gateway_account:
		frappe.throw(_("Payment Gateway Account not set"), _("Mandatory"))

	payment_gateway_account_currency = frappe.get_doc(
		"Payment Gateway Account", cart_settings.payment_gateway_account
	).currency

	account_name = _("Debtors ({0})").format(payment_gateway_account_currency)

	debtors_account_name = get_account_name(
		"Receivable",
		"Asset",
		is_group=0,
		account_currency=payment_gateway_account_currency,
		company=cart_settings.company,
	)

	if not debtors_account_name:
		debtors_account = frappe.get_doc(
			{
				"doctype": "Account",
				"account_type": "Receivable",
				"root_type": "Asset",
				"is_group": 0,
				"parent_account": get_account_name(
					root_type="Asset", is_group=1, company=cart_settings.company
				),
				"account_name": account_name,
				"currency": payment_gateway_account_currency,
			}
		).insert(ignore_permissions=True)

		return debtors_account.name

	else:
		return debtors_account_name


def get_address_docs(
    doctype=None,
    txt=None,
    filters=None,
    limit_start=0,
    limit_page_length=20,
    party=None,
):
	if not party:
		party = get_party()

	if not party:
		return []

	address_names = frappe.db.get_all(
		"Dynamic Link",
		fields=("parent"),
		filters=dict(
			parenttype="Address", link_doctype=party.doctype, link_name=party.name
		),
	)

	out = []

	for a in address_names:
		address = frappe.get_doc("Address", a.parent)
		address.display = get_address_display(address.as_dict())
		out.append(address)

	return out


@frappe.whitelist()
def apply_shipping_rule(shipping_rule):
	quotation = _get_cart_quotation()

	quotation.shipping_rule = shipping_rule

	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()

	return get_cart_quotation(quotation)


def _apply_shipping_rule(party=None, quotation=None, cart_settings=None):
	if not quotation.shipping_rule:
		shipping_rules = get_shipping_rules(quotation, cart_settings)

		if not shipping_rules:
			return

		elif quotation.shipping_rule not in shipping_rules:
			quotation.shipping_rule = shipping_rules[0]

	if quotation.shipping_rule:
		quotation.run_method("apply_shipping_rule")
		quotation.run_method("calculate_taxes_and_totals")


def get_applicable_shipping_rules(party=None, quotation=None):
	shipping_rules = get_shipping_rules(quotation)

	if shipping_rules:
		rule_label_map = frappe.db.get_values("Shipping Rule", shipping_rules, "label")
		# we need this in sorted order as per the position of the rule in the settings page
		return [[rule, rule] for rule in shipping_rules]


def get_shipping_rules(quotation=None, cart_settings=None):
	if not quotation:
		quotation = _get_cart_quotation()

	shipping_rules = []
	if quotation.shipping_address_name:
		country = frappe.db.get_value(
			"Address", quotation.shipping_address_name, "country"
		)
		if country:
			sr_country = frappe.qb.DocType("Shipping Rule Country")
			sr = frappe.qb.DocType("Shipping Rule")
			query = (
				frappe.qb.from_(sr_country)
				.join(sr)
				.on(sr.name == sr_country.parent)
				.select(sr.name)
				.distinct()
				.where((sr_country.country == country) & (sr.disabled != 1) & (sr.shipping_rule_type == "Selling"))
			)
			result = query.run(as_list=True)
			shipping_rules = [x[0] for x in result]

	return shipping_rules


def get_address_territory(address_name):
	"""Tries to match city, state and country of address to existing territory"""
	territory = None

	if address_name:
		address_fields = frappe.db.get_value(
			"Address", address_name, ["city", "state", "country"]
		)
		for value in address_fields:
			territory = frappe.db.get_value("Territory", value)
			if territory:
				break

	return territory


def show_terms(doc):
	return doc.tc_name


@frappe.whitelist(allow_guest=True)
def apply_coupon_code(applied_code, applied_referral_sales_partner):
	quotation = True

	if not applied_code:
		frappe.throw(_("Please enter a coupon code"))

	coupon_list = frappe.get_all("Coupon Code", filters={"coupon_code": applied_code})
	if not coupon_list:
		frappe.throw(_("Please enter a valid coupon code"))

	coupon_name = coupon_list[0].name

	from erpnext.accounts.doctype.pricing_rule.utils import validate_coupon_code

	validate_coupon_code(coupon_name)
	quotation = _get_cart_quotation()
	quotation.ignore_pricing_rule = 0
	quotation.coupon_code = coupon_name
	quotation.flags.ignore_permissions = True
	quotation.save()

	if applied_referral_sales_partner:
		sales_partner_list = frappe.get_all(
			"Sales Partner", filters={"referral_code": applied_referral_sales_partner}
		)
		if sales_partner_list:
			sales_partner_name = sales_partner_list[0].name
			quotation.referral_sales_partner = sales_partner_name
			quotation.flags.ignore_permissions = True
			quotation.save()

	return quotation


@frappe.whitelist(allow_guest=True)
def remove_coupon_code():
	quotation = _get_cart_quotation()
	quotation.coupon_code = ""
	quotation.referral_sales_partner = ""
	quotation.flags.ignore_permissions = True

	# reset discount amount if coupon code is removed (on desk it is done in client side)
	# as we are enabling ignore_pricing_rule, so we also need to manually reset discount percentage
	quotation.discount_amount = 0
	quotation.additional_discount_percentage = 0
	quotation.ignore_pricing_rule = 1

	quotation.save()

	return quotation

@frappe.whitelist()
def update_cart_delivery_date(delivery_date):
	# Delivery must be at least tomorrow; the cart UI enforces this too,
	# but the server is the source of truth.
	tomorrow = add_days(nowdate(), 1)
	if not delivery_date or getdate(delivery_date) < getdate(tomorrow):
		delivery_date = tomorrow
	quotation = _get_cart_quotation()
	requested = getdate(delivery_date)
	current = quotation.get("delivery_date")
	current_custom = quotation.get("custom_delivery_date")
	already_current = (
		current and getdate(current) == requested
		and (not quotation.meta.has_field("custom_delivery_date")
		     or (current_custom and getdate(current_custom) == requested))
	)
	# Page load fires onchange from the datepicker's programmatic set_value,
	# so this endpoint gets POSTed redundantly. Skip the save when nothing
	# would actually change — avoids racing _ensure_default_delivery_date's
	# in-render write and the "Record has changed since last read" error.
	if already_current:
		return {"name": quotation.name, "delivery_date": str(delivery_date)}

	quotation.delivery_date = delivery_date
	if quotation.meta.has_field("custom_delivery_date"):
		quotation.custom_delivery_date = delivery_date
	quotation.flags.ignore_permissions = True
	quotation.save()
	return {"name": quotation.name, "delivery_date": str(delivery_date)}


@frappe.whitelist()
def update_cart_line_code(line_code=None):
	"""Cart-level Line Code. Persists on Quotation.custom_line_code (or
	Sales Order.custom_line_code) so the label flows through to the saved
	document. Sidebar-style edit, no pricing/stock revalidation needed."""
	quotation = _get_cart_quotation()
	if not quotation.meta.has_field("custom_line_code"):
		frappe.throw(_("Line Code field is not configured on this cart."))

	value = (line_code or "").strip() or None
	frappe.db.set_value(
		quotation.doctype, quotation.name, "custom_line_code", value, update_modified=False
	)
	return {"name": quotation.name, "line_code": value or ""}


@frappe.whitelist()
def update_cart_delivery_point(delivery_point):
	quotation = _get_cart_quotation()
	if not quotation.meta.has_field("custom_delivery_point"):
		frappe.throw(_("Delivery Point field is not configured on this cart."))

	if delivery_point and not frappe.db.exists("Delivery Points", delivery_point):
		frappe.throw(_("Delivery Point {0} does not exist.").format(delivery_point))

	quotation.custom_delivery_point = delivery_point or None
	quotation.flags.ignore_permissions = True
	quotation.save()
	return {"name": quotation.name, "delivery_point": delivery_point or ""}


@frappe.whitelist()
def search_delivery_points(txt=None, limit=20):
	"""Storefront Link-search for the cart's Delivery Point field.

	Customers logging in via the webshop don't usually have any role with read
	access to Delivery Points, so the standard Link autocomplete returns nothing.
	This whitelisted helper ignores permissions and returns name + label."""
	if not _get_cart_quotation():
		return []

	conditions = ""
	args = {"txt": f"%{txt or ''}%", "limit": int(limit) if limit else 20}
	if txt:
		conditions = "WHERE name LIKE %(txt)s"

	rows = frappe.db.sql(
		f"""
		SELECT name FROM `tabDelivery Points`
		{conditions}
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		args,
		as_dict=True,
	)
	return [{"value": r.name, "label": r.name, "description": ""} for r in rows]


@frappe.whitelist()
def update_cart_box_type(box_type):
	"""Cart-level Box Type. Saves on Quotation.custom_box_type and overwrites
	every Quotation Item's custom_box_type so pricing / min_order_qty derive
	from the single cart-level choice."""
	quotation = _get_cart_quotation()
	if not quotation.meta.has_field("custom_box_type"):
		frappe.throw(_("Box Type field is not configured on this cart."))

	if box_type and not frappe.db.exists("Box Type", box_type):
		frappe.throw(_("Box Type {0} does not exist.").format(box_type))

	value = box_type or None
	quotation.custom_box_type = value

	child_dt = "Sales Order Item" if quotation.doctype == "Sales Order" else "Quotation Item"
	propagate = frappe.db.has_column(child_dt, "custom_box_type")
	if propagate:
		for item in quotation.get("items", []):
			item.custom_box_type = value

	quotation.flags.ignore_permissions = True
	quotation.save()
	# Box type drives pricing on per-row flows (pack rate / min_order_qty), so
	# reload the cart page to pick up recomputed line totals.
	return {"name": quotation.name, "box_type": box_type or "", "reload": bool(propagate)}


@frappe.whitelist()
def search_box_types(txt=None, limit=20):
	"""Storefront Link-search for the cart's Box Type field. Mirrors
	search_delivery_points — webshop customers don't usually have read access
	to the Box Type doctype, so bypass permissions and return name + label."""
	if not _get_cart_quotation():
		return []

	conditions = ""
	args = {"txt": f"%{txt or ''}%", "limit": int(limit) if limit else 20}
	if txt:
		conditions = "WHERE name LIKE %(txt)s"

	rows = frappe.db.sql(
		f"""
		SELECT name FROM `tabBox Type`
		{conditions}
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		args,
		as_dict=True,
	)
	return [{"value": r.name, "label": r.name, "description": ""} for r in rows]


@frappe.whitelist()
def get_item_price_for_configure(item_code):
	"""Return per-stem price for a variant item, used in the configure dialog."""
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	price_list = cart_settings.price_list

	try:
		party = get_party()
		if party:
			from erpnext.accounts.party import get_default_price_list
			customer_pl = get_default_price_list(party)
			if customer_pl:
				price_list = customer_pl
	except Exception:
		pass

	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")

	price = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "uom": stock_uom},
		["price_list_rate", "currency"],
		as_dict=True,
	)

	if not price:
		price = frappe.db.get_value(
			"Item Price",
			{"item_code": item_code, "price_list": price_list},
			["price_list_rate", "currency"],
			as_dict=True,
		)

	return price or {}
