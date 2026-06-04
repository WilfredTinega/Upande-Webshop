import json

import frappe
from frappe import _
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


def _user_can_see_all_customers(user=None):
	"""Only administrators may transact for any customer.

	Every other user — including sales reps who happen to hold Sales roles — is
	limited to the customers they're linked to via Customer.portal_users, so the
	Add-to-Cart / Reserve dialog shows that user's own customers alone.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return "System Manager" in frappe.get_roles(user)


def _user_portal_customers(user=None, term=None, limit=20):
	"""Customers where `user` is listed in Customer.portal_users.

	Returns a list of customer names. Optionally filters by a search `term`
	(matched against customer name) and caps the result size.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return []

	filters = {"user": user, "parenttype": "Customer"}
	parents = frappe.get_all(
		"Portal User", filters=filters, fields=["parent"], pluck="parent"
	)
	if not parents:
		return []
	parents = list(dict.fromkeys(parents))  # dedupe, preserve order

	cust_filters = {"name": ["in", parents]}
	if term:
		cust_filters["customer_name"] = ["like", f"%{term}%"]
	return frappe.get_all(
		"Customer",
		filters=cust_filters,
		fields=["name"],
		order_by="customer_name asc",
		limit_page_length=limit,
		pluck="name",
	)


def _assert_customer_allowed(customer, user=None):
	"""Block portal users from transacting for a customer they aren't linked to.

	Privileged internal staff bypass this. Mirrors the dropdown filtering in
	get_portal_customers so the restriction is enforced, not merely cosmetic.
	"""
	user = user or frappe.session.user
	if _user_can_see_all_customers(user):
		return
	allowed = frappe.db.exists(
		"Portal User", {"parent": customer, "parenttype": "Customer", "user": user}
	)
	if not allowed:
		frappe.throw(
			_("You are not authorised to transact for customer {0}.").format(customer),
			frappe.PermissionError,
		)


@frappe.whitelist()
def get_product_overview_cart_count():
	"""Total item qty across the user's open draft-SO carts (all customers).

	Powers the cart badge on Product Overview. Counts every open Shopping Cart
	Sales Order created by this user, summed across customers.
	"""
	user = frappe.session.user
	if user == "Guest":
		return {"count": 0}
	totals = frappe.get_all(
		"Sales Order",
		filters={"contact_email": user, "order_type": "Shopping Cart", "docstatus": 0},
		fields=["total_qty"],
	)
	count = sum(int(t.total_qty or 0) for t in totals)
	return {"count": count}


@frappe.whitelist()
def get_portal_customers(term=None):
	"""Customer list for the Product Overview Add-to-Cart / Reserve dialogs.

	Portal users (sales reps) see ONLY the customers they're linked to via
	Customer.portal_users. Privileged internal staff see all customers, matching
	the previous behaviour. Returns a list of customer names.
	"""
	user = frappe.session.user
	if user == "Guest":
		return []

	if _user_can_see_all_customers(user):
		filters = [["customer_name", "like", f"%{term}%"]] if term else []
		return frappe.get_all(
			"Customer",
			filters=filters,
			fields=["name"],
			order_by="modified desc",
			limit_page_length=20,
			pluck="name",
		)

	return _user_portal_customers(user, term=term, limit=500)


@frappe.whitelist()
def set_user_profile_image(file_url):
	"""Store a profile image URL on the currently logged-in User."""
	if not frappe.session.user or frappe.session.user == "Guest":
		frappe.throw(_("You must be logged in to update your profile image."), frappe.PermissionError)

	if not file_url:
		frappe.throw(_("No profile image was provided."))

	frappe.db.set_value("User", frappe.session.user, "user_image", file_url, update_modified=False)
	frappe.db.commit()
	return {"user_image": file_url}


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

	# Box Type may not carry min_order_qty on every site — guard the read.
	if not frappe.get_meta("Box Type").has_field("min_order_qty"):
		return {"min_order_qty": 0}

	moq = frappe.db.get_value("Box Type", box_name, "min_order_qty")
	if moq is None:
		moq = frappe.db.get_value("Box Type", {"box_type_name": box_name}, "min_order_qty")
	if moq is None:
		first_token = box_name.split()[0] if box_name else ""
		if first_token:
			moq = frappe.db.get_value("Box Type", first_token, "min_order_qty")

	return {"min_order_qty": float(moq or 0)}


def _product_overview_warehouses(settings):
	"""Warehouses to render as columns on the Product Overview page.

	Sourced from Webshop Settings → Stock tab → Warehouses child table, in row
	order, deduped. Group warehouses are NOT expanded — the admin picks the
	display buckets they want shown.
	"""
	seen = []
	for row in settings.get("warehouses") or []:
		wh = row.get("warehouse") if isinstance(row, dict) else row.warehouse
		if wh and wh not in seen:
			seen.append(wh)
	return seen


