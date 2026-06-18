# Copyright (c) 2026, Upande LTD and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import flt

from upande_webshop.upande_webshop.utils.item_price_source import get_price

from upande_webshop.upande_webshop.doctype.item_review.item_review import get_customer
from upande_webshop.upande_webshop.utils.product import get_non_stock_item_status
from upande_webshop.upande_webshop.utils.shelf_stock import (
	get_shelf_qty,
	get_shelf_qty_by_length,
	get_shelf_qty_for_items,
	use_shelf_stock,
)
from upande_webshop.upande_webshop.utils.enabled_stock import (
	enabled_feature_active,
	enabled_qty_by_length,
	enabled_total_qty,
	enabled_total_qty_for_items,
)


class ProductQuery:
	"""Query engine for product listing

	Attributes:
	        fields (list): Fields to fetch in query
	        conditions (string): Conditions for query building
	        or_conditions (string): Search conditions
	        page_length (Int): Length of page for the query
	        settings (Document): Webshop Settings DocType
	"""

	def __init__(self):
		self.settings = frappe.get_doc("Webshop Settings")
		self.page_length = self.settings.products_per_page or 20

		self.or_filters = []
		self.filters = [["published", "=", 1]]
		self.fields = [
			"web_item_name",
			"name",
			"item_name",
			"item_code",
			"website_image",
			"variant_of",
			"has_variants",
			"item_group",
			"web_long_description",
			"short_description",
			"route",
			"website_warehouse",
			"ranking",
			"on_backorder",
		]

	def query(self, attributes=None, fields=None, search_term=None, start=0, item_group=None):
		"""
		Args:
		        attributes (dict, optional): Item Attribute filters
		        fields (dict, optional): Field level filters
		        search_term (str, optional): Search term to lookup
		        start (int, optional): Page start

		Returns:
		        dict: Dict containing items, item count & discount range
		"""
		# track if discounts included in field filters
		self.filter_with_discount = bool(fields.get("discount"))
		result, discount_list, website_item_groups, count = [], [], [], 0
		cart_items = {}

		if fields:
			self.build_fields_filters(fields)
		if item_group:
			self.build_item_group_filters(item_group)
		if search_term:
			self.build_search_filters(search_term)

		# query results
		if attributes:
			result, count = self.query_items_with_attributes(attributes, start)
		else:
			result, count = self.query_items(start=start)

		if self.settings.enabled:
			cart_items = self.get_cart_items()

		result, discount_list = self.add_display_details(result, discount_list, cart_items)

		discounts = []
		if discount_list:
			discounts = [min(discount_list), max(discount_list)]

		result = self.filter_results_by_discount(fields, result)

		return {"items": result, "items_count": count, "discounts": discounts}

	def query_items(self, start=0):
		"""Build a query to fetch Website Items based on field filters.

		Results are ordered by total storefront stock qty desc, then ranking desc
		as tiebreaker. Out-of-stock items fall to the bottom.
		"""
		# Fetch all matching rows; sorting needs the full set because the sort
		# key (stock qty) is computed in Python from the Bin table.
		items = frappe.db.get_all(
			"Website Item",
			fields=self.fields,
			filters=self.filters,
			or_filters=self.or_filters,
			limit_page_length=184467440737095516,
			limit_start=0,
		)
		count = len(items)

		self._attach_stock_qty(items)
		items.sort(
			key=lambda i: (flt(i.get("stock_qty")), flt(i.get("ranking"))),
			reverse=True,
		)

		# If discount filter is active, downstream code slices after filtering;
		# otherwise apply pagination here.
		if not self.filter_with_discount:
			items = items[start : start + self.page_length]

		return items, count

	def _attach_stock_qty(self, items):
		"""Set `stock_qty` on each item using one batched Bin query per warehouse set.

		Used both as the sort key and to short-circuit `get_stock_availability`.
		"""
		# Group items by the warehouse set they resolve to, so each set takes one query.
		items_by_warehouse_key = {}
		for item in items:
			leaves = tuple(sorted(_all_storefront_warehouses(item.get("website_warehouse"))))
			items_by_warehouse_key.setdefault(leaves, []).append(item)

		# For templates with variants, we also need the variant item_codes.
		variant_parent_of = {}
		template_codes = [i.item_code for i in items if i.get("has_variants")]
		if template_codes:
			variants = frappe.get_all(
				"Item",
				filters={"variant_of": ("in", template_codes)},
				fields=["name", "variant_of"],
			)
			for v in variants:
				variant_parent_of[v.name] = v.variant_of

		# Shelf stock is not warehouse-scoped, so for plain items we resolve qty
		# once across all items rather than per warehouse-bucket. Variants never
		# live on a shelf (each is a distinct length already in core Bin).
		shelf_mode = use_shelf_stock()
		shelf_qty_by_code = {}
		if shelf_mode:
			plain_codes = [i.item_code for i in items if not i.get("has_variants")]
			shelf_qty_by_code = get_shelf_qty_for_items(plain_codes)

		# Admin-published totals (per plain item) override whatever live source the
		# listing would otherwise show. Batched: one query for all plain items.
		# When the publish feature is active, it GATES plain items: a plain item with
		# no published rows shows 0 (not its live stock).
		feature_active = enabled_feature_active()
		published_by_code = enabled_total_qty_for_items(
			[i.item_code for i in items if not i.get("has_variants")]
		)

		# Per-customer warehouse gate: when the logged-in customer is pinned to a
		# warehouse (Customer Settings), their portal user sees ONLY the published
		# items that ALSO physically sit in that warehouse — i.e. exactly the items
		# enabled on that customer's warehouse tab. Items published from elsewhere
		# (shelf / other warehouses) are hidden for this customer.
		from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
			get_session_customer_warehouse,
		)

		customer_wh_gate = bool(get_session_customer_warehouse())

		# Plain items (shelf mode aside) read core Bin, same source as variants.
		for leaves, bucket in items_by_warehouse_key.items():
			# Variants are length-resolved at the item level (one variant = one
			# length), so their qty stays in core Bin. Plain items follow the source
			# chosen above; the listing has no length context, so qty is summed.
			variant_lookup_codes = set()
			plain_lookup_codes = set()
			for item in bucket:
				if item.get("has_variants"):
					variant_lookup_codes.update(
						code for code, parent in variant_parent_of.items() if parent == item.item_code
					)
				elif not shelf_mode or customer_wh_gate:
					# Plain items: read Bin when not in shelf mode, OR always under the
					# customer-warehouse gate (we need warehouse membership to decide
					# whether a published item is visible to this customer).
					plain_lookup_codes.add(item.item_code)

			qty_by_code = {}

			# Without warehouses we can only resolve shelf-mode plain items (handled
			# below via shelf_qty_by_code); Bin-backed lookups need a warehouse set.
			if leaves:
				# Plain items read core Bin alongside variants.
				bin_codes = set(variant_lookup_codes)
				bin_codes |= plain_lookup_codes

				if bin_codes:
					rows = frappe.db.get_all(
						"Bin",
						filters={
							"item_code": ("in", list(bin_codes)),
							"warehouse": ("in", list(leaves)),
						},
						fields=["item_code", "actual_qty"],
					)
					for row in rows:
						qty_by_code[row.item_code] = qty_by_code.get(row.item_code, 0.0) + flt(row.actual_qty)

			for item in bucket:
				if item.get("has_variants"):
					total = sum(
						qty_by_code.get(code, 0.0)
						for code, parent in variant_parent_of.items()
						if parent == item.item_code
					)
				elif feature_active:
					# Gated: plain items show ONLY their published qty (0 if none).
					total = published_by_code.get(item.item_code, 0.0)
					# Customer-warehouse gate: hide published items that aren't in
					# THIS customer's warehouse (qty_by_code holds the warehouse's Bin
					# membership since leaves == the customer warehouse).
					if customer_wh_gate and qty_by_code.get(item.item_code, 0.0) <= 0:
						total = 0.0
				elif shelf_mode:
					total = shelf_qty_by_code.get(item.item_code, 0.0)
				else:
					total = qty_by_code.get(item.item_code, 0.0)
				item.stock_qty = total

	def query_items_with_attributes(self, attributes, start=0):
		"""Build a query to fetch Website Items based on field & attribute filters."""
		item_codes = []

		for attribute, values in attributes.items():
			if not isinstance(values, list):
				values = [values]

			# get items that have selected attribute & value
			item_code_list = frappe.db.get_all(
				"Item",
				fields=["item_code"],
				filters=[
					["published_in_website", "=", 1],
					["Item Variant Attribute", "attribute", "=", attribute],
					["Item Variant Attribute", "attribute_value", "in", values],
				],
			)
			item_codes.append({x.item_code for x in item_code_list})

		if item_codes:
			item_codes = list(set.intersection(*item_codes))
			self.filters.append(["item_code", "in", item_codes])

		items, count = self.query_items(start=start)

		return items, count

	def build_fields_filters(self, filters):
		"""Build filters for field values

		Args:
		        filters (dict): Filters
		"""
		for field, values in filters.items():
			if not values or field == "discount":
				continue

			# handle multiselect fields in filter addition
			meta = frappe.get_meta("Website Item", cached=True)
			df = meta.get_field(field)
			if df.fieldtype == "Table MultiSelect":
				child_doctype = df.options
				child_meta = frappe.get_meta(child_doctype, cached=True)
				fields = child_meta.get("fields")
				if fields:
					self.filters.append([child_doctype, fields[0].fieldname, "IN", values])
			elif isinstance(values, list):
				# If value is a list use `IN` query
				self.filters.append([field, "in", values])
			else:
				# `=` will be faster than `IN` for most cases
				self.filters.append([field, "=", values])

	def build_item_group_filters(self, item_group):
		"Add filters for Item group page and include Website Item Groups."
		from upande_webshop.upande_webshop.doctype.override_doctype.item_group import get_child_groups_for_website

		item_group_filters = []

		item_group_filters.append(["Website Item", "item_group", "=", item_group])
		# Consider Website Item Groups
		item_group_filters.append(["Website Item Group", "item_group", "=", item_group])

		if frappe.db.get_value("Item Group", item_group, "include_descendants"):
			# include child item group's items as well
			# eg. Group Node A, will show items of child 1 and child 2 as well
			# on it's web page
			include_groups = get_child_groups_for_website(item_group, include_self=True)
			include_groups = [x.name for x in include_groups]

			item_group_filters.append(["Website Item", "item_group", "in", include_groups])

		self.or_filters.extend(item_group_filters)

	def build_search_filters(self, search_term):
		"""Query search term in specified fields

		Args:
		        search_term (str): Search candidate
		"""
		# Default fields to search from
		default_fields = {"item_code", "item_name", "web_long_description", "item_group"}

		# Get meta search fields
		meta = frappe.get_meta("Website Item")
		meta_fields = set(meta.get_search_fields())

		# Join the meta fields and default fields set
		search_fields = default_fields.union(meta_fields)
		if frappe.db.count("Website Item", cache=True) > 50000:
			search_fields.discard("web_long_description")

		# Build or filters for query
		search = "%{}%".format(search_term)
		for field in search_fields:
			self.or_filters.append([field, "like", search])

	def add_display_details(self, result, discount_list, cart_items):
		"""Add price and availability details in result.

		Pricing is the hot path here: the previous implementation called
		`get_product_info_for_website` once per item, which re-resolved the cart
		settings, party, price list AND recomputed stock on every iteration
		(~21 ms/item — the bulk of the listing's render time). The listing only
		consumes the price, and stock is already attached by `_attach_stock_qty`,
		so we hoist every invariant out of the loop and call `get_price` directly.
		"""
		price_ctx = self._get_price_context()

		# Batch the per-item `is_stock_item` flag (used by get_stock_availability)
		# into one query instead of a cached_value lookup per row.
		is_stock_by_code = {}
		if self.settings.show_stock_availability:
			rows = frappe.get_all(
				"Item",
				filters={"item_code": ("in", [i.item_code for i in result])},
				fields=["item_code", "is_stock_item"],
			)
			is_stock_by_code = {r.item_code: r.is_stock_item for r in rows}

		for item in result:
			if price_ctx:
				# A single item's pricing must never blank the whole grid. If
				# get_price throws (e.g. a missing Currency Exchange rate during
				# conversion), log it and show the item without a price rather than
				# silently dropping every product.
				try:
					price = get_price(
						item.item_code,
						price_ctx["price_list"],
						price_ctx["customer_group"],
						price_ctx["company"],
						party=price_ctx["party"],
					)
				except Exception:
					frappe.log_error(
						title="Webshop listing: get_price failed",
						message="Item {0}: {1}".format(item.item_code, frappe.get_traceback()),
					)
					price = None
				if price:
					# update/mutate item and discount_list objects
					self.get_price_discount_info(item, price, discount_list)

			if self.settings.show_stock_availability:
				self.get_stock_availability(item, is_stock_by_code.get(item.item_code))

			item.in_cart = item.item_code in cart_items
			item.cart_qty = cart_items.get(item.item_code, 0) if isinstance(cart_items, dict) else 0

		# One batched query for the wishlist flag instead of one `exists` per item.
		wished_codes = self._get_wished_item_codes([i.item_code for i in result])
		for item in result:
			item.wished = item.item_code in wished_codes

		return result, discount_list

	def _get_price_context(self):
		"""Resolve the (invariant per request) inputs `get_price` needs.

		Returns None when prices shouldn't be shown (cart disabled, price hidden
		for guests), so the caller skips pricing entirely.
		"""
		from upande_webshop.upande_webshop.shopping_cart.cart import _set_price_list, get_party

		settings = self.settings
		if not settings.enabled or not settings.show_price:
			return None
		if frappe.session.user == "Guest" and settings.hide_price_for_guest:
			return None

		# get_party() can raise for a portal user (get_doc("Customer") fails the
		# permission check) or redirect a brand-new web user. Pricing only uses
		# `party` for the Price-List fallback, so degrade to party=None rather than
		# let one call blank the whole listing. The session display currency is
		# still resolved from the customer link inside get_price.
		try:
			party = get_party()
		except Exception:
			frappe.log_error(
				title="Webshop listing: get_party failed",
				message=frappe.get_traceback(),
			)
			party = None

		return {
			"price_list": _set_price_list(settings, None),
			"customer_group": settings.default_customer_group,
			"company": settings.company,
			"party": party,
		}

	def _get_wished_item_codes(self, item_codes):
		"""Item codes the current user has wishlisted, in one query."""
		if not item_codes or frappe.session.user == "Guest":
			return set()
		rows = frappe.get_all(
			"Wishlist Item",
			filters={"item_code": ("in", item_codes), "parent": frappe.session.user},
			pluck="item_code",
		)
		return set(rows)

	def get_price_discount_info(self, item, price_object, discount_list):
		"""Modify item object and add price details."""
		fields = ["formatted_mrp", "formatted_price", "price_list_rate"]
		for field in fields:
			item[field] = price_object.get(field)

		if price_object.get("discount_percent"):
			item.discount_percent = flt(price_object.discount_percent)
			discount_list.append(price_object.discount_percent)

		if item.formatted_mrp:
			item.discount = price_object.get("formatted_discount_percent") or price_object.get(
				"formatted_discount_rate"
			)

	def get_stock_availability(self, item, is_stock_item=None):
		"""Modify item object and add stock details."""
		# stock_qty was pre-computed by `_attach_stock_qty` in one batched query.
		precomputed_qty = item.get("stock_qty")
		item.in_stock = False
		warehouse = item.get("website_warehouse")
		if is_stock_item is None:
			is_stock_item = frappe.get_cached_value("Item", item.item_code, "is_stock_item")

		if item.get("on_backorder"):
			return

		if item.get("has_variants"):
			if warehouse:
				item.in_stock = flt(precomputed_qty) > 0
			return

		if not is_stock_item:
			item.stock_qty = None
			if warehouse:
				# product bundle case
				item.in_stock = get_non_stock_item_status(item.item_code, "website_warehouse")
			else:
				item.in_stock = True
		elif warehouse:
			# stock item and has warehouse
			item.in_stock = flt(precomputed_qty) > 0

	def has_any_variant_in_stock(self, template_item_code, warehouse):
		from upande_webshop.templates.pages.wishlist import (
			get_stock_availability as get_stock_availability_from_template,
		)

		variants = frappe.get_all(
			"Item",
			filters={"variant_of": template_item_code},
			pluck="name",
		)
		for variant_code in variants:
			if get_stock_availability_from_template(variant_code, warehouse):
				return True
		return False

	def get_cart_items(self):
		customer = get_customer(silent=True)
		if customer:
			quotation = frappe.get_all(
				"Quotation",
				fields=["name"],
				filters={
					"party_name": customer,
					"contact_email": frappe.session.user,
					"order_type": "Shopping Cart",
					"docstatus": 0,
				},
				order_by="modified desc",
				limit_page_length=1,
			)
			if quotation:
				rows = frappe.get_all(
					"Quotation Item",
					fields=["item_code", "qty"],
					filters={"parent": quotation[0].get("name")},
				)
				cart_qty_by_item = {}
				for row in rows:
					cart_qty_by_item[row.item_code] = cart_qty_by_item.get(row.item_code, 0) + (row.qty or 0)
				return cart_qty_by_item

		return {}

	def filter_results_by_discount(self, fields, result):
		if fields and fields.get("discount"):
			discount_percent = frappe.utils.flt(fields["discount"][0])
			result = [
				row
				for row in result
				if row.get("discount_percent") and row.discount_percent <= discount_percent
			]

		if self.filter_with_discount:
			# no limit was added to results while querying
			# slice results manually
			result[: self.page_length]

		return result


