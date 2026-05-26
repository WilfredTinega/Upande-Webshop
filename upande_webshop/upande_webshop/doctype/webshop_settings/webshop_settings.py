import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import comma_and, flt, unique

from upande_webshop.upande_webshop.redisearch_utils import (
	create_website_items_index,
	define_autocomplete_dictionary,
	get_indexable_web_fields,
	is_search_module_loaded,
)


class ShoppingCartSetupError(frappe.ValidationError):
	pass


class WebshopSettings(Document):
	def onload(self):
		self.get("__onload").quotation_series = frappe.get_meta("Quotation").get_options("naming_series")

		# flag >> if redisearch is installed and loaded
		self.is_redisearch_loaded = is_search_module_loaded()

	def validate(self):
		self.validate_field_filters(self.filter_fields, self.enable_field_filters)
		self.validate_attribute_filters()
		self.validate_checkout()
		self.validate_search_index_fields()

		if self.enabled:
			self.validate_price_list_exchange_rate()

		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")

		if self.meta.has_field("is_redisearch_enabled"):
			self.is_redisearch_enabled_pre_save = frappe.db.get_single_value(
				"Webshop Settings", "is_redisearch_enabled"
			)

	def after_save(self):
		self.create_redisearch_indexes()

	def create_redisearch_indexes(self):
		if not self.meta.has_field("is_redisearch_enabled"):
			return
		is_enabled = self.get("is_redisearch_enabled")
		value_changed = is_enabled != self.is_redisearch_enabled_pre_save
		if self.is_redisearch_loaded and is_enabled and value_changed:
			define_autocomplete_dictionary()
			create_website_items_index()

	@staticmethod
	def validate_field_filters(filter_fields, enable_field_filters):
		if not (enable_field_filters and filter_fields):
			return

		web_item_meta = frappe.get_meta("Website Item")
		valid_fields = [
			df.fieldname for df in web_item_meta.fields if df.fieldtype in ["Link", "Table MultiSelect"]
		]

		for row in filter_fields:
			if row.fieldname not in valid_fields:
				frappe.throw(
					_(
						"Filter Fields Row #{0}: Fieldname {1} must be of type 'Link' or 'Table MultiSelect'"
					).format(row.idx, frappe.bold(row.fieldname))
				)

	def validate_attribute_filters(self):
		if not (self.enable_attribute_filters and self.filter_attributes):
			return

		# if attribute filters are enabled, variants must be shown so attribute filtering can match them
		self.show_variants = 1

	def validate_checkout(self):
		if self.enable_checkout and not self.payment_gateway_account:
			self.enable_checkout = 0

	def validate_search_index_fields(self):
		if not self.get("search_index_fields"):
			return

		fields = self.search_index_fields.replace(" ", "")
		fields = unique(fields.strip(",").split(","))  # Remove extra ',' and remove duplicates

		# All fields should be indexable
		allowed_indexable_fields = get_indexable_web_fields()

		if not (set(fields).issubset(allowed_indexable_fields)):
			invalid_fields = list(set(fields).difference(allowed_indexable_fields))
			num_invalid_fields = len(invalid_fields)
			invalid_fields = comma_and(invalid_fields)

			if num_invalid_fields > 1:
				frappe.throw(
					_("{0} are not valid options for Search Index Field.").format(frappe.bold(invalid_fields))
				)
			else:
				frappe.throw(
					_("{0} is not a valid option for Search Index Field.").format(frappe.bold(invalid_fields))
				)

		self.search_index_fields = ",".join(fields)

	def validate_price_list_exchange_rate(self):
		"Check if exchange rate exists for Price List currency (to Company's currency)."
		from erpnext.setup.utils import get_exchange_rate

		if not self.enabled or not self.company or not self.price_list:
			return  # this function is also called from hooks, check values again

		company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
		price_list_currency = frappe.db.get_value("Price List", self.price_list, "currency")

		if not company_currency:
			msg = f"Please specify currency in Company {self.company}"
			frappe.throw(_(msg), title=_("Missing Currency"), exc=ShoppingCartSetupError)

		if not price_list_currency:
			msg = f"Please specify currency in Price List {frappe.bold(self.price_list)}"
			frappe.throw(_(msg), title=_("Missing Currency"), exc=ShoppingCartSetupError)

		if price_list_currency != company_currency:
			from_currency, to_currency = price_list_currency, company_currency

			# Get exchange rate checks Currency Exchange Records too
			exchange_rate = get_exchange_rate(from_currency, to_currency, args="for_selling")

			if not flt(exchange_rate):
				msg = f"Missing Currency Exchange Rates for {from_currency}-{to_currency}"
				frappe.throw(_(msg), title=_("Missing"), exc=ShoppingCartSetupError)

	def validate_tax_rule(self):
		if not frappe.db.get_value("Tax Rule", {"use_for_shopping_cart": 1}, "name"):
			frappe.throw(frappe._("Set Tax Rule for shopping cart"), ShoppingCartSetupError)

	def get_tax_master(self, billing_territory):
		tax_master = self.get_name_from_territory(
			billing_territory, "sales_taxes_and_charges_masters", "sales_taxes_and_charges_master"
		)
		return tax_master and tax_master[0] or None

	def get_shipping_rules(self, shipping_territory):
		return self.get_name_from_territory(shipping_territory, "shipping_rules", "shipping_rule")

	def on_change(self):
		old_doc = self.get_doc_before_save()

		if old_doc:
			old_fields = old_doc.get("search_index_fields")
			new_fields = self.get("search_index_fields")

			if new_fields and new_fields != old_fields:
				create_website_items_index()

			old_warehouses = sorted(
				row.warehouse for row in (old_doc.get("warehouses") or []) if row.warehouse
			)
			new_warehouses = sorted(
				row.warehouse for row in (self.get("warehouses") or []) if row.warehouse
			)

			if new_warehouses and new_warehouses != old_warehouses:
				from upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices import (
					bust_warehouse_cache,
				)

				bust_warehouse_cache()
				frappe.enqueue(
					"upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings.sync_website_item_warehouses",
					queue="long",
					user=frappe.session.user,
				)