def _sales_bunch_uom(item_code):
	"""Resolve an item's selling UOM (a bunch) and its stems-per-bunch factor.

	Product Overview lets users transact in bunches — the natural sales unit —
	while stock and the Stem Length Bin are tracked in stems. Returns
	(uom, stems_per_bunch). Prefers Item.sales_uom; falls back to stock_uom.
	The conversion factor is parsed from the UOM name (e.g. 'Bunch (10)' → 10),
	matching the cart's authoritative source `_stems_per_bunch_from_uom`.
	"""
	from upande_webshop.upande_webshop.shopping_cart.cart import (
		_stems_per_bunch_from_uom,
	)

	item = frappe.db.get_value(
		"Item", item_code, ["sales_uom", "stock_uom"], as_dict=True
	) or frappe._dict()
	uom = item.get("sales_uom") or item.get("stock_uom") or "Nos"
	stems_per_bunch = _stems_per_bunch_from_uom(uom) or 1
	return uom, stems_per_bunch


def _available_for_sale_stems(item_code, warehouse, stem_length, exclude_so=None):
	"""Available-for-sale stems = Stem Length Bin actual_qty − reserved_qty.

	This is the same "available" figure the Product Overview grid shows, with
	the same draft-cart netting: stems sitting in OTHER open draft Shopping-Cart
	Sales Orders are subtracted too (Add to Cart doesn't reserve in the bin).
	`exclude_so` skips one Sales Order from that netting — pass the cart currently
	being appended to, so its own lines aren't double-counted (the caller adds
	them separately). Returns 0 when no bin row exists. Variant/template items
	aren't tracked here (their per-length qty lives in core Bin); callers gate on
	plain items.
	"""
	from frappe.utils import flt

	row = frappe.db.get_value(
		"Stem Length Bin",
		{"item_code": item_code, "warehouse": warehouse, "stem_length": stem_length},
		["actual_qty", "reserved_qty"],
		as_dict=True,
	)
	if not row:
		return 0.0
	available = flt(row.actual_qty) - flt(row.reserved_qty)
	committed = _draft_cart_committed_stems_for_cell(
		item_code, warehouse, stem_length, exclude_so=exclude_so
	)
	return max(0.0, available - committed)


def _draft_cart_committed_stems_for_cell(
	item_code, warehouse, stem_length, exclude_so=None
):
	"""Stems for ONE cell parked in open draft Shopping-Cart Sales Orders.

	Single-cell counterpart of `_draft_cart_committed_stems` (which sweeps all
	cells for the matrix). Used by the server-side stock-cap guard so re-adds
	can't exceed what's truly free. `exclude_so` drops one cart from the sum.
	"""
	from frappe.utils import flt

	has_length = frappe.db.has_column("Sales Order Item", "custom_length")
	if not has_length:
		return 0.0
	has_total = frappe.db.has_column("Sales Order Item", "custom_total_stems")
	has_src_wh = frappe.db.has_column("Sales Order Item", "custom_source_warehouse")

	src_wh = "soi.custom_source_warehouse" if has_src_wh else "soi.warehouse"
	stems_expr = (
		"COALESCE(NULLIF(soi.custom_total_stems, 0), soi.qty * COALESCE(soi.conversion_factor, 1))"
		if has_total
		else "soi.qty * COALESCE(soi.conversion_factor, 1)"
	)
	conditions = [
		"so.docstatus = 0",
		"so.order_type = 'Shopping Cart'",
		"soi.item_code = %(item_code)s",
		"soi.custom_length = %(stem_length)s",
		f"{src_wh} = %(warehouse)s",
	]
	params = {
		"item_code": item_code,
		"stem_length": stem_length,
		"warehouse": warehouse,
	}
	if exclude_so:
		conditions.append("so.name != %(exclude_so)s")
		params["exclude_so"] = exclude_so

	row = frappe.db.sql(
		f"""
		SELECT SUM({stems_expr}) AS stems
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE {' AND '.join(conditions)}
		""",
		params,
		as_dict=True,
	)
	return flt(row[0]["stems"]) if row and row[0] else 0.0


def _assert_stock_available(
	item_code, warehouse, stem_length, want_stems, exclude_so=None
):
	"""Throw if `want_stems` exceeds available-for-sale stock in this warehouse.

	Enforces the storefront's "can't order more than is in stock" rule on the
	server, so it holds even if the client-side cap is bypassed. Skipped for
	variant/template items (not tracked in Stem Length Bin). `exclude_so` is
	passed through to the availability check so the cart being appended to isn't
	double-counted against itself.
	"""
	from frappe.utils import flt

	is_variant = frappe.db.get_value("Item", item_code, "variant_of")
	has_variants = frappe.db.get_value("Item", item_code, "has_variants")
	if is_variant or has_variants:
		return  # core Bin tracks these; Stem Length Bin doesn't

	available = _available_for_sale_stems(
		item_code, warehouse, stem_length, exclude_so=exclude_so
	)
	if flt(want_stems) > available:
		frappe.throw(
			_(
				"Only {0} stems available for {1} ({2}) in {3}. You requested {4}."
			).format(
				int(available), item_code, stem_length, warehouse, int(flt(want_stems))
			),
			title=_("Not enough stock"),
		)


