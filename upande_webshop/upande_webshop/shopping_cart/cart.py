# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
import frappe.defaults
from frappe import _, throw
from frappe.contacts.doctype.address.address import get_address_display
from frappe.contacts.doctype.contact.contact import get_contact_name
from frappe.utils import cint, cstr, flt, get_fullname
from frappe.utils.nestedset import get_root_of

from erpnext.accounts.utils import get_account_name
from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
    get_shopping_cart_settings,
)
from upande_webshop.upande_webshop.utils.product import get_web_item_qty_in_stock
from erpnext.selling.doctype.quotation.quotation import _make_sales_order


class WebsitePriceListMissingError(frappe.ValidationError):
    pass


def set_cart_count(quotation=None):
	if cint(frappe.db.get_singles_value("Webshop Settings", "enabled")):
		if not quotation:
			quotation = _get_cart_quotation()
		cart_count = cstr(cint(quotation.get("total_qty")))

		if hasattr(frappe.local, "cookie_manager"):
			frappe.local.cookie_manager.set_cookie("cart_count", cart_count)



def _get_transit_days_for_party(party=None):
        """Get transit days from Customer record. Returns int (default 2)."""
        if not party:
                party = get_party()
        if party and party.doctype == "Customer":
                transit_days = frappe.db.get_value("Customer", party.name, "custom_transit_days")
                if transit_days:
                        return cint(transit_days)
        return 2


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

	return {
		"doc": decorate_quotation_doc(doc),
		"shipping_addresses": get_shipping_addresses(party),
		"billing_addresses": get_billing_addresses(party),
		"shipping_rules": get_applicable_shipping_rules(party),
		"cart_settings": frappe.get_cached_doc("Webshop Settings"),
		"transit_days": _get_transit_days_for_party(party),
	}


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
	"""Return error message (string) if any line fails the box-type minimum, else None."""
	min_qty_cache = {}
	for item in quotation.get("items") or []:
		box_type = getattr(item, "custom_box_type", None)
		if not box_type:
			return _("{0} ({1}) has no Box Type selected. Please remove the line and re-add it with a Box Type.").format(
				item.item_code, item.custom_length or _("no length")
			)
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


@frappe.whitelist()
def place_order():
	quotation = _get_cart_quotation()
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

	if not cint(cart_settings.allow_items_not_in_stock):
		for item in sales_order.get("items"):
			item.warehouse = frappe.db.get_value(
				"Website Item", {"item_code": item.item_code}, "website_warehouse"
			)
			is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")

			if is_stock_item:
				item_stock = get_web_item_qty_in_stock(
					item.item_code, "website_warehouse"
				)
				if not cint(item_stock.in_stock):
					throw(_("{0} Not in Stock").format(item.item_code))
				if item.qty > item_stock.stock_qty:
					throw(
						_("Only {0} in Stock for item {1}").format(
							item_stock.stock_qty, item.item_code
						)
					)

	sales_order.flags.ignore_permissions = True
	sales_order.insert()
	sales_order.submit()

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return sales_order.name


@frappe.whitelist()
def request_for_quotation():
	quotation = _get_cart_quotation()
	box_err = _check_box_type_min_order_qty(quotation)
	if box_err:
		return {"error": box_err}
	quotation.flags.ignore_permissions = True
	quotation.flags.ignore_validate = True
	quotation.save()
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


def _apply_length_price_db(quotation):
	"""After quotation.save(), directly update rate/amount in DB for length-priced items.
	This bypasses ERPNext's calculate_taxes_and_totals which overwrites our values.
	Item Price.price_list_rate is already per-stem.
	qty is in bunches; stock_qty = qty × conversion_factor = total stems.
	rate = per_stem price, amount = per_stem × total_stems.
	"""
	price_list = quotation.selling_price_list
	currency = quotation.currency
	net_total = flt(0)
	any_changed = False

	for item in quotation.get("items"):
		# Derive conversion_factor from the UOM name (e.g. "Bunch (15)" → 15).
		# This is the authoritative source — UOM Conversion Detail may be missing entries
		# and ERPNext resets conversion_factor to 1 during calculate_taxes_and_totals.
		cf = flt(_stems_per_bunch_from_uom(item.uom)) if item.uom else flt(item.conversion_factor or 1)
		item.conversion_factor = cf
		total_stems = flt(item.qty) * cf
		if item.name:
			per_stem = _get_per_stem_rate(item.item_code, item.custom_length, currency, price_list, uom=item.uom)
			db_fields = {"conversion_factor": cf, "stock_qty": total_stems, "custom_total_stems": total_stems}
			item.stock_qty = total_stems
			item.custom_total_stems = total_stems
			if per_stem is not None:
				amount = flt(per_stem * total_stems, 9)
				db_fields.update({"rate": per_stem, "amount": amount})
				item.rate = per_stem
				item.amount = amount
				any_changed = True
			frappe.db.set_value("Quotation Item", item.name, db_fields, update_modified=False)
		net_total += flt(item.amount)

	if any_changed:
		# Update quotation-level totals in DB and in-memory so template context is correct
		frappe.db.set_value(
			"Quotation", quotation.name,
			{"total": net_total, "net_total": net_total, "grand_total": net_total},
			update_modified=False
		)
		quotation.total = net_total
		quotation.net_total = net_total
		quotation.grand_total = net_total


