import re

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


def _delivery_point_doctype():
	"""Return the Delivery Point doctype name as it exists on THIS site.

	The doctype is named "Delivery Point" (singular) in upande_webshop and
	upande_kaitet, but "Delivery Points" (plural) in upande_tambuzi. Some sites
	(e.g. tambuzi) have BOTH installed — one empty, one populated — so we prefer
	whichever actually holds records, then fall back to whichever exists. The
	cart dropdown query and link validation then target the right table on every
	site. Returns None if neither exists.
	"""
	existing = [n for n in ("Delivery Point", "Delivery Points") if frappe.db.exists("DocType", n)]
	if not existing:
		return None
	# Prefer the doctype that has data — on dual-install sites the records live
	# in only one of them.
	populated = [n for n in existing if frappe.db.count(n)]
	return (populated or existing)[0]


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
	# Box Type may not carry a min_order_qty field on every site — guard the read
	# so a missing column can't 500 the cart.
	if not frappe.get_meta("Box Type").has_field("min_order_qty"):
		return None

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

	When the cart has a Box Type whose pack rate is known, defer to the
	pack-rate packer instead so qty changes / adds keep box ids consistent with
	the box-type selection (rather than reverting to a 1..N placeholder).
	"""
	items = doc.get("items") or []
	if not items:
		return
	child_meta = frappe.get_meta(items[0].doctype)
	if not child_meta.has_field("custom_box_id"):
		return

	# Prefer the cart-level Box Type rate; fall back to the global Webshop
	# Settings pack rate so box ids still pack sensibly when no box type is set.
	# (Per-line rates override at display time in _decorate_items_with_box_info;
	# the packer uses one cart cap for the farm-grouped first-fit layout.)
	box_type = doc.get("custom_box_type")
	pack_rate = 0
	if box_type and frappe.get_meta("Box Type").has_field("packrate"):
		pack_rate = cint(frappe.db.get_value("Box Type", box_type, "packrate") or 0)
	if pack_rate <= 0:
		pack_rate = _global_pack_rate()
	if pack_rate > 0:
		_assign_box_ids_by_pack_rate(doc, pack_rate)
		return

	for idx, item in enumerate(items, start=1):
		if not item.get("custom_box_id"):
			item.custom_box_id = idx


# Farm packing order — mirrors the /order-stock create_order_stock_order script:
# Pendekeza first, then Burguret, then Turaco, then anything else.
_FARM_PACK_ORDER = {"Pendekeza": "0", "Burguret": "1", "Turaco": "2"}


def _farm_of(warehouse):
	"""Reduce a warehouse name to its farm, e.g.
	'Burguret Available for Sale - TL' -> 'Burguret'."""
	w = str(warehouse or "")
	farm = (
		w.replace(" Available for Sale - TL", "")
		.replace(" Receiving Cold Store - TL", "")
		.replace(" - TL", "")
		.strip()
	)
	return farm or "Other"


def _merge_identical_rows(doc):
	"""Merge cart rows that are identical except for qty back into a single line.

	The split helper (`_split_rows_exceeding_pack_rate`) carves an oversized line
	into box-sized sibling rows. When the pack rate later *increases* (a bigger
	box type is chosen), those siblings would otherwise stay split forever, even
	though they now fit in one box. Merging them first — before the re-split below
	— makes the pipeline symmetric: a larger box recombines what a smaller box
	split, a smaller box re-splits the merged total.

	Two rows merge only when they match on every order-relevant attribute:
	item_code, uom, conversion_factor, custom_length, custom_box_type, source
	warehouse, and additional_notes. Requiring additional_notes to match means a
	manually-noted row is never silently folded into another (and split siblings,
	which inherit the parent's notes, still merge). The first row of each group is
	resized to the summed qty; later siblings are dropped. No-op when nothing
	matches, so re-running on an unmergeable cart leaves it untouched.
	"""
	items = doc.get("items") or []
	if len(items) < 2:
		return
	child_meta = frappe.get_meta(items[0].doctype)
	if not child_meta.has_field("custom_box_id"):
		return

	has_total_stems = child_meta.has_field("custom_total_stems")

	def _key(r):
		return (
			r.item_code,
			r.uom or "",
			flt(r.conversion_factor or 1),
			(r.get("custom_length") or "") if child_meta.has_field("custom_length") else "",
			(r.get("custom_box_type") or "") if child_meta.has_field("custom_box_type") else "",
			r.get("custom_source_warehouse") or r.get("warehouse") or "",
			r.get("additional_notes") or "",
		)

	merged = {}
	ordered = []
	changed = False
	for r in items:
		k = _key(r)
		head = merged.get(k)
		if head is None:
			merged[k] = r
			ordered.append(r)
			continue
		# Fold this sibling's qty into the first row sharing its key.
		cf = flt(head.conversion_factor or 1) or 1
		head.qty = cint(head.qty or 0) + cint(r.qty or 0)
		head.stock_qty = head.qty * cf
		if has_total_stems:
			head.custom_total_stems = head.qty * cf
		changed = True

	if changed:
		doc.items = ordered
		for idx, r in enumerate(ordered, start=1):
			r.idx = idx


def _split_rows_exceeding_pack_rate(doc, pack_rate):
	"""Split any cart row whose total stems exceed one box (`pack_rate`) into
	box-sized rows, so a single line never spans more than one box.

	A line of N stems at a pack rate of `cap` stems/box becomes
	ceil(N / cap) rows: full box-sized chunks plus a remainder row. Splitting
	respects bunch granularity — stems = qty(bunches) × conversion_factor, so
	each chunk holds floor(cap / stems_per_bunch) whole bunches. A bunch that's
	itself larger than the box can't be split, so such a row is left whole (the
	packer will still give it its own box id).

	Idempotent: rows produced here are ≤ one box, so re-running this helper on
	an already-split cart is a no-op. New rows inherit every field of the parent
	row except qty/stem totals; they're appended and will be persisted by the
	caller's quotation.save().
	"""
	items = doc.get("items") or []
	if not items:
		return
	child_meta = frappe.get_meta(items[0].doctype)
	if not child_meta.has_field("custom_box_id"):
		return

	cap = cint(pack_rate)
	if cap <= 0:
		return

	has_total_stems = child_meta.has_field("custom_total_stems")
	new_items = []
	changed = False
	# Iterate a snapshot: doc.append("items", …) below mutates the live
	# doc.items list, which `items` aliases. Looping the live list would re-visit
	# (and re-append) the clones we add. Snapshot the originals up front so each
	# source row is processed exactly once.
	for r in list(items):
		cf = flt(r.conversion_factor or 1) or 1
		qty = cint(r.qty or 0)
		total_stems = qty * cf
		# Fits in one box (or can't be split below a single bunch) — keep as-is.
		bunches_per_box = int(cap // cf) if cf else 0
		if total_stems <= cap or bunches_per_box < 1 or qty <= bunches_per_box:
			new_items.append(r)
			continue

		changed = True
		remaining = qty
		first = True
		while remaining > 0:
			chunk = min(bunches_per_box, remaining)
			remaining -= chunk
			if first:
				# Resize the original row in place so its docname (and any
				# manual box label) is preserved on the first chunk.
				r.qty = chunk
				r.stock_qty = chunk * cf
				if has_total_stems:
					r.custom_total_stems = chunk * cf
				new_items.append(r)
				first = False
			else:
				# Copy EVERY field from the parent row, then override only the
				# quantity/stem fields. Whitelisting individual fields here dropped
				# item_name, rate, amount, description, etc., so split rows saved
				# with "Value missing for: Item Name / Amount". Cloning the whole row
				# carries pricing + descriptive fields through; we strip the row's
				# identity (name/idx/parent) so Frappe inserts it as a brand-new
				# child rather than aliasing the original.
				clone = r.as_dict()
				for k in ("name", "idx", "parent", "parentfield", "parenttype",
						"creation", "modified", "modified_by", "owner", "docstatus"):
					clone.pop(k, None)
				clone["qty"] = chunk
				clone["conversion_factor"] = cf
				clone["stock_qty"] = chunk * cf
				if has_total_stems:
					clone["custom_total_stems"] = chunk * cf
				# Re-derive amount-like fields from the carried-over rate so the new
				# row's totals match its (smaller) qty; rate/price_list_rate come
				# straight from the parent. _apply_length_price_db reprices after.
				rate = flt(clone.get("rate") or 0)
				clone["amount"] = rate * chunk
				if clone.get("base_rate") is not None:
					clone["base_amount"] = flt(clone.get("base_rate") or 0) * chunk
				new_items.append(doc.append("items", clone))

	if changed:
		# Reorder so split rows sit next to their origin; idx is re-stamped by
		# the packer below.
		doc.items = new_items


def _assign_box_ids_by_pack_rate(doc, pack_rate):
	"""Pack the cart's item rows into boxes of `pack_rate` stems and stamp a
	`custom_box_id` per box, grouping by farm (Pendekeza, Burguret, Turaco, then
	others). Stems = qty * conversion_factor. Uses first-fit packing: a line joins
	the first open box of its farm that still has room (so any cart item can share
	a box that isn't full yet, regardless of cart order), opening a new box only
	when none fits. Lines keep their cart order; box ids may therefore repeat
	non-contiguously down the list (e.g. box 1, box 2, box 1 again).

	Falls back to the 1..N placeholder when there's no usable pack rate or the
	child doctype lacks custom_box_id.

	Sibling rows left over from a previous (smaller) box are merged back first,
	then rows whose stems exceed one box are split into box-sized rows so a single
	cart line never straddles more than one box; each resulting row then gets its
	own sequential box id. Merge-then-split makes box-type changes symmetric: a
	bigger box recombines lines a smaller box split, a smaller box re-splits them.
	"""
	items = doc.get("items") or []
	if not items:
		return
	if not frappe.get_meta(items[0].doctype).has_field("custom_box_id"):
		return

	cap = cint(pack_rate)
	if cap <= 0:
		# No capacity to pack against — keep the simple placeholder.
		_assign_sequential_box_ids(doc)
		return

	# Recombine any split siblings into their single source line, then carve
	# oversized lines into box-sized rows. Merging first means a pack-rate
	# increase collapses lines a smaller box previously split, and the re-split
	# below re-divides the merged total against the new (larger) capacity.
	_merge_identical_rows(doc)
	_split_rows_exceeding_pack_rate(doc, cap)
	items = doc.get("items") or []

	# Group rows by farm and remember a stable sort key for the farm order.
	groups = {}
	order_keys = {}
	for r in items:
		farm = _farm_of(r.get("custom_source_warehouse") or r.get("warehouse"))
		order_keys[farm] = _FARM_PACK_ORDER.get(farm, "9") + farm
		groups.setdefault(farm, []).append(r)

	# First-fit packing: a line lands in the FIRST already-open box of its farm
	# that still has room, not just the most-recently-opened one. This lets a small
	# line top up an earlier box a bigger line left partly empty, so boxes fill up
	# regardless of cart order — only when no open box fits does a new one open.
	# Box ids stay scoped per farm (a box never mixes farms); the row order in the
	# cart is preserved (we don't reshuffle lines, only which box they reference).
	ordered = []
	box = 0
	for sk in sorted(order_keys.values()):
		farm = sk[1:]
		open_boxes = []  # list of [box_id, fill] for this farm, in open order
		for r in groups[farm]:
			stems = (r.qty or 0) * (r.conversion_factor or 1)
			# Find the first open box this line fits into (fill + stems <= cap).
			target = next((b for b in open_boxes if b[1] + stems <= cap), None)
			if target is None:
				# Nothing fits it (or it's the first line) — open a new box. A line
				# bigger than a whole box still gets its own box id; splitting to box
				# size already happened in _split_rows_exceeding_pack_rate above.
				box += 1
				target = [box, 0]
				open_boxes.append(target)
			r.custom_box_id = target[0]
			target[1] += stems
			ordered.append(r)
		# Farms don't share boxes: the next farm starts fresh (open_boxes is per-farm),
		# and box ids simply continue counting up.

	for idx, r in enumerate(ordered, start=1):
		r.idx = idx
	doc.items = ordered


def _max_box_id_for_delivery_date(delivery_date, exclude_so=None):
	"""Highest `custom_box_id` already used by SUBMITTED Sales Orders delivering
	on `delivery_date`. Returns 0 when none exist (or the field/date is absent).

	Box ids are continuous per delivery day across orders: the day's first order
	uses 1..N, the next continues at N+1, and so on. Only docstatus=1 (submitted)
	orders count — draft/abandoned carts never consume numbers — and the order
	currently being submitted is excluded so re-runs don't double-count it.
	"""
	if not delivery_date:
		return 0
	if not frappe.db.has_column("Sales Order Item", "custom_box_id"):
		return 0
	max_id = frappe.db.sql(
		"""
		SELECT MAX(soi.custom_box_id)
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE so.docstatus = 1
		  AND so.delivery_date = %(dd)s
		  AND (%(exclude)s IS NULL OR so.name != %(exclude)s)
		""",
		{"dd": getdate(delivery_date), "exclude": exclude_so},
	)
	return cint(max_id[0][0]) if (max_id and max_id[0][0] is not None) else 0


def _continue_box_ids_across_orders(doc):
	"""Re-base this order's per-order box ids (1..N) onto the running total for
	its delivery date, so box numbering continues from where the previous order
	for that day stopped.

	Call this at checkout AFTER box ids are assigned and the delivery date is
	finalized, but BEFORE submit. Adds the day's current max box id (over already
	submitted Sales Orders) as an offset to every row's custom_box_id. No-op when
	the child doctype lacks custom_box_id, the cart is empty, or it's the day's
	first order (offset 0).
	"""
	items = doc.get("items") or []
	if not items:
		return
	if not frappe.get_meta(items[0].doctype).has_field("custom_box_id"):
		return

	offset = _max_box_id_for_delivery_date(doc.get("delivery_date"), exclude_so=doc.get("name"))
	if offset <= 0:
		return
	for r in items:
		if r.get("custom_box_id"):
			r.custom_box_id = cint(r.custom_box_id) + offset


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
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	if quotation.meta.has_field("custom_delivery_point") and not (quotation.get("custom_delivery_point") or "").strip():
		return _("Please select a Delivery Point before placing your order.")
	# Consignee is required at checkout (webshop only — the field's reqd flag is
	# left off so desk / imported orders are unaffected).
	if quotation.meta.has_field("custom_consignee") and not quotation.get("custom_consignee"):
		return _("Please select a Consignee before placing your order.")
	# Line Code is only required when the cart shows it.
	if (
		cint(cart_settings.get("show_cart_line_code", 1))
		and quotation.meta.has_field("custom_line_code")
		and not (quotation.get("custom_line_code") or "").strip()
	):
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

	# Sales-Order-as-cart mode: the cart IS a draft Sales Order. Checkout just
	# submits it in place (no Quotation→SO conversion) and reserves stems.
	if quotation.doctype == "Sales Order":
		return _place_sales_order_cart(quotation, cart_settings)

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

	# Copy custom_delivery_date from quotation if present
	# ERPNext's _make_sales_order may not copy this custom field
	if quotation.meta.has_field("custom_delivery_date") and quotation.custom_delivery_date:
		sales_order.delivery_date = quotation.custom_delivery_date

	# Ensure delivery_date is at least tomorrow (next day from today).
	# Sales Order requires a future date; if the quotation didn't carry a fresh
	# date, fall back to tomorrow on both the header and every line item.
	tomorrow = add_days(nowdate(), 1)
	if not sales_order.delivery_date or getdate(sales_order.delivery_date) < getdate(tomorrow):
		sales_order.delivery_date = tomorrow
	for so_item in sales_order.get("items") or []:
		if not so_item.delivery_date:
			so_item.delivery_date = sales_order.delivery_date
		if getdate(so_item.delivery_date) < getdate(tomorrow):
			so_item.delivery_date = tomorrow

	if not cint(cart_settings.get("allow_items_not_in_stock")):
		# Refresh warehouse pointers before validating; the cart UI doesn't always
		# set them on append.
		for item in sales_order.get("items"):
			item.warehouse = frappe.db.get_value(
				"Website Item", {"item_code": item.item_code}, "website_warehouse"
			)
		_validate_cart_stock(sales_order)

	# Box numbering continues from the previous order for this delivery date:
	# now that delivery_date is finalized above, re-base the 1..N box ids onto
	# the day's running total before the order is submitted and its boxes count.
	_continue_box_ids_across_orders(sales_order)

	# _make_sales_order may not carry kaitet's mandatory custom fields across from
	# the Quotation; stamp the roses defaults before insert.
	_apply_kaitet_order_defaults(sales_order, frappe._dict({"doctype": "Customer", "name": sales_order.customer}))
	# Stamp each line's source warehouse from its shelf stock so the SO-approval
	# Material Transfer (handle_sales_order_approval) has a source→target to move.
	_apply_shelf_source_warehouse(sales_order)
	_sync_ordered_stems(sales_order)

	sales_order.flags.ignore_permissions = True
	sales_order.insert()
	_finalize_kaitet_order_name(sales_order)
	sales_order.submit()

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return sales_order.name


def _place_sales_order_cart(so, cart_settings):
	"""Submit a draft Sales-Order cart in place.

	Used when "Use Sales Order as Cart" is on: the cart already IS the order, so
	checkout submits it (docstatus 0→1) rather than converting a Quotation. Each
	line keeps its chosen source warehouse.

	Stock availability is validated up-front (see _validate_cart_stock); no
	per-length reservation happens here. Each line keeps its chosen source
	warehouse so submission draws down core Bin as usual.
	"""
	so.company = cart_settings.company

	# Default delivery to at least tomorrow on header and lines.
	tomorrow = add_days(nowdate(), 1)
	if not so.delivery_date or getdate(so.delivery_date) < getdate(tomorrow):
		so.delivery_date = tomorrow
	for item in so.get("items") or []:
		if not item.delivery_date or getdate(item.delivery_date) < getdate(tomorrow):
			item.delivery_date = so.delivery_date

	_assign_sequential_box_ids(so)
	# Continue box numbering from the previous order for this delivery date (the
	# date is finalized just above). Excludes this SO itself — it's a draft cart
	# (docstatus 0) so the submitted-only query already skips it, but pass its
	# name for safety against re-runs.
	_continue_box_ids_across_orders(so)

	# Stamp each line's source warehouse from its shelf stock so the SO-approval
	# Material Transfer (handle_sales_order_approval) has a source→target to move.
	_apply_shelf_source_warehouse(so)
	_sync_ordered_stems(so)
	so.flags.ignore_permissions = True
	so.order_type = "Sales"  # leave the cart; becomes a normal Sales Order
	so.save()
	_finalize_kaitet_order_name(so)
	so.submit()  # fires on_sales_order_submit → reserves each line's stems once

	# Clear the active-cart selection so the next view doesn't reopen this order.
	frappe.cache.delete_value(_active_cart_customer_key())

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return so.name


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
	# Two-step flow: "Save Order" leaves a Sales-Order-as-cart in draft; the
	# follow-up "Submit Order" button calls submit_cart_order() to finalize it.
	# Quotation carts still submit here unless the site keeps them as drafts.
	if quotation.doctype == "Quotation" and not cint(cart_settings.save_quotations_as_draft):
		quotation.submit()

	return quotation.name


@frappe.whitelist()
def submit_cart_order():
	"""Submit the draft Sales-Order cart (step 2 of Save → Submit).

	"Save Order" leaves the SO in draft; this takes it draft → submitted
	(docstatus 0→1), firing on_submit (handle_sales_order_approval / stem
	reservation). Re-validates required fields and stock first so the second
	click can't bypass the same gates the save did.
	"""
	quotation = _get_cart_quotation()
	if quotation.doctype != "Sales Order":
		frappe.throw(_("This cart has no Sales Order to submit."))
	if cint(quotation.docstatus) == 1:
		return quotation.name  # already submitted — idempotent

	required_err = _check_required_cart_fields(quotation)
	if required_err:
		return {"error": required_err}
	box_err = _check_box_type_min_order_qty(quotation)
	if box_err:
		return {"error": box_err}

	cart_settings = frappe.get_cached_doc("Webshop Settings")
	if not cint(cart_settings.get("allow_items_not_in_stock")):
		_validate_cart_stock(quotation)

	_apply_shelf_source_warehouse(quotation)
	quotation.flags.ignore_permissions = True
	_finalize_kaitet_order_name(quotation)
	quotation.submit()

	# Clear the active-cart selection so the next view starts a fresh cart.
	frappe.cache.delete_value(_active_cart_customer_key())
	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return quotation.name


def _get_per_stem_rate(item_code, custom_length, currency, price_list, uom=None):
	"""Fetch per-stem price from Item Price, converted to `currency`.

	The catalog is priced in one base currency (the price list's currency). We
	read the base rate and convert to the requested `currency` via exchange
	rates, so customers transact in their own currency without per-currency
	Item Prices.
	First tries matching by uom (bunch-specific price), then stock_uom (per-stem).
	"""
	base_currency = frappe.db.get_value("Price List", price_list, "currency")
	# Filter by price list only — the currency is the price list's currency.
	base_filters = {
		"item_code": item_code,
		"price_list": price_list,
	}

	def conv(rate):
		return _convert_rate(flt(rate), base_currency, currency)

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
			per_stem = flt(price_records[0].price_list_rate) / conversion_factor if conversion_factor else flt(price_records[0].price_list_rate)
			return conv(per_stem)

	# Fall back to stock UOM (Stems) price — already per-stem
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	price_records = frappe.db.get_all(
		"Item Price",
		filters={**base_filters, "uom": stock_uom},
		fields=["price_list_rate"],
		limit=1,
	)
	if price_records:
		return conv(price_records[0].price_list_rate)

	# Last resort: any price for this item
	price_records = frappe.db.get_all(
		"Item Price",
		filters=base_filters,
		fields=["price_list_rate"],
		limit=1,
	)
	if price_records:
		return conv(price_records[0].price_list_rate)
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
	  - Plain items read core Bin too: Bin has no length dimension, so a
	    length-specific ask falls back to the item's total Bin qty across the
	    warehouse(s).
	"""
	from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
		get_session_customer_warehouse,
	)
	from upande_webshop.upande_webshop.product_data_engine.query import (
		_all_storefront_warehouses,
		_resolve_warehouses,
	)
	from upande_webshop.upande_webshop.utils.shelf_stock import (
		get_shelf_qty,
		use_shelf_stock,
	)

	item_meta = frappe.db.get_value(
		"Item", item_code, ["has_variants", "variant_of"], as_dict=True
	) or frappe._dict()
	is_variant_or_template = bool(item_meta.has_variants) or bool(item_meta.variant_of)

	# Customer-warehouse override takes priority: when the logged-in customer is
	# pinned to a warehouse (Customer Settings), availability — and the cart's
	# source warehouse — read from THAT warehouse's Bin, even in shelf mode. This
	# keeps the add-to-cart check in sync with the per-customer storefront stock.
	customer_wh = get_session_customer_warehouse()
	if customer_wh:
		leaves = _resolve_warehouses(customer_wh)
		if not leaves:
			return 0
		total = frappe.db.sql(
			"""SELECT COALESCE(SUM(actual_qty), 0)
			   FROM `tabBin`
			   WHERE item_code = %s AND warehouse IN ({})""".format(
				",".join(["%s"] * len(leaves))
			),
			[item_code, *leaves],
		)
		return flt(total[0][0]) if total else 0

	# Plain items read from the shelf when shelf mode is on, scoped to the given
	# stem length if any. Not warehouse-scoped.
	if not is_variant_or_template and use_shelf_stock():
		return get_shelf_qty(item_code, custom_length or None)

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

	# Plain items read core Bin, same source as variants. Bin has no length
	# dimension, so a length-specific ask falls back to the item's total Bin qty.
	total = frappe.db.sql(
		"""SELECT COALESCE(SUM(actual_qty), 0)
		   FROM `tabBin`
		   WHERE item_code = %s AND warehouse IN ({})""".format(
			",".join(["%s"] * len(warehouses))
		),
		[item_code, *warehouses],
	)
	return flt(total[0][0]) if total else 0