@frappe.whitelist()
def get_product_overview_rows():
	"""Return rows for the Product Overview page.

	One entry per published Website Item (the "variety"). Each entry holds rows
	keyed by Stem Length with per-warehouse actual_qty against the warehouses
	configured in Webshop Settings → Stock → Warehouses.

	Source of truth is Website Item — every published variety is listed, even
	if it has no Stem Length Bin rows yet. Stock data comes from Stem Length
	Bin for plain items (the only source that tracks per-length qty); template
	items appear with their variants' lengths summed across core Bin.
	"""
	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.get("show_product_overview"):
		frappe.throw(_("Product Overview is disabled."))

	warehouses = _product_overview_warehouses(settings)
	if not warehouses:
		return []
	wh_count = len(warehouses)
	wh_idx = {wh: i for i, wh in enumerate(warehouses)}

	items = frappe.get_all(
		"Website Item",
		filters={"published": 1},
		fields=["item_code", "web_item_name", "item_name", "has_variants", "route"],
		order_by="web_item_name asc",
	)
	if not items:
		return []

	plain_codes = [i.item_code for i in items if not i.has_variants]
	template_codes = [i.item_code for i in items if i.has_variants]

	bins = []
	if plain_codes:
		bins = frappe.db.get_all(
			"Stem Length Bin",
			filters={
				"item_code": ("in", plain_codes),
				"warehouse": ("in", warehouses),
			},
			fields=["item_code", "warehouse", "stem_length", "actual_qty", "reserved_qty"],
		)

	variant_rows = []
	variant_to_template = {}
	if template_codes:
		variants = frappe.get_all(
			"Item",
			filters={"variant_of": ("in", template_codes)},
			fields=["name", "variant_of", "custom_length"]
			if frappe.db.has_column("Item", "custom_length")
			else ["name", "variant_of"],
		)
		variant_to_template = {v.name: v.variant_of for v in variants}
		variant_length = {v.name: v.get("custom_length") for v in variants}
		if variants:
			core_bins = frappe.db.get_all(
				"Bin",
				filters={
					"item_code": ("in", [v.name for v in variants]),
					"warehouse": ("in", warehouses),
				},
				fields=["item_code", "warehouse", "actual_qty", "reserved_qty"],
			)
			for cb in core_bins:
				variant_rows.append(
					frappe._dict(
						{
							"item_code": variant_to_template.get(cb.item_code),
							"warehouse": cb.warehouse,
							"stem_length": variant_length.get(cb.item_code),
							"actual_qty": cb.actual_qty,
							"reserved_qty": cb.reserved_qty,
						}
					)
				)

	all_rows = list(bins) + variant_rows

	stem_length_names = list({b.stem_length for b in all_rows if b.stem_length})
	stem_meta = {}
	if stem_length_names and frappe.db.exists("DocType", "Stem Length"):
		for row in frappe.db.get_all(
			"Stem Length",
			filters={"name": ("in", stem_length_names)},
			fields=["name", "length"],
		):
			stem_meta[row.name] = row

	by_item = {}
	for b in all_rows:
		if not b.item_code or not b.stem_length:
			continue
		entry = by_item.setdefault(b.item_code, {})
		row = entry.setdefault(
			b.stem_length,
			{
				"stem_length": b.stem_length,
				"stem_length_label": _stem_length_label(b.stem_length, stem_meta),
				"warehouse_qty": [0] * wh_count,
				"_sort_key": _stem_length_sort_key(b.stem_length, stem_meta),
			},
		)
		idx = wh_idx.get(b.warehouse)
		if idx is None:
			continue
		# Show available for sale = actual − reserved (the bin's projected_qty),
		# so reserved-but-unshipped stems aren't counted as sellable. Clamp at 0
		# to never surface a negative from a reservation overshoot.
		available = float(b.actual_qty or 0) - float(b.get("reserved_qty") or 0)
		if available < 0:
			available = 0
		row["warehouse_qty"][idx] += available

	# Sales UOM (bunch) + stems-per-bunch per item — the dialog transacts in
	# bunches, so the qty input is labelled with this and qty is multiplied up
	# to stems server-side. Batched to avoid a query per item.
	from upande_webshop.upande_webshop.shopping_cart.cart import (
		_stems_per_bunch_from_uom,
	)

	uom_meta = {}
	if items:
		for u in frappe.db.get_all(
			"Item",
			filters={"item_code": ("in", [i.item_code for i in items])},
			fields=["item_code", "sales_uom", "stock_uom"],
		):
			uom = u.sales_uom or u.stock_uom or "Nos"
			uom_meta[u.item_code] = (uom, _stems_per_bunch_from_uom(uom) or 1)

	out = []
	for item in items:
		entry = by_item.get(item.item_code) or {}
		rows = [
			r for r in entry.values()
			if sum(r["warehouse_qty"]) > 0
		]
		for r in rows:
			r.pop("_sort_key", None)
			# Per-tile total — the grid renders one tile per row, so this is what
			# the tiles are sorted by (see the global tile sort below / in JS).
			r["stock"] = sum(r["warehouse_qty"])
		if not rows:
			continue
		# Rows within a variety, biggest tile first.
		rows.sort(key=lambda r: -r["stock"])
		uom, stems_per_bunch = uom_meta.get(item.item_code, ("Nos", 1))
		total_stock = sum(r["stock"] for r in rows)
		out.append(
			{
				"item_code": item.item_code,
				"variety": item.web_item_name or item.item_name or item.item_code,
				"route": item.route or "",
				"sales_uom": uom,
				"stems_per_bunch": stems_per_bunch,
				"total_stock": total_stock,
				# Largest single tile in this variety — orders varieties so the
				# one holding the biggest tile leads (matches global tile sort).
				"max_row_stock": rows[0]["stock"],
				"rows": rows,
			}
		)

	# Order varieties by their largest single tile, descending — so when the grid
	# flattens to tiles, the biggest tiles lead globally. Ties → variety name.
	out.sort(key=lambda i: (-i["max_row_stock"], i["variety"].lower()))
	return out