def _resolve_warehouses(warehouse):
	from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses

	if warehouse and frappe.get_cached_value("Warehouse", warehouse, "is_group") == 1:
		return get_child_warehouses(warehouse)
	return [warehouse] if warehouse else []


def _all_storefront_warehouses(fallback_warehouse=None):
	"""
	Leaf warehouses to query for storefront stock.

	When the logged-in customer has a warehouse assigned (Webshop Settings →
	Customer Settings), that warehouse OVERRIDES the default set — the customer
	sees only their warehouse's stock. Otherwise aggregates Webshop Settings →
	Warehouses (with group expansion), falling back to the per-item
	`website_warehouse` so we still render something if the settings table is empty.
	"""
	from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
		get_configured_warehouses,
		get_session_customer_warehouse,
	)

	# Per-customer override: pin stock to the customer's assigned warehouse.
	customer_wh = get_session_customer_warehouse()
	if customer_wh:
		return list(_resolve_warehouses(customer_wh))

	leaves = set()
	for wh in get_configured_warehouses():
		leaves.update(_resolve_warehouses(wh))
	if not leaves and fallback_warehouse:
		leaves.update(_resolve_warehouses(fallback_warehouse))
	return list(leaves)


def get_item_total_qty(item_code, warehouse):
	"""Total qty for a single item across the storefront warehouse set.

	Both variant and plain items read core Bin (each variant_of = a distinct
	length, already tracked there; plain items have no length context in the
	listing). Plain items read from the shelf instead when shelf mode is on."""
	item_meta = frappe.db.get_value(
		"Item", item_code, ["has_variants", "variant_of"], as_dict=True
	) or frappe._dict()
	is_variant_or_template = bool(item_meta.has_variants) or bool(item_meta.variant_of)

	# Gated: once the publish feature is active, plain items show ONLY their
	# published total (0 if this item was never enabled).
	if not is_variant_or_template and enabled_feature_active():
		return enabled_total_qty(item_code)

	# Plain items read from the shelf when shelf mode is on (not warehouse-scoped).
	if not is_variant_or_template and use_shelf_stock():
		return get_shelf_qty(item_code)

	warehouses = _all_storefront_warehouses(warehouse)
	if not warehouses:
		return 0.0

	# Both plain items and variants read core Bin.
	rows = frappe.db.get_all(
		"Bin",
		filters={"item_code": item_code, "warehouse": ("in", warehouses)},
		fields=["actual_qty"],
	)
	return sum(flt(r.actual_qty) for r in rows)