def _sync_ordered_stems(doc):
	"""Stamp each line's `custom_ordered_quantity` ("Ordered Stems") with its
	total stems (qty × conversion_factor).

	kaitet's "Enforce Ordered Stems Non-zero" Server Script throws on any Roses
	Sales Order whose non-"Mix Box" line has custom_ordered_quantity == 0. That
	script runs on the save/validate event even with controller ignore_validate
	set, so this must populate the field on the in-memory doc BEFORE save(), not
	after. No-op on sites/doctypes without the column (mona, tambuzi, Quotation).
	"""
	items = doc.get("items") or []
	if not items:
		return
	if not frappe.db.has_column(items[0].doctype, "custom_ordered_quantity"):
		return
	for item in items:
		cf = flt(_stems_per_bunch_from_uom(item.uom)) if item.uom else flt(item.conversion_factor or 1)
		stems = flt(item.qty) * (cf or 1)
		if stems > 0:
			item.custom_ordered_quantity = stems


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
			frappe.db.set_value(child_dt, item.name, db_fields, update_modified=False)
		net_total += flt(item.amount)

	# Always re-derive parent totals from the per-stem amounts we just computed and
	# persist + sync them, even when no rate changed. ERPNext's calculate_taxes_and_totals
	# (run during quotation.save() before this) leaves grand_total based on qty×rate, which
	# diverges from our per-stem net_total. Gating this on `any_changed` left grand_total
	# stale on qty-only updates — the Net Total ("total") refreshed while Grand Total didn't.
	frappe.db.set_value(
		parent_dt, quotation.name,
		{
			"total": net_total,
			"net_total": net_total,
			"grand_total": net_total,
			"rounded_total": net_total,
		},
		update_modified=False
	)
	quotation.total = net_total
	quotation.net_total = net_total
	quotation.grand_total = net_total
	quotation.rounded_total = net_total


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
		_sync_ordered_stems(quotation)
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