def _stem_length_label(stem_length, stem_meta):
	row = stem_meta.get(stem_length)
	if row and row.length:
		try:
			val = float(row.length)
		except (TypeError, ValueError):
			return str(row.length)
		return f"{int(val) if val.is_integer() else val} cm"
	return stem_length


def _stem_length_sort_key(stem_length, stem_meta):
	row = stem_meta.get(stem_length)
	if row and row.length is not None:
		try:
			return (0, float(row.length))
		except (TypeError, ValueError):
			pass
	return (1, stem_length or "")


@frappe.whitelist()
def reserve_stems_for_customer(
	item_code, stem_length, warehouse, qty, customer, portal_contact=None
):
	"""Create a draft Sales Order reserving `qty` stems for `customer`.

	Bumps Stem Length Bin.reserved_qty via the existing tracker. Never throws on
	insufficient stock (the tracker is passive) — the SO itself is the source of
	truth for the reservation. Returns the SO name.
	"""
	from frappe.utils import flt

	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.get("show_product_overview"):
		frappe.throw(_("Product Overview is disabled."))

	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Quantity must be greater than zero."))
	if not (item_code and stem_length and warehouse and customer):
		frappe.throw(_("Missing required values."))

	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer))
	if not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(_("Warehouse {0} not found.").format(warehouse))
	_assert_customer_allowed(customer)

	company = settings.get("company") or frappe.defaults.get_user_default("company")
	if not company:
		frappe.throw(_("Webshop Settings → Company is not set."))

	from erpnext.accounts.party import get_party_account_currency

	currency = (
		get_party_account_currency("Customer", customer, company)
		or frappe.db.get_value("Company", company, "default_currency")
	)

	so = frappe.new_doc("Sales Order")
	so.customer = customer
	so.company = company
	so.currency = currency
	so.transaction_date = frappe.utils.nowdate()
	so.delivery_date = frappe.utils.add_days(frappe.utils.nowdate(), 7)
	if portal_contact and frappe.db.exists("Contact", portal_contact):
		so.contact_person = portal_contact
	so.order_type = "Sales"

	# qty is entered in bunches (the item's sales UOM); stems = qty × stems/bunch.
	sales_uom, stems_per_bunch = _sales_bunch_uom(item_code)
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
	total_stems = qty * stems_per_bunch
	# Don't reserve more than is available for sale in this warehouse.
	_assert_stock_available(item_code, warehouse, stem_length, total_stems)
	row = {
		"item_code": item_code,
		"qty": qty,
		"uom": sales_uom,
		"stock_uom": stock_uom,
		"conversion_factor": stems_per_bunch,
		"warehouse": warehouse,
		"delivery_date": so.delivery_date,
	}
	if frappe.db.has_column("Sales Order Item", "custom_length"):
		row["custom_length"] = stem_length
	if frappe.db.has_column("Sales Order Item", "custom_total_stems"):
		row["custom_total_stems"] = total_stems
	# Tambuzi's pick-list automation requires a source warehouse per line on
	# submit; the warehouse picked on Product Overview is that source.
	if frappe.db.has_column("Sales Order Item", "custom_source_warehouse"):
		row["custom_source_warehouse"] = warehouse
	so.append("items", row)

	so.flags.ignore_permissions = True
	so.flags.ignore_mandatory = True
	# Storefront save: suppress interactive SO-hook msgprints (see add_to_cart).
	so.flags.webshop_cart_save = True
	so.insert(ignore_permissions=True)

	from upande_webshop.upande_webshop.doctype.stem_length_bin.stem_length_bin import (
		reserve_stem_length_qty,
	)

	reserve_stem_length_qty(item_code, warehouse, stem_length, total_stems)

	return {"sales_order": so.name}


