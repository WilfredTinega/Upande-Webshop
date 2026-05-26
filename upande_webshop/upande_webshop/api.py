import json

import frappe
from frappe.utils import cint

from upande_webshop.upande_webshop.product_data_engine.filters import ProductFiltersBuilder
from upande_webshop.upande_webshop.product_data_engine.query import ProductQuery
from upande_webshop.upande_webshop.doctype.override_doctype.item_group import get_child_groups_for_website


@frappe.whitelist(allow_guest=True)
def get_product_filter_data(query_args=None):
	"""
	Returns filtered products and discount filters.

	Args:
		query_args (dict): contains filters to get products list

	Query Args filters:
		search (str): Search Term.
		field_filters (dict): Keys include item_group, brand, etc.
		attribute_filters(dict): Keys include Color, Size, etc.
		start (int): Offset items by
		item_group (str): Valid Item Group
		from_filters (bool): Set as True to jump to page 1
	"""
	if isinstance(query_args, str):
		query_args = json.loads(query_args)

	query_args = frappe._dict(query_args or {})

	if query_args:
		search = query_args.get("search")
		field_filters = query_args.get("field_filters", {})
		attribute_filters = query_args.get("attribute_filters", {})
		start = cint(query_args.start) if query_args.get("start") else 0
		item_group = query_args.get("item_group")
		from_filters = query_args.get("from_filters")
	else:
		search, attribute_filters, item_group, from_filters = None, None, None, None
		field_filters = {}
		start = 0

	# if new filter is checked, reset start to show filtered items from page 1
	if from_filters:
		start = 0

	sub_categories = []
	if item_group:
		sub_categories = get_child_groups_for_website(item_group, immediate=True)

	engine = ProductQuery()

	try:
		result = engine.query(
			attribute_filters,
			field_filters,
			search_term=search,
			start=start,
			item_group=item_group,
		)
	except Exception:
		frappe.log_error("Product query with filter failed")
		return {"exc": "Something went wrong!"}

	# discount filter data
	filters = {}
	discounts = result["discounts"]

	if discounts:
		filter_engine = ProductFiltersBuilder()
		filters["discount_filters"] = filter_engine.get_discount_filters(discounts)

	return {
		"items": result["items"] or [],
		"filters": filters,
		"settings": engine.settings,
		"sub_categories": sub_categories,
		"items_count": result["items_count"],
	}


@frappe.whitelist(allow_guest=True)
def get_guest_redirect_on_action():
	return frappe.db.get_single_value("Webshop Settings", "redirect_on_action")


@frappe.whitelist()
def get_post_login_redirect():
	"""Return the correct redirect URL after login based on the user's role.
	Customers go to /webshop; all other roles go to /app (desk).
	"""
	if "Customer" in frappe.get_roles(frappe.session.user):
		return "/webshop"
	return "/app"

@frappe.whitelist(allow_guest=True)
def get_box_items():
	"""Return only BOX items from PACKAGING group for the box type dropdown."""
	items = frappe.db.get_all(
		"Item",
		filters={"item_group": "PACKAGING", "disabled": 0, "item_name": ["like", "%BOX%"]},
		fields=["name", "item_name"],
		order_by="item_name asc"
	)
	return items

@frappe.whitelist(allow_guest=True)
def get_pack_rate(item_code):
	"""Return default_pack_rate for a variant item."""
	rate = frappe.db.get_value("Item", item_code, "default_pack_rate")
	return {"default_pack_rate": rate or 0}


@frappe.whitelist(allow_guest=True)
def get_pack_rates_map():
	"""
	Return all Pack Rate records as a nested map:
	    { variety_lowercase: { box_key: { length_cm: stems_per_box } } }
	box_key is 'std' for Standard, 'zim' for Zim — matching item_configure.js.
	"""
	rows = frappe.get_all(
		"Pack Rate",
		fields=["variety", "box_group", "length_cm", "stems_per_box"],
	)
	box_key_map = {"Standard": "std", "Zim": "zim"}
	result = {}
	for r in rows:
		variety = (r.variety or "").lower().strip()
		box_key = box_key_map.get(r.box_group)
		if not variety or not box_key or not r.length_cm:
			continue
		result.setdefault(variety, {}).setdefault(box_key, {})[int(r.length_cm)] = int(
			r.stems_per_box or 0
		)
	return result

@frappe.whitelist()
def get_customer_boxes():
	"""
	Return allowed boxes for the logged-in customer.
	If customer has specific boxes assigned, return those only.
	Otherwise return all BOX items (general customers).
	"""
	user = frappe.session.user

	if user and user != "Guest":
		# Resolve user -> contact -> customer
		contact_name = frappe.db.get_value("Contact", {"email_id": user})
		if contact_name:
			customer_name = frappe.db.get_value("Dynamic Link", {
				"parenttype": "Contact",
				"parent": contact_name,
				"link_doctype": "Customer"
			}, "link_name")

			if customer_name:
				# Check if customer has specific boxes assigned
				allowed = frappe.db.get_all(
					"Customer Allowed Box",
					filters={"parent": customer_name, "parenttype": "Customer"},
					fields=["box_item"]
				)
				if allowed:
					# Fetch item_name for each allowed box
					boxes = []
					for row in allowed:
						item_name = frappe.db.get_value("Item", row.box_item, "item_name")
						if item_name:
							boxes.append({"name": row.box_item, "item_name": item_name})
					return boxes

	# Fallback — return all BOX items for general customers
	return frappe.db.get_all(
		"Item",
		filters={"item_group": "PACKAGING", "disabled": 0, "item_name": ["like", "%BOX%"]},
		fields=["name", "item_name"],
		order_by="item_name asc"
	)


@frappe.whitelist(allow_guest=True)
def get_box_min_order_qty(box_name):
	"""
	Resolve the MOQ (in bunches) for a box, sourced from Box Type.min_order_qty.

	`box_name` is the value selected in the configurator dropdown — currently the
	Item item_name (e.g. 'STD-EB BOX'). Match by Box Type primary key first,
	then by box_type_name; finally try a startswith match so 'STD-EB BOX' resolves
	to Box Type 'STD-EB'. Returns {min_order_qty: float} (0 if no match).
	"""
	if not box_name:
		return {"min_order_qty": 0}

	moq = frappe.db.get_value("Box Type", box_name, "min_order_qty")
	if moq is None:
		moq = frappe.db.get_value("Box Type", {"box_type_name": box_name}, "min_order_qty")
	if moq is None:
		first_token = box_name.split()[0] if box_name else ""
		if first_token:
			moq = frappe.db.get_value("Box Type", first_token, "min_order_qty")

	return {"min_order_qty": float(moq or 0)}