def _box_pack_rate(box_type):
	"""Stems-per-box for a Box Type, parsed from its `packrate` field.

	`Box Type.packrate` is a Select of stem counts ("240", "120", ...). Returns
	an int, or 0 when the box type / pack rate is missing or unparseable (0 →
	"no pack rate", so the caller skips the Box ID).
	"""
	if not box_type:
		return 0
	try:
		return int(flt(frappe.db.get_value("Box Type", box_type, "packrate") or 0))
	except (TypeError, ValueError):
		return 0


def _global_pack_rate():
	"""Stems-per-box default from Webshop Settings.packrate (a Select of stem
	counts). 0 when unset/unparseable. The fallback when a line carries no rate."""
	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.meta.has_field("packrate"):
		return 0
	try:
		return int(flt(settings.get("packrate") or 0))
	except (TypeError, ValueError):
		return 0


def _line_pack_rate_field(child_dt):
	"""Return the per-line pack-rate fieldname present on this cart's item
	doctype, or None. kaitet ships `custom_packrate` (Link → Packrate) on Sales
	Order Item and `custom_pack_rate` (Float) on Quotation Item."""
	meta = frappe.get_meta(child_dt)
	for fieldname in ("custom_packrate", "custom_pack_rate"):
		if meta.has_field(fieldname):
			return fieldname
	return None