@frappe.whitelist()
def get_product_overview_age_qty(item_code, age):
	"""Per-stem-length × per-warehouse qty for stems harvested `age` days ago.

	Reads the indexed Stem Length Age Bin (one row per item/warehouse/length/
	harvest_date), bucketing by days since harvest. `age` is an int; values >= 4
	mean "4 or more days". Returns {stem_length_doc_name: {warehouse: qty}}.
	The age bin already stores stem_length as the Stem Length doc name, so no
	string→doc mapping is needed.
	"""
	from frappe.utils import cint

	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.get("show_product_overview"):
		frappe.throw(_("Product Overview is disabled."))

	warehouses = _product_overview_warehouses(settings)
	if not warehouses or not item_code:
		return {}

	age = cint(age)
	age_clause = "days_ago >= %s" if age >= 4 else "days_ago = %s"
	wh_placeholders = ", ".join(["%s"] * len(warehouses))

	rows = frappe.db.sql(
		f"""
		SELECT stem_length, warehouse, SUM(qty) AS qty FROM (
			SELECT
				stem_length,
				warehouse,
				DATEDIFF(CURDATE(), harvest_date) AS days_ago,
				SUM(actual_qty) AS qty
			FROM `tabStem Length Age Bin`
			WHERE item_code = %s AND warehouse IN ({wh_placeholders})
			GROUP BY stem_length, warehouse, days_ago
		) t
		WHERE {age_clause}
		GROUP BY stem_length, warehouse
		""",
		[item_code, *warehouses, 4 if age >= 4 else age],
		as_dict=True,
	)

	out = {}
	for r in rows:
		stem_name = r.get("stem_length")
		if not stem_name:
			continue
		bucket = out.setdefault(stem_name, {})
		bucket[r["warehouse"]] = float(bucket.get(r["warehouse"], 0)) + float(r["qty"] or 0)
	return out


def _draft_cart_committed_stems(warehouses):
	"""Stems sitting in OPEN DRAFT Shopping-Cart Sales Orders, per cell.

	Add to Cart appends to a draft Sales Order but does NOT bump Stem Length
	Bin.reserved_qty (only SO submit reserves). So the bin's actual − reserved
	still counts those carted stems as available — and they'd re-appear as
	sellable when the Product Overview dialog is reopened. To honour "once it's
	in a cart, don't offer it again", subtract every open draft cart's lines
	here. Scope is ALL customers' draft carts (shared stock pool), not just the
	current user's.

	Returns {(item_code, stem_length, warehouse): committed_stems}. Lines come
	from draft (docstatus 0) Sales Orders with order_type "Shopping Cart". Stems
	per line = custom_total_stems when present, else qty × conversion_factor.
	Warehouse = custom_source_warehouse when present, else the line warehouse;
	length = custom_length.
	"""
	from frappe.utils import flt

	if not warehouses:
		return {}

	has_total = frappe.db.has_column("Sales Order Item", "custom_total_stems")
	has_length = frappe.db.has_column("Sales Order Item", "custom_length")
	if not has_length:
		# No per-length tracking on cart lines → can't map to a cell; nothing to net.
		return {}
	has_src_wh = frappe.db.has_column("Sales Order Item", "custom_source_warehouse")

	src_wh = "soi.custom_source_warehouse" if has_src_wh else "soi.warehouse"
	stems_expr = (
		"COALESCE(NULLIF(soi.custom_total_stems, 0), soi.qty * COALESCE(soi.conversion_factor, 1))"
		if has_total
		else "soi.qty * COALESCE(soi.conversion_factor, 1)"
	)
	wh_placeholders = ", ".join(["%s"] * len(warehouses))

	rows = frappe.db.sql(
		f"""
		SELECT soi.item_code AS item_code,
			soi.custom_length AS stem_length,
			{src_wh} AS warehouse,
			SUM({stems_expr}) AS stems
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE so.docstatus = 0
			AND so.order_type = 'Shopping Cart'
			AND soi.custom_length IS NOT NULL
			AND soi.custom_length != ''
			AND {src_wh} IN ({wh_placeholders})
		GROUP BY soi.item_code, soi.custom_length, {src_wh}
		""",
		[*warehouses],
		as_dict=True,
	)

	committed = {}
	for r in rows:
		if not r["item_code"] or not r["stem_length"]:
			continue
		key = (r["item_code"], r["stem_length"], r["warehouse"])
		committed[key] = committed.get(key, 0.0) + flt(r["stems"])
	return committed