def get_item_qty_by_length(item_code, warehouse):
	"""Per-stem-length availability for a plain item, as {length: qty}.

	The non-variant stem-length picker renders one row per globally defined Stem
	Length. With shelf mode on, availability is per-length (the shelf carries a
	distinct row per length), so each row must report its OWN length's qty — not
	the item's grand total, which would let a user pick a length the cart then
	rejects with "Only 0 ... available in stock".

	Returns a dict keyed by the Stem Length `length` string (e.g. "52cm"); lengths
	with no shelf row are simply absent (caller treats missing as 0 / out of stock).

	Off shelf mode there is no per-length dimension in core Bin, so this returns an
	empty dict and the template falls back to the item's total Bin qty per row
	(the prior behaviour).
	"""
	item_meta = frappe.db.get_value(
		"Item", item_code, ["has_variants", "variant_of"], as_dict=True
	) or frappe._dict()
	is_variant_or_template = bool(item_meta.has_variants) or bool(item_meta.variant_of)

	# Gated: when the publish feature is active, plain items expose ONLY their
	# enabled lengths' published qty (every other length reads as 0 / out of stock).
	if not is_variant_or_template and enabled_feature_active():
		return enabled_qty_by_length(item_code)

	# Live per-length availability (shelf mode only; warehouse mode has no length
	# dimension in core Bin and returns {} so the template falls back to total).
	if not is_variant_or_template and use_shelf_stock():
		return get_shelf_qty_by_length(item_code)

	return {}


def get_variants_total_qty(template_item_code, warehouse):
	warehouses = _all_storefront_warehouses(warehouse)
	if not warehouses:
		return 0.0
	variants = frappe.get_all(
		"Item",
		filters={"variant_of": template_item_code},
		pluck="name",
	)
	if not variants:
		return 0.0
	rows = frappe.db.get_all(
		"Bin",
		filters={
			"item_code": ("in", variants),
			"warehouse": ("in", warehouses),
		},
		fields=["actual_qty"],
	)
	return sum(flt(r.actual_qty) for r in rows)
