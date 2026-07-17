import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, comma_and, flt, unique

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
		# flag >> if redisearch is installed and loaded
		self.is_redisearch_loaded = is_search_module_loaded()
		self._populate_warehouse_qty()

	def _populate_warehouse_qty(self):
		"""Fill each Warehouses row's `qty` with the live Bin total so the form
		shows current stock. In-memory only — not persisted, so the doc stays
		clean. Done server-side so the values arrive with the form (no flaky
		client-side grid refresh)."""
		rows = [r for r in (self.get("warehouses") or []) if r.warehouse]
		if not rows:
			return
		totals = get_warehouse_totals([r.warehouse for r in rows])
		for r in rows:
			r.qty = totals.get(r.warehouse, 0) or 0

	def validate(self):
		self.validate_field_filters(self.filter_fields, self.enable_field_filters)
		self.validate_checkout()
		self.validate_search_index_fields()

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

	def validate_tax_rule(self):
		if not frappe.db.get_value("Tax Rule", {"use_for_shopping_cart": 1}, "name"):
			frappe.throw(frappe._("Set Tax Rule for shopping cart"), ShoppingCartSetupError)

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

	All items — variants, templates and plain — read from core Bin, summing
	actual_qty per warehouse.

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

	# All items read from core Bin, summed per warehouse.
	bin_rows = frappe.db.sql(
		f"""
		SELECT B.warehouse, COALESCE(SUM(B.actual_qty), 0) AS qty
		FROM `tabBin` B
		WHERE B.warehouse IN ({placeholders})
		GROUP BY B.warehouse
		""",
		params,
		as_dict=True,
	)

	qty_by_leaf = {}
	for r in bin_rows:
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


# ---------------------------------------------------------------------------
# Bulk publish
#
# Backend for the "Bulk Publish Items" dialog opened from the Webshop Settings
# form (open_bulk_publish_page button). Previously lived in a standalone Page
# (page/bulk_publish_items); moved here when that orphaned Page was removed.
# ---------------------------------------------------------------------------


def _check_bulk_publish_permission():
	if not frappe.has_permission("Website Item", "create"):
		frappe.throw(_("Not permitted to create Website Items"), frappe.PermissionError)