def _age_bucket_allocation(warehouses):
	"""Per-(item, length, warehouse) sellable stock split across day buckets.

	Returns {(item_code, stem_length, warehouse): [day0, day1, day2, day3, day4+]}
	where each vector sums to the real sellable balance (Stem Length Bin
	actual − reserved) for that cell.

	The Age Bin (harvest-age tracker) DRIFTS HIGH — outbound moves (sales,
	reserves, transfers) debit Stem Length Bin but not the age bin — so its raw
	buckets over-count lifetime inflow and don't reconcile with the "All" total.
	Rather than scale proportionally (which crushed a today-harvested batch of 48
	against a 10,084 lifetime total down to round(base × 48/10084) ≈ 1, hiding
	real stock), allocate the real base NEWEST-FIRST: assume the stems still on
	hand are the freshest (a FIFO sell-down of the oldest). Hand the base to Day 0
	first (capped at its raw harvest), then Day 1, 2, 3, and let whatever remains
	fall into Day 4+. The freshest buckets show their true harvest count; the
	stale drift is absorbed by the 4+ remainder. Each vector sums to base, so
	Day's Pick + 1 + 2 + 3 + 4+ == the "All" total.
	"""
	if not warehouses:
		return {}

	wh_placeholders = ", ".join(["%s"] * len(warehouses))

	# Raw age buckets for EVERY day (0,1,2,3,4+), per (item, length, warehouse).
	# days_ago is clamped to the 0..4 bucket index.
	raw_rows = frappe.db.sql(
		f"""
		SELECT item_code, stem_length, warehouse,
			LEAST(GREATEST(DATEDIFF(CURDATE(), harvest_date), 0), 4) AS bucket,
			SUM(actual_qty) AS qty
		FROM `tabStem Length Age Bin`
		WHERE warehouse IN ({wh_placeholders})
		GROUP BY item_code, stem_length, warehouse, bucket
		""",
		[*warehouses],
		as_dict=True,
	)

	buckets = {}
	for r in raw_rows:
		key = (r["item_code"], r["stem_length"], r["warehouse"])
		b = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0.0])
		b[int(r["bucket"])] += float(r["qty"] or 0)

	# Real sellable base (actual − reserved, clamped ≥0) — the number "All" shows.
	base_rows = frappe.db.get_all(
		"Stem Length Bin",
		filters={"warehouse": ("in", warehouses)},
		fields=["item_code", "warehouse", "stem_length", "actual_qty", "reserved_qty"],
	)
	# Stems already parked in open draft carts aren't reserved in the bin, so
	# net them out here to keep them from being offered again.
	committed = _draft_cart_committed_stems(warehouses)
	base = {}
	for b in base_rows:
		if not b.item_code or not b.stem_length:
			continue
		key = (b.item_code, b.stem_length, b.warehouse)
		avail = float(b.actual_qty or 0) - float(b.reserved_qty or 0)
		avail -= committed.get(key, 0.0)
		if avail < 0:
			avail = 0
		base[key] = avail

	# Every cell that has a base balance gets a vector, even if the age bin has no
	# rows for it (then all the base lands in Day 4+ below).
	out = {}
	for key in set(base) | set(buckets):
		remaining = base.get(key, 0)
		if remaining <= 0:
			continue
		day_raw = buckets.get(key, [0.0, 0.0, 0.0, 0.0, 0.0])
		alloc = [0.0, 0.0, 0.0, 0.0, 0.0]
		for d in range(5):
			take = min(day_raw[d], remaining)
			alloc[d] = take
			remaining -= take
			if remaining <= 0:
				break
		# Base left after the raw buckets are exhausted (age bin under-counts vs
		# base) lands in the oldest bucket so the vector still sums to base.
		if remaining > 0:
			alloc[4] += remaining
		out[key] = alloc
	return out


@frappe.whitelist()
def get_product_overview_age_qty_all(age):
	"""Batch version of `get_product_overview_age_qty` for ALL items at once.

	Powers the global "days since harvest" filter on the Product Overview page.
	Returns {item_code: {stem_length_doc_name: {warehouse: qty}}} for the selected
	`age` bucket (`age` >= 4 means "4 or more days"). Per-cell buckets come from
	`_age_bucket_allocation` (newest-first), so the day buttons reconcile to the
	"All" total.
	"""
	from frappe.utils import cint

	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.get("show_product_overview"):
		frappe.throw(_("Product Overview is disabled."))

	warehouses = _product_overview_warehouses(settings)
	if not warehouses:
		return {}

	want = 4 if cint(age) >= 4 else cint(age)
	alloc = _age_bucket_allocation(warehouses)

	out = {}
	for (item_code, stem_name, warehouse), vec in alloc.items():
		qty = round(vec[want])
		if qty <= 0:
			continue
		out.setdefault(item_code, {}).setdefault(stem_name, {})[warehouse] = qty
	return out