def _coerce_pack_rate(value):
	"""A line's pack-rate value may be a Link to the Packrate doctype (whose name
	IS the stem count, e.g. "240") or a raw number. Return it as an int, 0 if
	empty/unparseable."""
	if value in (None, ""):
		return 0
	try:
		return int(flt(value))
	except (TypeError, ValueError):
		# Link to Packrate — its `packrate` field holds the int.
		rate = frappe.db.get_value("Packrate", value, "packrate")
		try:
			return int(flt(rate or 0))
		except (TypeError, ValueError):
			return 0


def _pack_rate_value_for_field(child_dt, fieldname, rate):
	"""Coerce an int stems-per-box `rate` into the value the line field expects.

	`custom_packrate` (Sales Order Item) is a Link → Packrate whose record name is
	the stem count ("240"); store the matching Packrate name if it exists.
	`custom_pack_rate` (Quotation Item) is a Float; store the number. Returns None
	when there's nothing sensible to store (so the caller leaves the field blank).
	"""
	if not rate or rate <= 0:
		return None
	options = frappe.get_meta(child_dt).get_field(fieldname).options
	if options == "Packrate":
		name = str(rate)
		return name if frappe.db.exists("Packrate", name) else None
	return rate


def _line_pack_rate(line, doc):
	"""Resolve the effective stems-per-box for a single cart line.

	Precedence: the line's own pack-rate field overrides everything; then the
	cart-level Box Type's rate; then the global Webshop Settings default. Returns
	0 only when none of those yield a usable rate.
	"""
	field = _line_pack_rate_field(line.doctype)
	if field:
		rate = _coerce_pack_rate(line.get(field))
		if rate > 0:
			return rate

	box_rate = _box_pack_rate(doc.get("custom_box_type"))
	if box_rate > 0:
		return box_rate

	return _global_pack_rate()