def get_configured_warehouses():
	"""Return the ordered list of warehouses configured under Webshop Settings → Stock Balances."""
	settings = frappe.get_cached_doc("Webshop Settings")
	return [row.warehouse for row in (settings.get("warehouses") or []) if row.warehouse]


@frappe.whitelist()
def get_warehouse_totals(warehouses):
	"""Return {warehouse_name: total_actual_qty} for each requested warehouse.

	Mirrors the per-item source-of-truth choice in
	upande_webshop.utils.product.get_web_item_qty_in_stock:
	  - Variants and templates (has_variants=1 OR variant_of set) come from Bin.
	  - Plain items come from Stem Length Bin summed across all lengths.

	Group warehouses are expanded to their leaves so a group row aggregates its
	children. Nothing is persisted; this is a read-only form display.
	"""
	from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses
	from frappe.utils import flt

	if isinstance(warehouses, str):
		warehouses = frappe.parse_json(warehouses)
	warehouses = [w for w in (warehouses or []) if w]
	if not warehouses:
		return {}

	leaves_by_warehouse = {}
	all_leaves = set()
	for wh in warehouses:
		if frappe.get_cached_value("Warehouse", wh, "is_group") == 1:
			leaves = get_child_warehouses(wh) or []
		else:
			leaves = [wh]
		leaves_by_warehouse[wh] = leaves
		all_leaves.update(leaves)

	if not all_leaves:
		return {wh: 0.0 for wh in warehouses}

	placeholders = ",".join(["%s"] * len(all_leaves))
	params = tuple(all_leaves)

	bin_rows = frappe.db.sql(
		f"""
		SELECT B.warehouse, COALESCE(SUM(B.actual_qty), 0) AS qty
		FROM `tabBin` B
		INNER JOIN `tabItem` I ON I.item_code = B.item_code
		WHERE B.warehouse IN ({placeholders})
		  AND (I.has_variants = 1 OR (I.variant_of IS NOT NULL AND I.variant_of != ''))
		GROUP BY B.warehouse
		""",
		params,
		as_dict=True,
	)
	slb_rows = frappe.db.sql(
		f"""
		SELECT S.warehouse, COALESCE(SUM(S.actual_qty), 0) AS qty
		FROM `tabStem Length Bin` S
		INNER JOIN `tabItem` I ON I.item_code = S.item_code
		WHERE S.warehouse IN ({placeholders})
		  AND I.has_variants = 0
		  AND (I.variant_of IS NULL OR I.variant_of = '')
		GROUP BY S.warehouse
		""",
		params,
		as_dict=True,
	)

	qty_by_leaf = {}
	for r in bin_rows:
		qty_by_leaf[r.warehouse] = qty_by_leaf.get(r.warehouse, 0.0) + flt(r.qty)
	for r in slb_rows:
		qty_by_leaf[r.warehouse] = qty_by_leaf.get(r.warehouse, 0.0) + flt(r.qty)

	return {
		wh: sum(qty_by_leaf.get(leaf, 0.0) for leaf in leaves)
		for wh, leaves in leaves_by_warehouse.items()
	}