@frappe.whitelist()
def get_product_overview_matrix():
	"""Per-variety stock matrix for the Product Overview card grid.

	One entry per published variety that has any sellable stock. Each entry lists
	only the stem lengths and warehouses that variety actually stocks, plus a
	`cells` map giving the 5 day-bucket quantities per (length, warehouse):

	    {
	      "item_code": ..., "variety": ..., "route": ...,
	      "sales_uom": "Bunch (12)", "stems_per_bunch": 12,
	      "lengths": [{"stem_length": <doc>, "label": "53CM"}, ...],  # in-stock only
	      "warehouses": ["Burguret Available for Sale - TL", ...],     # in-stock only
	      "cells": { <stem_length_doc>: { <warehouse>: [d0,d1,d2,d3,d4plus] } },
	      "wh_total_stems": { <stem_length_doc>: { <warehouse>: <sum of buckets> } },
	      "total_stock": <sum of all cells>,
	    }

	Day buckets come from `_age_bucket_allocation` (newest-first), so each cell's
	5 values sum to that cell's real sellable balance. Only plain items are
	matrixed — variants/templates aren't tracked in Stem Length Bin.
	"""
	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.get("show_product_overview"):
		frappe.throw(_("Product Overview is disabled."))

	warehouses = _product_overview_warehouses(settings)
	if not warehouses:
		return []

	alloc = _age_bucket_allocation(warehouses)
	if not alloc:
		return []

	# Variety metadata for every item that has at least one allocated cell.
	item_codes = list({k[0] for k in alloc})
	items = frappe.get_all(
		"Website Item",
		filters={"published": 1, "item_code": ("in", item_codes), "has_variants": 0},
		fields=["item_code", "web_item_name", "item_name", "route"],
	)
	if not items:
		return []
	published = {i.item_code: i for i in items}

	# Stem Length labels + sort keys, resolved once.
	stem_names = list({k[1] for k in alloc if k[1]})
	stem_meta = {}
	if stem_names and frappe.db.exists("DocType", "Stem Length"):
		for row in frappe.db.get_all(
			"Stem Length",
			filters={"name": ("in", stem_names)},
			fields=["name", "length"],
		):
			stem_meta[row.name] = row

	# Sales UOM (bunch) + stems-per-bunch per item — the modal transacts in bunches.
	from upande_webshop.upande_webshop.shopping_cart.cart import (
		_stems_per_bunch_from_uom,
	)

	uom_meta = {}
	for u in frappe.db.get_all(
		"Item",
		filters={"item_code": ("in", list(published.keys()))},
		fields=["item_code", "sales_uom", "stock_uom"],
	):
		uom = u.sales_uom or u.stock_uom or "Nos"
		uom_meta[u.item_code] = (uom, _stems_per_bunch_from_uom(uom) or 1)

	# Assemble per-item matrices.
	matrices = {}
	for (item_code, stem_name, warehouse), vec in alloc.items():
		if item_code not in published or not stem_name:
			continue
		total = sum(vec)
		if total <= 0:
			continue
		m = matrices.setdefault(
			item_code,
			{"cells": {}, "wh_total": {}, "lengths": set(), "warehouses": set()},
		)
		m["cells"].setdefault(stem_name, {})[warehouse] = [round(v) for v in vec]
		m["wh_total"].setdefault(stem_name, {})[warehouse] = round(total)
		m["lengths"].add(stem_name)
		m["warehouses"].add(warehouse)

	out = []
	for item_code, m in matrices.items():
		meta = published[item_code]
		uom, stems_per_bunch = uom_meta.get(item_code, ("Nos", 1))
		# Lengths in stock, sorted by numeric length; warehouses in configured order.
		lengths = sorted(
			m["lengths"], key=lambda s: _stem_length_sort_key(s, stem_meta)
		)
		whs = [w for w in warehouses if w in m["warehouses"]]
		total_stock = sum(
			sum(buckets) for by_wh in m["cells"].values() for buckets in by_wh.values()
		)
		out.append(
			{
				"item_code": item_code,
				"variety": meta.web_item_name or meta.item_name or item_code,
				"route": meta.route or "",
				"sales_uom": uom,
				"stems_per_bunch": stems_per_bunch,
				"lengths": [
					{"stem_length": s, "label": _stem_length_label(s, stem_meta)}
					for s in lengths
				],
				"warehouses": whs,
				"cells": m["cells"],
				"wh_total_stems": m["wh_total"],
				"total_stock": total_stock,
			}
		)

	# Biggest varieties first; ties by name.
	out.sort(key=lambda i: (-i["total_stock"], i["variety"].lower()))
	return out