def _decorate_items_with_box_info(doc):
	"""Stamp each cart row with `_box_id` and `_box_label` for display.

	`_box_id` = ceil(total_stems / pack_rate): the number of boxes the line
	fills. The pack rate is resolved per line (`_line_pack_rate`): the line's own
	pack-rate field wins, then the cart-level Box Type, then the global Webshop
	Settings default. 0 when no rate or no stems (template hides it then).

	`_pack_rate` is the resolved per-line rate, surfaced so the cart UI can show
	and edit it. `_box_label` mirrors the row's optional `custom_box_label` text
	when that column exists — display only, never required.
	"""
	import math

	child_dt = doc.items[0].doctype if doc.get("items") else None
	has_box_label = bool(child_dt) and frappe.db.has_column(child_dt, "custom_box_label")

	for d in doc.get("items", []):
		total_stems = flt(d.get("custom_total_stems") or 0)
		pack_rate = _line_pack_rate(d, doc)
		d._pack_rate = pack_rate
		d._box_id = int(math.ceil(total_stems / pack_rate)) if (pack_rate and total_stems) else 0
		d._box_label = (d.get("custom_box_label") or "") if has_box_label else ""


def decorate_quotation_doc(doc):
	_decorate_items_with_box_info(doc)
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


def _ensure_contact_linked_to_customer(contact_name, customer_name):
	"""Link a Contact to a Customer if not already linked.

	The webshop authorizes a user against a Customer via Portal User. ERPNext's
	Sales Order validation additionally requires the contact_person to be a
	Contact *of* that customer (a Dynamic Link). When a portal user's Contact
	isn't linked, the cart save fails with "Contact Person does not belong to
	the {customer}". We add the missing link so authorized portal users can
	place orders for their customer.
	"""
	if not contact_name or not customer_name:
		return
	already = frappe.db.exists(
		"Dynamic Link",
		{
			"parent": contact_name,
			"parenttype": "Contact",
			"link_doctype": "Customer",
			"link_name": customer_name,
		},
	)
	if already:
		return
	contact = frappe.get_doc("Contact", contact_name)
	contact.append("links", {"link_doctype": "Customer", "link_name": customer_name})
	contact.flags.ignore_permissions = True
	contact.save()


def _active_cart_customer_key(user=None):
	return f"active_cart_customer:{user or frappe.session.user}"


def _user_is_portal_user_of(customer, user=None):
	"""True if `user` is a Portal User on `customer` (rep authorised on it)."""
	user = user or frappe.session.user
	return bool(
		frappe.db.exists(
			"Portal User", {"parent": customer, "parenttype": "Customer", "user": user}
		)
	)


@frappe.whitelist()
def set_active_cart_customer(customer):
	"""Set which customer's cart the session is currently viewing/editing.

	A sales rep is a Portal User on several customers; this picks the active one
	so /cart, update_cart and checkout all operate on that customer's draft SO.
	Rejected if the user isn't authorised on the customer (unless admin).
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer))

	is_admin = user == "Administrator" or "System Manager" in frappe.get_roles(user)
	if not is_admin and not _user_is_portal_user_of(customer, user):
		frappe.throw(
			_("You are not authorised to act for customer {0}.").format(customer),
			frappe.PermissionError,
		)

	frappe.cache.set_value(_active_cart_customer_key(user), customer)
	return {"customer": customer}


def _active_cart_customer(user=None):
	"""The session's selected cart customer, if still valid for this user."""
	user = user or frappe.session.user
	customer = frappe.cache.get_value(_active_cart_customer_key(user))
	if not customer:
		return None
	is_admin = user == "Administrator" or "System Manager" in frappe.get_roles(user)
	if is_admin or _user_is_portal_user_of(customer, user):
		return customer
	return None


@frappe.whitelist()
def get_cart_customers():
	"""Customers (with an open draft-SO cart) the rep may switch between on /cart.

	Returns [{customer, has_cart, active}]. Always includes customers the user
	is a Portal User on; flags which already have an open Shopping Cart SO and
	which is the active selection.
	"""
	user = frappe.session.user
	if user == "Guest":
		return []

	portal_customers = frappe.get_all(
		"Portal User",
		filters={"user": user, "parenttype": "Customer"},
		pluck="parent",
	)
	portal_customers = list(dict.fromkeys(portal_customers))

	cart_sos = frappe.get_all(
		"Sales Order",
		filters={
			"contact_email": user,
			"order_type": "Shopping Cart",
			"docstatus": 0,
		},
		fields=["name", "customer", "total_qty"],
	)
	# customer -> total item qty across their open cart(s)
	cart_qty = {}
	for so in cart_sos:
		cart_qty[so.customer] = cart_qty.get(so.customer, 0) + (so.total_qty or 0)
	with_carts = set(cart_qty)

	# Union: portal customers + any customer that already has a cart for this user.
	names = list(dict.fromkeys(list(portal_customers) + list(with_carts)))
	active = _active_cart_customer(user)
	rows = [
		{
			"customer": n,
			"customer_name": frappe.db.get_value("Customer", n, "customer_name") or n,
			"has_cart": n in with_carts,
			"cart_qty": int(cart_qty.get(n, 0)),
			"active": n == active,
		}
		for n in names
	]
	rows.sort(key=lambda r: (not r["has_cart"], r["customer_name"].lower()))
	return rows


def _get_cart_doc(party=None):
	"""Return the open draft cart document of the configured doctype.

	For "Sales Order" mode, the party must be a Customer (Sales Order has no
	`quotation_to`). If `get_party()` returns a Lead, we still need a Customer —
	we fall back to Quotation mode for that session rather than silently
	promoting the Lead, which is a destructive side-effect for a cart action.
	"""
	if not party:
		party = get_party()

	# The cart always operates on the Customer linked to the logged-in portal
	# user (resolved by get_party()). There is no customer switcher — each portal
	# user places Sales Orders for their own customer only.

	target_doctype = _cart_doctype()

	# Sales Order can't accept a Lead. If we don't have a Customer in hand,
	# degrade to Quotation for this request so the cart still works.
	if target_doctype == "Sales Order" and (not party or party.doctype != "Customer"):
		target_doctype = "Quotation"

	# A portal user authorized on the Customer must be able to order for it.
	# ERPNext validates contact_person belongs to the customer, so ensure the
	# session user's Contact is linked before any cart save (new or existing).
	if target_doctype == "Sales Order" and party and party.doctype == "Customer":
		_session_contact = frappe.db.get_value(
			"Contact", {"email_id": frappe.session.user}
		)
		if _session_contact:
			_ensure_contact_linked_to_customer(_session_contact, party.name)

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
					"naming_series": get_shopping_cart_settings().get("quotation_series")
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

		_apply_kaitet_order_defaults(qdoc, party)

		qdoc.flags.ignore_permissions = True
		qdoc.run_method("set_missing_values")
		apply_cart_settings(party, qdoc)

	return qdoc


# kaitet's Sales Order has four mandatory custom fields with no UI on the
# storefront. Stamp the roses-business-unit defaults so cart saves / checkout
# don't trip "Value missing" validation. Every write is guarded by has_field so
# this is a no-op on sites without these fields (tambuzi, mona).
_KAITET_SO_DEFAULTS = {
	"custom_sales_order_type": "Roses",
	"custom_business_unit": "Roses",
	"custom_farm": "Kapkolia",
}