@frappe.whitelist()
def update_cart(item_code, qty, additional_notes=None, uom=None, custom_length=None, custom_box_type=None, with_items=False, child_docname=None):
	quotation = _get_cart_quotation()

	empty_card = False
	qty = flt(qty)

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

		# Match by child_docname (update), or by item_code + custom_length + uom (existing row), else append new
		if child_docname:
			matched = [i for i in quotation.get("items") if i.name == child_docname]
		else:
			matched = [
				i for i in quotation.get("items")
				if i.item_code == item_code
				and (i.custom_length or "") == (custom_length or "")
				and (i.uom or "") == (uom or "")
			]

		if not matched:
			# New combination — append a new row
			if not uom:
				uom = frappe.db.get_value("Item", item_code, "stock_uom")
			# Parse stems from UOM name (e.g. "Bunch (15)" → 15) as primary source.
			# UOM Conversion Detail may be missing entries for custom bunch UOMs.
			conversion_factor = flt(_stems_per_bunch_from_uom(uom))
			total_stems = qty * conversion_factor
			quotation.append(
				"items",
				{
					"doctype": "Quotation Item",
					"item_code": item_code,
					"qty": qty,
					"uom": uom,
					"conversion_factor": conversion_factor,
					"stock_qty": total_stems,
					"custom_total_stems": total_stems,
					"custom_length": custom_length,
					"custom_box_type": custom_box_type,
					"additional_notes": additional_notes,
					"warehouse": warehouse,
				},
			)
		else:
			item = matched[0]
			item.qty = qty
			if uom:
				item.uom = uom
			if custom_length:
				item.custom_length = custom_length
			if custom_box_type:
				item.custom_box_type = custom_box_type
			item.warehouse = warehouse
			item.additional_notes = additional_notes
			total_stems = qty * flt(item.conversion_factor or 1)
			item.stock_qty = total_stems
			item.custom_total_stems = total_stems

	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.flags.ignore_validate = True
	quotation.payment_schedule = []
	if not empty_card:
		quotation.save()
		_apply_length_price_db(quotation)
	else:
		frappe.delete_doc("Quotation", quotation.name, ignore_permissions=True, force=True)
		quotation = None

	set_cart_count(quotation)

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
		}
	else:
		return {"name": quotation.name}


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
	"""Return the open Quotation of type "Shopping Cart" or make a new one"""
	if not party:
		party = get_party()

	quotation = frappe.get_all(
		"Quotation",
		fields=["name"],
		filters={
			"party_name": party.name,
			"contact_email": frappe.session.user,
			"order_type": "Shopping Cart",
			"docstatus": 0,
		},
		order_by="modified desc",
		limit_page_length=1,
	)

	if quotation:
		qdoc = frappe.get_doc("Quotation", quotation[0].name)
	else:
		company = frappe.db.get_single_value("Webshop Settings", "company")
		qdoc = frappe.get_doc(
			{
				"doctype": "Quotation",
				"naming_series": get_shopping_cart_settings().quotation_series
				or "QTN-CART-",
				"quotation_to": party.doctype,
				"company": company,
				"order_type": "Shopping Cart",
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

	party_name = quotation.get("party_name") if quotation else get_party().get("name")
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

	customer_group = frappe.db.get_value(
		"Customer", quotation.party_name, "customer_group"
	)

	quotation.taxes_and_charges = set_taxes(
		quotation.party_name,
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
		if contact.links:
			party_doctype = contact.links[0].link_doctype
			party = contact.links[0].link_name

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
	quotation = _get_cart_quotation()
	quotation.delivery_date = delivery_date
	quotation.flags.ignore_permissions = True
	quotation.save()
	return {"name": quotation.name}

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