def validate_cart_settings(doc=None, method=None):
	frappe.get_doc("Webshop Settings", "Webshop Settings").run_method("validate")


def get_shopping_cart_settings():
	return frappe.get_cached_doc("Webshop Settings")


@frappe.whitelist(allow_guest=True)
def is_cart_enabled():
	return get_shopping_cart_settings().enabled


@frappe.whitelist(allow_guest=True)
def is_wishlist_enabled():
	return get_shopping_cart_settings().enable_wishlist


def show_quantity_in_website():
	return get_shopping_cart_settings().show_quantity_in_website


def check_shopping_cart_enabled():
	if not get_shopping_cart_settings().enabled:
		frappe.throw(_("You need to enable Shopping Cart"), ShoppingCartSetupError)


def show_attachments():
	return get_shopping_cart_settings().show_attachments


def sync_website_item_warehouses(user=None):
	"""
	For every Website Item, set `website_warehouse` to the first warehouse in
	Webshop Settings → Warehouses that has stock for that item. Group warehouses
	are expanded to their child warehouses; the chosen warehouse stored on the
	Website Item is the configured row (parent), not the leaf with stock.
	"""
	from upande_webshop.upande_webshop.product_data_engine.query import _resolve_warehouses

	configured = get_configured_warehouses()
	if not configured:
		return

	# Map each configured warehouse to its expanded leaf set (group → children).
	expanded = {wh: _resolve_warehouses(wh) for wh in configured}
	all_leaves = sorted({leaf for leaves in expanded.values() for leaf in leaves})
	if not all_leaves:
		return

	items = frappe.get_all("Website Item", fields=["name", "item_code", "website_warehouse"])
	if not items:
		return

	item_codes = list({it.item_code for it in items if it.item_code})

	bins = frappe.get_all(
		"Bin",
		filters={"item_code": ("in", item_codes), "warehouse": ("in", all_leaves)},
		fields=["item_code", "warehouse", "actual_qty"],
	)
	stock_by_item_leaf = {}
	for b in bins:
		if flt(b.actual_qty) > 0:
			stock_by_item_leaf.setdefault(b.item_code, set()).add(b.warehouse)

	updated = 0
	for it in items:
		leaves_with_stock = stock_by_item_leaf.get(it.item_code, set())
		chosen = None
		for wh in configured:
			if any(leaf in leaves_with_stock for leaf in expanded[wh]):
				chosen = wh
				break
		# Fall back to the first configured warehouse so the field stays populated.
		if not chosen:
			chosen = configured[0]
		if chosen != it.website_warehouse:
			frappe.db.set_value("Website Item", it.name, "website_warehouse", chosen)
			updated += 1

	frappe.db.commit()

	if user:
		frappe.publish_realtime(
			"upande_webshop_warehouse_synced",
			{
				"message": _("Updated {0} Website Items based on configured warehouses.").format(updated),
				"indicator": "green",
			},
			user=user,
			after_commit=True,
		)