def _apply_shelf_source_warehouse(doc):
	"""Stamp each line's `custom_source_warehouse` for a Shopping Cart order.

	The source warehouse is chosen per item as the one most used on that item's
	previous Sales Order lines, restricted to the approved set (see
	get_history_source_warehouse) with a priority fallback. `warehouse` stays the
	delivery target. With both set and custom_sales_order_type == "Roses",
	so_delivery_warehouse.handle_sales_order_approval builds the source→target
	Material Transfer on submit.

	No-op unless the field exists; never overwrites a value already set on a line.
	"""
	from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
		get_warehouse_for_customer,
	)
	from upande_webshop.upande_webshop.utils.shelf_stock import (
		get_history_source_warehouse,
	)

	items = doc.get("items") or []
	if not items:
		return
	# custom_source_warehouse and custom_length live on the CHILD (Sales Order
	# Item / Quotation Item), not the parent — check the child's meta.
	child_meta = frappe.get_meta(items[0].doctype)
	if not child_meta.has_field("custom_source_warehouse"):
		return

	# When the order's customer is pinned to a warehouse (Customer Settings), every
	# line sources from THAT warehouse — the same one their stock was shown from and
	# added to the cart from. Otherwise each line's source is the one most used for
	# that item on previous Sales Orders (approved set, with a priority fallback),
	# so cart orders converge on the warehouses operations actually pick from rather
	# than wherever shelf stock happens to sit. Never overwrites a value already set.
	customer_wh = get_warehouse_for_customer(_cart_party_name(doc))
	for item in items:
		if item.get("custom_source_warehouse"):
			continue
		item.custom_source_warehouse = customer_wh or get_history_source_warehouse(item.item_code)


def stamp_source_warehouse_on_submit(doc, method=None):
	"""Sales Order before_submit hook: stamp each line's source warehouse from its
	shelf stock, however the SO is submitted (cart button, desk, or API).

	The cart's own checkout calls _apply_shelf_source_warehouse before submit, but
	an SO can also be submitted straight from the desk; this hook guarantees the
	source warehouse is set in every path. Guarded to shopping-cart orders so it
	never touches manually-built / allocation-path SOs that set their own source."""
	if doc.get("order_type") != "Shopping Cart":
		return
	_apply_shelf_source_warehouse(doc)


def _apply_kaitet_order_defaults(doc, party):
	meta = doc.meta
	for fieldname, value in _KAITET_SO_DEFAULTS.items():
		if meta.has_field(fieldname) and not doc.get(fieldname):
			doc.set(fieldname, value)

	# Order Name is a free-form label; mirror the manual roses pattern of using
	# the customer name (the SO-number suffix is appended at submit, see
	# _finalize_kaitet_order_name).
	if meta.has_field("custom_order_name") and not doc.get("custom_order_name"):
		customer_name = None
		if party and party.doctype == "Customer":
			customer_name = frappe.db.get_value("Customer", party.name, "customer_name")
		doc.set("custom_order_name", customer_name or (party.name if party else ""))


def _finalize_kaitet_order_name(doc):
	"""Append the SO-number suffix to custom_order_name once the doc is named,
	mirroring the manual roses pattern (e.g. "OASIS-07324"). No-op when the field
	is absent or the suffix is already present.
	"""
	if not doc.meta.has_field("custom_order_name"):
		return

	# Trailing numeric block of the SO name (e.g. SO-2026-07324 -> 07324).
	match = re.search(r"(\d+)$", doc.name or "")
	if not match:
		return
	suffix = match.group(1)

	base = (doc.get("custom_order_name") or "").strip()
	if base.endswith(f"-{suffix}"):
		return
	new_name = f"{base}-{suffix}" if base else suffix
	doc.db_set("custom_order_name", new_name, update_modified=False)


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

	# Force the order currency to the customer's accounting currency. ERPNext
	# derives currency from the price list, but the receivable entry must be in
	# the customer's default_currency — otherwise posting fails with
	# "Accounting Entry ... can only be made in currency: X".
	#
	# We set currency + conversion rates directly rather than via
	# set_missing_values(): on a Sales Order that method calls
	# set_missing_lead_customer_details → _get_party_details, which does a
	# throwing has_permission("Customer") check that portal/Website users fail.
	party_name = _cart_party_name(quotation)
	if party_name and frappe.db.exists("Customer", party_name):
		customer_currency = frappe.db.get_value("Customer", party_name, "default_currency")
		if customer_currency and quotation.currency != customer_currency:
			from erpnext.setup.utils import get_exchange_rate

			company_currency = frappe.get_cached_value(
				"Company", quotation.company, "default_currency"
			)
			conv = 1.0
			if company_currency and company_currency != customer_currency:
				conv = flt(
					get_exchange_rate(customer_currency, company_currency, args="for_selling")
				) or 1.0

			quotation.currency = customer_currency
			quotation.price_list_currency = customer_currency
			quotation.conversion_rate = conv
			quotation.plc_conversion_rate = conv
			quotation.run_method("calculate_taxes_and_totals")

	if hasattr(frappe.local, "cookie_manager"):
		# set it in cookies for using in product page
		frappe.local.cookie_manager.set_cookie(
			"selling_price_list", quotation.selling_price_list
		)


def _price_list_has_items(price_list):
	"""True if the price list has at least one Item Price (i.e. it can price the catalog)."""
	return bool(price_list) and frappe.db.exists("Item Price", {"price_list": price_list})


def _base_price_list():
	"""The catalog's base selling price list — the populated one the webshop
	prices from. Its rate is converted to the customer's currency via exchange
	rates, so item prices don't need to be duplicated per currency.

	We pick the enabled selling price list with the most Item Prices (the real
	catalog), cached per request. Falls back to the USD resolver if no list has
	any prices.
	"""
	cached = getattr(frappe.local, "_upande_base_price_list", None)
	if cached:
		return cached

	rows = frappe.db.sql(
		"""
		SELECT ip.price_list AS price_list, COUNT(*) AS c
		FROM `tabItem Price` ip
		JOIN `tabPrice List` pl ON pl.name = ip.price_list
		WHERE pl.selling = 1 AND pl.enabled = 1
		GROUP BY ip.price_list
		ORDER BY c DESC
		LIMIT 1
		""",
		as_dict=True,
	)
	if rows:
		frappe.local._upande_base_price_list = rows[0].price_list
		return rows[0].price_list

	from upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices import (
		_resolve_price_list,
	)

	return _resolve_price_list()


def _customer_default_price_list(customer_name):
	"""Customer's default price list (or its Customer Group's), read without a
	permission check. Portal/Website users can't `get_doc("Customer")`, so we
	read fields directly via the DB.
	"""
	if not customer_name:
		return None
	pl, group = frappe.db.get_value(
		"Customer", customer_name, ["default_price_list", "customer_group"]
	) or (None, None)
	if pl:
		return pl
	if group:
		return frappe.db.get_value("Customer Group", group, "default_price_list")
	return None