@frappe.whitelist()
def add_to_cart_for_customer(
	item_code, stem_length, warehouse, qty, customer, portal_contact=None
):
	"""Append `qty` stems at `stem_length` to `customer`'s draft Sales Order cart.

	The Product Overview cart is a draft **Sales Order** (never a Quotation) —
	"Use Sales Order as Cart" behaviour. Reuses one open draft SO per customer
	(order_type = "Shopping Cart") and appends to it, leaving it as a draft for
	checkout/submit from /cart. Reservation does NOT happen here — stems are held
	only when the cart is checked out into a submitted Sales Order (the SO submit
	hook is the single reservation point).
	"""
	from frappe.utils import flt

	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.get("show_product_overview"):
		frappe.throw(_("Product Overview is disabled."))

	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Quantity must be greater than zero."))
	if not (item_code and stem_length and warehouse and customer):
		frappe.throw(_("Missing required values."))

	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer))
	if not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(_("Warehouse {0} not found.").format(warehouse))
	_assert_customer_allowed(customer)

	company = settings.get("company") or frappe.defaults.get_user_default("company")
	if not company:
		frappe.throw(_("Webshop Settings → Company is not set."))

	from erpnext.accounts.party import get_party_account_currency

	currency = (
		get_party_account_currency("Customer", customer, company)
		or frappe.db.get_value("Company", company, "default_currency")
	)

	# One open draft SO acts as the customer's cart. Matched on the same keys the
	# /cart page uses (customer + contact_email + order_type "Shopping Cart" +
	# docstatus 0) so Product Overview and /cart share ONE cart document.
	cart_email = frappe.session.user
	so_name = frappe.db.get_value(
		"Sales Order",
		{
			"customer": customer,
			"contact_email": cart_email,
			"docstatus": 0,
			"order_type": "Shopping Cart",
		},
		"name",
	)
	if so_name:
		so = frappe.get_doc("Sales Order", so_name)
	else:
		so = frappe.new_doc("Sales Order")
		so.customer = customer
		so.company = company
		so.currency = currency
		so.order_type = "Shopping Cart"
		so.contact_email = cart_email
		so.transaction_date = frappe.utils.nowdate()
		so.delivery_date = frappe.utils.add_days(frappe.utils.nowdate(), 7)
		if portal_contact and frappe.db.exists("Contact", portal_contact):
			so.contact_person = portal_contact

	# qty is entered in bunches (the item's sales UOM); stems = qty × stems/bunch.
	sales_uom, stems_per_bunch = _sales_bunch_uom(item_code)
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
	total_stems = qty * stems_per_bunch
	# One cart line per (variety + length + source warehouse) cell. Re-adding the
	# same cell merges its qty onto the existing line rather than spawning a new
	# row — so Product Overview's per-length / per-variety / per-warehouse cell
	# maps to exactly one Sales Order Item.
	def _is_same_cell(it):
		return (
			it.item_code == item_code
			and (it.get("custom_source_warehouse") or it.warehouse) == warehouse
			and (it.get("custom_length") or "") == (stem_length or "")
		)

	existing = next((it for it in so.get("items", []) if _is_same_cell(it)), None)

	# Cap at available-for-sale. A draft-SO cart doesn't bump reserved_qty, so
	# also count what's already in THIS cart for the same item/warehouse/length —
	# otherwise repeated adds could quietly exceed stock.
	already_in_cart = sum(
		flt(it.get("custom_total_stems"))
		or flt(it.qty) * flt(it.conversion_factor or 1)
		for it in so.get("items", [])
		if _is_same_cell(it)
	)
	# Exclude THIS cart from the global draft-cart netting — its existing lines
	# are already counted via `already_in_cart` above (so.get("name") is None for
	# a brand-new cart, which the helper treats as "exclude nothing").
	_assert_stock_available(
		item_code,
		warehouse,
		stem_length,
		already_in_cart + total_stems,
		exclude_so=so.get("name"),
	)

	has_total = frappe.db.has_column("Sales Order Item", "custom_total_stems")
	if existing:
		# Merge onto the matching cell's line.
		existing.qty = flt(existing.qty) + qty
		if has_total:
			existing.custom_total_stems = (
				flt(existing.get("custom_total_stems")) + total_stems
			)
	else:
		row = {
			"item_code": item_code,
			"qty": qty,
			"uom": sales_uom,
			"stock_uom": stock_uom,
			"conversion_factor": stems_per_bunch,
			"warehouse": warehouse,
			"delivery_date": so.delivery_date,
		}
		if frappe.db.has_column("Sales Order Item", "custom_length"):
			row["custom_length"] = stem_length
		if has_total:
			row["custom_total_stems"] = total_stems
		# Tambuzi's pick-list automation requires a source warehouse per line on
		# submit; the warehouse picked on Product Overview is that source.
		if frappe.db.has_column("Sales Order Item", "custom_source_warehouse"):
			row["custom_source_warehouse"] = warehouse
		so.append("items", row)

	so.flags.ignore_permissions = True
	so.flags.ignore_mandatory = True
	# Mark this as a storefront cart save so server-side SO hooks (e.g. tambuzi's
	# delivery-warehouse remap) skip their interactive msgprint popups, which
	# would otherwise stack a modal on the Product Overview on every add-to-cart.
	so.flags.webshop_cart_save = True
	so.save(ignore_permissions=True)

	# Make this customer the session's active cart so /cart shows the SO we just
	# built. Reps switch between their customers' carts via the /cart selector.
	from upande_webshop.upande_webshop.shopping_cart.cart import set_active_cart_customer

	try:
		set_active_cart_customer(customer)
	except Exception:
		pass  # non-fatal: the cart row is saved regardless

	return {"sales_order": so.name, "cart": so.name}