@frappe.whitelist()
def get_items(
	item_group=None, search=None, hide_published=1, show_templates=0, start=0, page_length=50
):
	"""Return Items matching filters, flagged with whether a Website Item already exists."""
	_check_bulk_publish_permission()

	start = cint(start)
	page_length = min(cint(page_length) or 50, 200)
	hide_published = cint(hide_published)
	show_templates = cint(show_templates)

	has_variants = 1 if show_templates else 0
	conditions = ["i.disabled = 0", "i.has_variants = %(has_variants)s"]
	values = {"has_variants": has_variants}

	if item_group:
		conditions.append("i.item_group = %(item_group)s")
		values["item_group"] = item_group
	if search:
		conditions.append("i.item_name LIKE %(search)s")
		values["search"] = f"%{search}%"
	if hide_published:
		conditions.append("wi.name IS NULL")

	where_clause = " AND ".join(conditions)

	total = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM `tabItem` i
		LEFT JOIN `tabWebsite Item` wi ON wi.item_code = i.item_code
		WHERE {where_clause}
		""",
		values,
	)[0][0]

	values["start"] = start
	values["page_length"] = page_length

	rows = frappe.db.sql(
		f"""
		SELECT
			i.name AS item_code,
			i.item_name,
			i.item_group,
			i.brand,
			i.image,
			CASE WHEN wi.name IS NOT NULL THEN 1 ELSE 0 END AS already_published
		FROM `tabItem` i
		LEFT JOIN `tabWebsite Item` wi ON wi.item_code = i.item_code
		WHERE {where_clause}
		ORDER BY i.item_name ASC
		LIMIT %(start)s, %(page_length)s
		""",
		values,
		as_dict=True,
	)

	return {"items": rows, "total": total}


@frappe.whitelist()
def get_publish_status(item_codes):
	"""Count how many of the given Item codes already have a Website Item.

	Used by the dialog as a realtime-independent progress fallback.
	"""
	_check_bulk_publish_permission()
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)
	item_codes = [c for c in (item_codes or []) if c]
	if not item_codes:
		return {"total": 0, "published": 0}

	published = frappe.db.count("Website Item", filters={"item_code": ("in", item_codes)})
	return {"total": len(item_codes), "published": published}


@frappe.whitelist()
def publish_items(item_codes):
	"""Enqueue bulk publish for the given Item codes. Returns immediately."""
	_check_bulk_publish_permission()

	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)
	item_codes = [c for c in (item_codes or []) if c]
	if not item_codes:
		frappe.throw(_("No items selected"))

	frappe.enqueue(
		"upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings._bulk_publish_worker",
		queue="long",
		timeout=1500,
		item_codes=item_codes,
		user=frappe.session.user,
	)
	return {"queued": len(item_codes)}


def _bulk_publish_worker(item_codes, user):
	"""Background worker: create Website Items and set published=1."""
	from upande_webshop.upande_webshop.doctype.website_item.website_item import (
		make_website_item,
	)

	total = len(item_codes)
	succeeded = 0
	skipped = 0
	failed = 0
	errors = []

	for index, item_code in enumerate(item_codes, start=1):
		try:
			if frappe.db.exists("Website Item", {"item_code": item_code}):
				skipped += 1
			else:
				item_doc = frappe.get_doc("Item", item_code)
				web_item = make_website_item(item_doc.as_dict(), save=False)
				web_item.published = 1
				web_item.flags.ignore_permissions = True
				web_item.save()
				succeeded += 1
		except Exception as exc:
			failed += 1
			if len(errors) < 20:
				errors.append(f"{item_code}: {exc}")
			frappe.log_error(
				title=f"Bulk publish failed for {item_code}",
				message=frappe.get_traceback(),
			)

		if index % 10 == 0 or index == total:
			frappe.db.commit()
			progress = int((index / total) * 100)
			frappe.publish_realtime(
				"webshop_bulk_publish_progress",
				{
					"progress": progress,
					"message": _("Publishing {0} of {1}...").format(index, total),
				},
				user=user,
				after_commit=True,
			)

	frappe.publish_realtime(
		"webshop_bulk_publish_done",
		{
			"succeeded": succeeded,
			"skipped": skipped,
			"failed": failed,
			"total": total,
			"errors": errors,
		},
		user=user,
		after_commit=True,
	)


# ---------------------------------------------------------------------------
# Setup check
#
# The webshop flow depends on a set of custom fields existing on their
# doctypes. Rather than throwing a raw error mid-cart, the Webshop Settings
# "Run Setup Check" button (Actions tab) renders this report inline so an admin
# can see what's missing and how to add it. The same data powers /webshop-setup.
# ---------------------------------------------------------------------------

# required=True fields block the webshop pages when missing (the flow can't run
# without them). required=False are shown in the setup check but never block:
#  - custom_delivery_date: cart falls back to the standard `delivery_date` field
#  - custom_line_code: gated by the Show Line Code on Cart setting
#  - custom_total_stems: written only when the column exists (has_column guarded)
WEBSHOP_REQUIRED_FIELDS = [
	{"doctype": "Website Item", "fieldname": "custom_length", "label": "Stem Length", "fieldtype": "Link", "options": "Stem Length", "required": True, "why": "Lets the product page resolve and display each stem-length variant."},
	{"doctype": "Website Item", "fieldname": "custom_box_type", "label": "Box Type", "fieldtype": "Link", "options": "Box Type", "required": True, "why": "Used for box-type selection and pricing on the product page."},
]

WEBSHOP_QUOTATION_FIELDS = [
	{"doctype": "Quotation", "fieldname": "custom_delivery_point", "label": "Delivery Point", "fieldtype": "Link", "options": "Delivery Point", "required": True, "why": "Where the order is delivered. Required at checkout."},
	{"doctype": "Quotation", "fieldname": "custom_box_type", "label": "Box Type", "fieldtype": "Link", "options": "Box Type", "required": True, "why": "Cart-level box type, propagated to each order line."},
	{"doctype": "Quotation", "fieldname": "custom_line_code", "label": "Line Code", "fieldtype": "Data", "options": "", "required": False, "why": "Optional — only used when 'Show Line Code on Cart' is enabled."},
	{"doctype": "Quotation Item", "fieldname": "custom_length", "label": "Stem Length", "fieldtype": "Link", "options": "Stem Length", "required": True, "why": "Per-line stem length carried from the cart to the order."},
	{"doctype": "Quotation Item", "fieldname": "custom_total_stems", "label": "Total Stems", "fieldtype": "Float", "options": "", "required": False, "why": "Optional — written only when the column exists."},
]

WEBSHOP_SALES_ORDER_FIELDS = [
	{"doctype": "Sales Order", "fieldname": "custom_delivery_point", "label": "Delivery Point", "fieldtype": "Data", "options": "", "required": True, "why": "Where the order is delivered."},
	{"doctype": "Sales Order", "fieldname": "custom_box_type", "label": "Box Type", "fieldtype": "Data", "options": "", "required": True, "why": "Cart-level box type."},
	{"doctype": "Sales Order", "fieldname": "custom_line_code", "label": "Line Code", "fieldtype": "Data", "options": "", "required": False, "why": "Optional — only used when 'Show Line Code on Cart' is enabled."},
	{"doctype": "Sales Order Item", "fieldname": "custom_length", "label": "Length", "fieldtype": "Link", "options": "Stem Length", "required": True, "why": "Per-line stem length."},
	{"doctype": "Sales Order Item", "fieldname": "custom_box_type", "label": "Box Type", "fieldtype": "Link", "options": "Box Type", "required": True, "why": "Per-line box type."},
	{"doctype": "Sales Order Item", "fieldname": "custom_total_stems", "label": "Total Stems", "fieldtype": "Float", "options": "", "required": False, "why": "Optional — written only when the column exists."},
]


def get_setup_check_fields():
	"""Return the list of required fields for the cart doctype actually in use,
	each augmented with whether it exists and a link to add it."""
	use_sales_order = bool(
		frappe.db.get_single_value("Webshop Settings", "use_sales_order_as_cart")
	)
	cart_fields = WEBSHOP_SALES_ORDER_FIELDS if use_sales_order else WEBSHOP_QUOTATION_FIELDS
	fields = WEBSHOP_REQUIRED_FIELDS + cart_fields

	out = []
	for f in fields:
		row = dict(f)
		row["exists"] = bool(frappe.get_meta(f["doctype"]).has_field(f["fieldname"]))
		# Open the Customize Form for the doctype — shows the doctype and all its
		# fields so the admin can add the missing one inline.
		row["new_custom_field_url"] = "/app/customize-form?doc_type={0}".format(
			frappe.utils.quote(f["doctype"])
		)
		out.append(row)
	return {"fields": out, "use_sales_order": use_sales_order}


def get_missing_webshop_fields():
	"""Return required webshop fields that don't yet exist. Only required-and-
	missing fields block the pages; optional ones never block."""
	return [
		f
		for f in get_setup_check_fields()["fields"]
		if f.get("required") and not f["exists"]
	]


def apply_webshop_setup_guard(context):
	"""Guard a webshop page: if any required custom field is missing, swap the
	page for a friendly setup-block template instead of letting the page error
	(or fall through to a Not Found). Returns True if the page was blocked.

	Call at the top of a webshop page's get_context, before any code that reads
	the custom fields.
	"""
	missing = get_missing_webshop_fields()
	if not missing:
		return False

	# Group missing fields by doctype for a clean display.
	groups = {}
	for f in missing:
		groups.setdefault(f["doctype"], []).append(f)

	context.webshop_setup_missing = missing
	context.webshop_setup_groups = groups
	context.body_class = "product-page"
	context.no_cache = 1
	context.title = _("Webshop Setup Needed")
	# Render the friendly block instead of the normal page body.
	context.template = "templates/includes/webshop_setup_block.html"
	return True


@frappe.whitelist()
def get_setup_check_html():
	"""Render the setup-check report as HTML for the Webshop Settings form."""
	if not frappe.has_permission("Webshop Settings", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	data = get_setup_check_fields()
	fields = data["fields"]
	missing = [f for f in fields if not f["exists"]]
	missing_required = [f for f in missing if f.get("required")]

	groups = {}
	for f in fields:
		groups.setdefault(f["doctype"], []).append(f)

	esc = frappe.utils.escape_html
	parts = []

	if not missing:
		parts.append(
			'<div class="alert alert-success" style="margin-bottom:12px;">'
			+ _("All custom fields are configured. The cart and checkout will work.")
			+ "</div>"
		)
	elif missing_required:
		parts.append(
			'<div class="alert alert-danger" style="margin-bottom:12px;">'
			+ _("{0} required field(s) are missing — the shop will show a setup page until they are added.").format(len(missing_required))
			+ "</div>"
		)
	else:
		parts.append(
			'<div class="alert alert-warning" style="margin-bottom:12px;">'
			+ _("{0} optional field(s) are missing. The shop still works; add them for full functionality.").format(len(missing))
			+ "</div>"
		)

	for doctype, rows in groups.items():
		parts.append('<div style="font-weight:600; margin:10px 0 4px;">%s</div>' % esc(doctype))
		parts.append('<table class="table table-bordered" style="font-size:13px;">')
		parts.append(
			"<thead><tr>"
			"<th style='width:80px;'>%s</th><th>%s</th><th>%s</th><th>%s</th><th style='width:120px;'></th>"
			"</tr></thead><tbody>"
			% (_("Status"), _("Field"), _("Type"), _("What it's for"))
		)
		for f in rows:
			status = (
				'<span class="indicator-pill green">%s</span>' % _("OK")
				if f["exists"]
				else '<span class="indicator-pill red">%s</span>' % _("Missing")
			)
			opts = (
				'<div class="text-muted" style="font-size:11px;">%s: %s</div>'
				% (_("Options"), esc(f["options"]))
				if f["options"]
				else ""
			)
			action = (
				""
				if f["exists"]
				else '<a class="btn btn-primary btn-xs" target="_blank" href="%s">%s</a>'
				% (f["new_custom_field_url"], _("Add field"))
			)
			req_pill = (
				'<span class="indicator-pill orange" style="margin-left:4px;">%s</span>' % _("Required")
				if f.get("required")
				else '<span class="indicator-pill gray" style="margin-left:4px;">%s</span>' % _("Optional")
			)
			parts.append(
				"<tr><td>%s</td>"
				"<td><b>%s</b>%s<div class='text-muted' style='font-size:11px;'>%s</div></td>"
				"<td>%s%s</td><td class='text-muted'>%s</td><td>%s</td></tr>"
				% (
					status,
					esc(f["label"]),
					req_pill,
					esc(f["fieldname"]),
					esc(f["fieldtype"]),
					opts,
					esc(f["why"]),
					action,
				)
			)
		parts.append("</tbody></table>")

	return {"html": "".join(parts), "missing": len(missing)}


# ---------------------------------------------------------------------------
# Customer Settings: per-customer warehouse override
# ---------------------------------------------------------------------------
# A customer can be pinned to a specific warehouse via the `customer_warehouse`
# table on Webshop Settings (Customer Settings tab). When a logged-in customer
# has a mapping, the storefront shows stock from THAT warehouse instead of the
# default configured set. Enable/disable still uses the global Stem Length Price
# flag (set_webshop_enabled_stock); this only changes which warehouse the qty is
# read from and gates the listing to that warehouse's items.


def get_customer_warehouse_map():
	"""{customer: warehouse} from the Webshop Settings customer_warehouse table.

	Last row wins on duplicate customers. Empty when no mappings configured."""
	settings = frappe.get_cached_doc("Webshop Settings")
	out = {}
	for row in settings.get("customer_warehouse") or []:
		if row.customer and row.warehouse:
			out[row.customer] = row.warehouse
	return out


def get_warehouse_for_customer(customer):
	"""Warehouse assigned to `customer`, or None when unmapped."""
	if not customer:
		return None
	return get_customer_warehouse_map().get(customer)


def get_session_customer_warehouse():
	"""Warehouse for the logged-in customer, or None.

	Resolves the session user → Customer (via the cart's permission-free helper)
	then looks them up in the customer_warehouse table. None for guests, unmapped
	customers, or when no mappings exist."""
	from upande_webshop.upande_webshop.shopping_cart.cart import _session_customer_name

	mapping = get_customer_warehouse_map()
	if not mapping:
		return None
	customer = _session_customer_name()
	return mapping.get(customer) if customer else None


@frappe.whitelist()
def get_customer_warehouse_rows(warehouse):
	"""Available (item, stem_length, qty, bunch_size) rows for one warehouse.

	Same shape get_warehouse_rows() returns, but scoped to a single `warehouse`
	(group warehouses expanded to leaves, qty reported under the chosen name) so
	the Customer Settings picker reuses the exact shelf/warehouse panel + the
	global enable/disable flow. One row per (warehouse, item) with positive qty;
	stem_length is "" (length is encoded in the variant code, same as the existing
	warehouse picker)."""
	from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses
	from upande_webshop.upande_webshop.doctype.box_type.box_type import (
		_stems_per_bunch_from_uom,
	)

	def _bunch(sales_uom, stock_uom):
		size = _stems_per_bunch_from_uom(sales_uom or stock_uom)
		return size if size and size > 0 else 1

	if not warehouse:
		return []

	if frappe.get_cached_value("Warehouse", warehouse, "is_group") == 1:
		leaves = get_child_warehouses(warehouse) or []
	else:
		leaves = [warehouse]
	if not leaves:
		return []

	placeholders = ",".join(["%s"] * len(leaves))
	bins = frappe.db.sql(
		f"""
		SELECT b.item_code, i.item_name, i.sales_uom, i.stock_uom, b.actual_qty
		FROM `tabBin` b
		JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.warehouse IN ({placeholders}) AND b.actual_qty > 0
		""",
		tuple(leaves),
		as_dict=True,
	)

	agg = {}
	for b in bins:
		row = agg.get(b.item_code)
		if not row:
			row = {
				"shelf": warehouse,
				"item_code": b.item_code,
				"item_name": b.item_name or b.item_code,
				"stem_length": "",
				"shelf_qty": 0,
				"bunch_size": _bunch(b.get("sales_uom"), b.get("stock_uom")),
			}
			agg[b.item_code] = row
		row["shelf_qty"] += int(flt(b.actual_qty))

	rows = [r for r in agg.values() if r["shelf_qty"] > 0]
	rows.sort(key=lambda r: r["item_name"])
	return rows