def _set_price_list(cart_settings, quotation=None):
	"""Resolve the selling price list used to *read* item rates.

	Currency is handled separately (the order currency is forced to the
	customer's accounting currency and ERPNext converts via exchange rates).
	So here we want the price list that actually has prices:

	  1. Customer's explicit default_price_list — only if it carries Item Prices.
	  2. The base catalog price list (the populated one), converted by FX.
	"""
	party_name = _cart_party_name(quotation) if quotation else get_party().get("name")
	selling_price_list = None

	if party_name and frappe.db.exists("Customer", party_name):
		customer_pl = _customer_default_price_list(party_name)
		if _price_list_has_items(customer_pl):
			selling_price_list = customer_pl

	# Fall back to the populated base catalog (FX converts to customer currency).
	if not selling_price_list:
		selling_price_list = _base_price_list()

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
		frappe.throw(
			_("Line Code is not set up yet. Open the Webshop Setup page to add it: {0}").format(
				'<a href="/webshop-setup">/webshop-setup</a>'
			)
		)

	value = ((line_code or "").strip().upper()) or None
	frappe.db.set_value(
		quotation.doctype, quotation.name, "custom_line_code", value, update_modified=False
	)
	return {"name": quotation.name, "line_code": value or ""}


@frappe.whitelist()
def update_cart_item_box_label(child_docname, box_label=None):
	"""Save the optional per-item Box Label on a cart row (display-only field).

	Writes `custom_box_label` directly on the Quotation/Sales Order Item row.
	No-op (silently) when the column isn't present on this site, so sites
	without the field don't error. The row is matched by its child docname and
	verified to belong to the current cart before writing.
	"""
	quotation = _get_cart_quotation()
	child_dt = quotation.items[0].doctype if quotation.get("items") else None
	if not child_dt or not frappe.db.has_column(child_dt, "custom_box_label"):
		return {"box_label": ""}

	# Only allow editing rows that belong to this cart.
	row = next((i for i in quotation.get("items") if i.name == child_docname), None)
	if not row:
		return {"box_label": ""}

	value = (box_label or "").strip() or None
	frappe.db.set_value(child_dt, child_docname, "custom_box_label", value, update_modified=False)
	return {"name": child_docname, "box_label": value or ""}


@frappe.whitelist()
def update_cart_item_box_id(child_docname, box_id=None):
	"""Persist a manually-edited Box ID on a cart row.

	The cart auto-assigns `custom_box_id` by packing lines into boxes of the
	Box Type's pack rate, but the user may override it. This writes the edited
	value directly to the row (like the box label) without re-packing, so the
	override sticks until the cart structure changes (qty/box-type change),
	which re-runs the packer. No-op when the column is absent. The row is
	verified to belong to the current cart before writing.
	"""
	quotation = _get_cart_quotation()
	child_dt = quotation.items[0].doctype if quotation.get("items") else None
	if not child_dt or not frappe.db.has_column(child_dt, "custom_box_id"):
		return {"box_id": None}

	row = next((i for i in quotation.get("items") if i.name == child_docname), None)
	if not row:
		return {"box_id": None}

	value = cint(box_id) if box_id not in (None, "") else None
	if value is not None and value < 1:
		value = 1
	frappe.db.set_value(child_dt, child_docname, "custom_box_id", value, update_modified=False)
	return {"name": child_docname, "box_id": value}


@frappe.whitelist()
def update_cart_item_pack_rate(child_docname, pack_rate=None):
	"""Persist a manually-edited per-line pack rate on a cart row.

	The line defaults to the global Webshop Settings pack rate; this lets the user
	override it per line. After writing, the line's box count (_box_id) is
	recomputed from the new rate. Blank clears the override so the line falls back
	to the cart Box Type / global default. No-op when no per-line field exists.
	"""
	quotation = _get_cart_quotation()
	child_dt = quotation.items[0].doctype if quotation.get("items") else None
	field = _line_pack_rate_field(child_dt) if child_dt else None
	if not field:
		return {"pack_rate": None}

	row = next((i for i in quotation.get("items") if i.name == child_docname), None)
	if not row:
		return {"pack_rate": None}

	rate = cint(pack_rate) if pack_rate not in (None, "") else 0
	value = _pack_rate_value_for_field(child_dt, field, rate) if rate > 0 else None
	frappe.db.set_value(child_dt, child_docname, field, value, update_modified=False)

	# Reflect the new rate in the line's box count for the response.
	row.set(field, value)
	import math

	effective = _line_pack_rate(row, quotation)
	total_stems = flt(row.get("custom_total_stems") or 0)
	box_id = int(math.ceil(total_stems / effective)) if (effective and total_stems) else 0
	return {
		"name": child_docname,
		"pack_rate": effective or "",
		"box_id": box_id,
	}


@frappe.whitelist()
def update_cart_delivery_point(delivery_point):
	quotation = _get_cart_quotation()
	if not quotation.meta.has_field("custom_delivery_point"):
		frappe.throw(
			_("Delivery Point is not set up yet. Open the Webshop Setup page to add it: {0}").format(
				'<a href="/webshop-setup">/webshop-setup</a>'
			)
		)

	dp_doctype = _delivery_point_doctype()
	if delivery_point and not (dp_doctype and frappe.db.exists(dp_doctype, delivery_point)):
		frappe.throw(_("Delivery Point {0} does not exist.").format(delivery_point))

	quotation.custom_delivery_point = delivery_point or None
	quotation.flags.ignore_permissions = True
	quotation.save()
	return {"name": quotation.name, "delivery_point": delivery_point or ""}


def _consignee_doctype():
	"""Resolve the Consignee master doctype for this site.

	Prefer the singular `Consignee` doctype; fall back to the legacy plural
	`Consignees` only when `Consignee` isn't installed. Returns None when neither
	exists (sites without the roses consignee setup)."""
	for dt in ("Consignee", "Consignees"):
		if frappe.db.exists("DocType", dt):
			return dt
	return None


@frappe.whitelist()
def update_cart_consignee(consignee):
	"""Cart-level Consignee. Stored on the cart's custom_consignee field — we keep
	that field as-is so the existing pack-list / dispatch fetch_from chains keep
	working; the cart just writes the chosen Consignee master name into it."""
	quotation = _get_cart_quotation()
	if not quotation.meta.has_field("custom_consignee"):
		frappe.throw(_("Consignee is not set up on this cart."))

	consignee_dt = _consignee_doctype()
	if consignee and consignee_dt and not frappe.db.exists(consignee_dt, consignee):
		frappe.throw(_("Consignee {0} does not exist.").format(consignee))

	quotation.custom_consignee = consignee or None
	quotation.flags.ignore_permissions = True
	quotation.save()
	return {"name": quotation.name, "consignee": consignee or ""}


@frappe.whitelist()
def search_consignees(txt=None, limit=20):
	"""Storefront Link-search for the cart's Consignee field. Webshop customers
	don't usually have read access to the Consignee master, so bypass permissions
	and return name + label (mirrors search_delivery_points)."""
	if not _get_cart_quotation():
		return []

	consignee_dt = _consignee_doctype()
	if not consignee_dt:
		return []

	# Only filter on `disable` when that column exists (the singular `Consignee`
	# doctype on kaitet has no such field).
	has_disable = bool(
		frappe.db.sql(
			f"SHOW COLUMNS FROM `tab{consignee_dt}` LIKE 'disable'"
		)
	)
	conditions = "WHERE IFNULL(disable, 0) = 0" if has_disable else "WHERE 1 = 1"
	args = {"txt": f"%{txt or ''}%", "limit": int(limit) if limit else 20}
	if txt:
		conditions += " AND name LIKE %(txt)s"

	rows = frappe.db.sql(
		f"""
		SELECT name FROM `tab{consignee_dt}`
		{conditions}
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		args,
		as_dict=True,
	)
	return [{"value": r.name, "label": r.name, "description": ""} for r in rows]


@frappe.whitelist()
def search_delivery_points(txt=None, limit=20):
	"""Storefront Link-search for the cart's Delivery Point field.

	Customers logging in via the webshop don't usually have any role with read
	access to Delivery Point, so the standard Link autocomplete returns nothing.
	This whitelisted helper ignores permissions and returns name + label."""
	if not _get_cart_quotation():
		return []

	dp_doctype = _delivery_point_doctype()
	if not dp_doctype:
		return []

	conditions = ""
	args = {"txt": f"%{txt or ''}%", "limit": int(limit) if limit else 20}
	if txt:
		conditions = "WHERE name LIKE %(txt)s"

	# Table name is `tab` + doctype name — singular or plural per site.
	rows = frappe.db.sql(
		f"""
		SELECT name FROM `tab{dp_doctype}`
		{conditions}
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		args,
		as_dict=True,
	)
	return [{"value": r.name, "label": r.name, "description": ""} for r in rows]


@frappe.whitelist()
def search_delivery_points_link(doctype, txt=None, searchfield=None, start=0, page_length=10, filters=None, as_dict=False, reference_doctype=None, ignore_user_permissions=False, link_fieldname=None):
	"""Link field search wrapper for Delivery Point, compatible with frappe.desk.search.search_link."""
	return search_delivery_points(txt=txt, limit=page_length)


@frappe.whitelist()
def update_cart_box_type(box_type):
	"""Cart-level Box Type. Saves on Quotation.custom_box_type and overwrites
	every Quotation Item's custom_box_type so pricing / min_order_qty derive
	from the single cart-level choice."""
	quotation = _get_cart_quotation()
	if not quotation.meta.has_field("custom_box_type"):
		frappe.throw(
			_("Box Type is not set up yet. Open the Webshop Setup page to add it: {0}").format(
				'<a href="/webshop-setup">/webshop-setup</a>'
			)
		)

	if box_type and not frappe.db.exists("Box Type", box_type):
		frappe.throw(_("Box Type {0} does not exist.").format(box_type))

	value = box_type or None
	quotation.custom_box_type = value

	child_dt = "Sales Order Item" if quotation.doctype == "Sales Order" else "Quotation Item"
	propagate = frappe.db.has_column(child_dt, "custom_box_type")
	if propagate:
		for item in quotation.get("items", []):
			item.custom_box_type = value

	# Selecting a box type fixes the pack rate: stamp each line's per-line
	# pack-rate field (custom_packrate / custom_pack_rate) with the Box Type's
	# rate so the cart's per-line Pack rate dropdown reflects it automatically.
	# Clearing the box type falls the lines back to the global default.
	pack_field = _line_pack_rate_field(child_dt)
	if pack_field:
		box_rate = _box_pack_rate(value) if value else 0
		effective = box_rate or _global_pack_rate()
		pack_value = _pack_rate_value_for_field(child_dt, pack_field, effective)
		for item in quotation.get("items", []):
			item.set(pack_field, pack_value)

	# Selecting a box type fixes the pack rate (stems/box), so re-pack the cart
	# lines into boxes of that capacity and re-stamp custom_box_id — same packing
	# logic as the /order-stock create_order_stock_order script. The helper reads
	# the cart's custom_box_type (just set above) and packs by its pack rate,
	# falling back to the 1..N placeholder when the box carries no pack rate.
	_assign_sequential_box_ids(quotation)
	_sync_ordered_stems(quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()
	_apply_length_price_db(quotation)
	set_cart_count(quotation)

	# Box type drives pricing on per-row flows (pack rate / min_order_qty), so
	# return the re-rendered cart fragments and let the client swap them in
	# place — no full page reload.
	quotation = _get_cart_quotation()
	context = get_cart_quotation(quotation)
	return {
		"name": quotation.name,
		"box_type": box_type or "",
		"items": frappe.render_template("templates/includes/cart/cart_items.html", context),
		"total": frappe.render_template("templates/includes/cart/cart_items_total.html", context),
		"taxes_and_totals": frappe.render_template(
			"templates/includes/cart/cart_payment_summary.html", context
		),
		"cart_count": cint(quotation.get("total_qty")) if quotation else 0,
	}


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
		SELECT name, packrate FROM `tabBox Type`
		{conditions}
		ORDER BY name ASC
		LIMIT %(limit)s
		""",
		args,
		as_dict=True,
	)
	return [
		{"value": r.name, "label": r.name, "description": "", "packrate": r.packrate or ""}
		for r in rows
	]


@frappe.whitelist()
def search_box_types_link(doctype, txt=None, searchfield=None, start=0, page_length=10, filters=None, as_dict=False, reference_doctype=None, ignore_user_permissions=False, link_fieldname=None):
	"""Link field search wrapper for Box Type, compatible with frappe.desk.search.search_link."""
	return search_box_types(txt=txt, limit=page_length)


def _session_customer_name():
	"""Customer linked to the current user, read without permission checks
	(portal users can't get_doc Customer/Contact). Mirrors how get_party()
	resolves the party: Portal User first, then Contact's Dynamic Link.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return None

	# Portal User is how the cart links a web user to a Customer.
	customer = frappe.db.get_value(
		"Portal User", {"user": user, "parenttype": "Customer"}, "parent"
	)
	if customer:
		return customer

	contact = frappe.db.get_value("Contact", {"email_id": user}, "name") or frappe.db.get_value(
		"Contact", {"user": user}, "name"
	)
	if not contact:
		return None
	return frappe.db.get_value(
		"Dynamic Link",
		{"parent": contact, "parenttype": "Contact", "link_doctype": "Customer"},
		"link_name",
	)


def _session_display_currency(base_currency):
	"""Currency to show the current session. Logged-in customer's
	default_currency if set, else the base catalog currency.
	"""
	customer = _session_customer_name()
	if customer:
		currency = frappe.db.get_value("Customer", customer, "default_currency")
		if currency:
			return currency
	return base_currency


def _convert_rate(rate, from_currency, to_currency):
	"""Convert a rate between currencies via ERPNext selling exchange rates."""
	if not rate or not from_currency or not to_currency or from_currency == to_currency:
		return rate
	from erpnext.setup.utils import get_exchange_rate

	fx = flt(get_exchange_rate(from_currency, to_currency, args="for_selling"))
	return flt(rate) * fx if fx else rate


@frappe.whitelist()
def get_item_price_for_configure(item_code):
	"""Return per-stem price for a variant item, used in the configure dialog.

	Reads the rate from the populated base catalog, then converts to the
	customer's display currency via exchange rates so the storefront shows each
	customer their own currency — matching what the cart will charge.
	"""
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	price_list = _set_price_list(cart_settings, None)
	base_currency = frappe.db.get_value("Price List", price_list, "currency")

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

	if not price:
		return {}

	from_currency = price.get("currency") or base_currency
	to_currency = _session_display_currency(from_currency)
	price["price_list_rate"] = _convert_rate(
		price.get("price_list_rate"), from_currency, to_currency
	)
	price["currency"] = to_currency
	return price
