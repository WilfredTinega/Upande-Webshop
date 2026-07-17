import re

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from upande_webshop.upande_webshop.utils.stem_length import (
	_normalize_stem_length,
	_stem_length_rates_from_item_prices,
	_stem_length_rates_from_variants,
)


# Match item groups whose name contains "rose"/"roses" as a whole word
# (e.g. "Roses", "Standard Roses", "Spray Roses", "Premium Rose Hybrids"),
# OR the David Austin group (English roses sold under that brand).
_ROSE_ITEM_GROUP_REGEXP = r"(^|[^[:alnum:]])(rose|roses|david austin)([^[:alnum:]]|$)"
_ROSE_ITEM_GROUP_PYTHON_RE = re.compile(
	r"(^|[^a-z0-9])(rose|roses|david austin)([^a-z0-9]|$)",
	re.IGNORECASE,
)


def _is_rose_item_group(item_group):
	if not item_group:
		return False
	return bool(_ROSE_ITEM_GROUP_PYTHON_RE.search(item_group))


def ensure_per_length_item_prices(item_code, price_list=None, default_rate=0):
	"""Create one Item Price row per master Stem Length for a non-variant rose item.

	Skips silently when:
	  - the `custom_length` Custom Field doesn't exist on Item Price yet
	  - the item is a variant or template (not a plain non-variant)
	  - the item is not in a rose / David Austin group
	  - rows for this (item_code, price_list) already exist

	Returns the number of new rows created.
	"""
	if not item_code:
		return 0
	if not frappe.db.has_column("Item Price", "custom_length"):
		return 0

	item = frappe.db.get_value(
		"Item",
		item_code,
		["item_group", "has_variants", "variant_of"],
		as_dict=True,
	)
	if not item:
		return 0
	if item.has_variants or item.variant_of:
		return 0
	if not _is_rose_item_group(item.item_group):
		return 0

	target_price_list = price_list or _resolve_price_list()
	if not target_price_list or not frappe.db.exists("Price List", target_price_list):
		return 0

	master_lengths = frappe.get_all(
		"Item Attribute Value",
		filters={"parent": "Stem Length"},
		fields=["attribute_value"],
		order_by="idx",
	)
	if not master_lengths:
		return 0

	# Existing rows on this price list, keyed by normalized length
	existing_rows = frappe.get_all(
		"Item Price",
		filters={"item_code": item_code, "price_list": target_price_list},
		fields=["name", "custom_length", "price_list_rate"],
	)
	existing_by_norm = {}
	flat_rows = []
	for row in existing_rows:
		norm = _normalize_stem_length(row.custom_length) if row.custom_length else None
		if norm:
			existing_by_norm[norm] = row
		else:
			flat_rows.append(row)

	flat_rate = flat_rows[0].price_list_rate if flat_rows else None
	seed_rate = flt(default_rate) if default_rate else flt(flat_rate or 0)

	created = 0
	for ml in master_lengths:
		canonical = ml.attribute_value
		norm = _normalize_stem_length(canonical)
		if not norm or norm in existing_by_norm:
			continue
		try:
			frappe.get_doc({
				"doctype": "Item Price",
				"item_code": item_code,
				"price_list": target_price_list,
				"price_list_rate": seed_rate,
				"custom_length": canonical,
			}).insert(ignore_permissions=True)
			created += 1
		except Exception as e:
			frappe.log_error(
				f"ensure_per_length_item_prices failed for {item_code} {canonical}: {e}",
				"Webshop Per-Length Item Price",
			)

	# Once per-length rows exist, retire any leftover flat Item Price for this
	# (item, price_list). Sales Order/Quotation pricing should resolve to a
	# specific length, not to an ambiguous lengthless row.
	if created and flat_rows:
		for row in flat_rows:
			try:
				frappe.delete_doc("Item Price", row.name, ignore_permissions=True)
			except Exception as e:
				frappe.log_error(
					f"could not delete flat Item Price {row.name} for {item_code}: {e}",
					"Webshop Per-Length Item Price",
				)

	return created


def _alert(message, indicator="orange"):
	frappe.msgprint(message, alert=True, indicator=indicator)


USD_PRICE_LIST = "USD Price List"


def _resolve_price_list():
	# Webshop Settings.price_list was removed — currency now follows the
	# customer's own price list, with USD as the guest/sync fallback. Guard the
	# read so a leftover value (pre-migration) is still honored if present.
	configured = None
	if frappe.get_meta("Webshop Settings").has_field("price_list"):
		configured = frappe.db.get_single_value("Webshop Settings", "price_list")
	if configured and frappe.db.exists("Price List", configured):
		return configured
	if frappe.db.exists("Price List", USD_PRICE_LIST):
		return USD_PRICE_LIST
	usd_lists = frappe.get_all(
		"Price List",
		filters={"currency": "USD", "enabled": 1, "selling": 1},
		fields=["name"],
		order_by="creation asc",
		limit=1,
	)
	if usd_lists:
		return usd_lists[0].name
	return configured


class WebshopItemPrices(Document):
	@frappe.whitelist()
	def refresh_prices_and_stock(self):
		"""Refresh both rate and stock_qty for this item in one shot."""
		if not self.item_code:
			_alert("Item Code is required to refresh.", "red")
			return None
		return _sync_item_prices_and_stock(self.item_code)

	@frappe.whitelist()
	def fetch_stem_length_prices(self, price_list=None):
		if not self.item_code:
			_alert("Item Code is required to fetch prices.", "red")
			return 0

		configured = _resolve_price_list()

		has_variants = frappe.db.get_value("Item", self.item_code, "has_variants")
		if has_variants:
			# Variant pricing resolves per variant code; the dialog's price-list
			# choice applies to non-variant items only, so use the configured list.
			latest_rate = _stem_length_rates_from_variants(self.item_code, configured)
		else:
			# Non-variant: read from the selected price list (if any) and fall back
			# per-length to the configured list. No selection → configured only.
			primary = price_list or configured
			latest_rate = _stem_length_rates_from_item_prices(
				self.item_code, primary, fallback_price_list=configured
			)

		existing = {row.stem_length: row for row in self.stem_length_prices if row.stem_length}

		for stem_length, rate in latest_rate.items():
			if stem_length in existing:
				existing[stem_length].rate = rate
			else:
				self.append(
					"stem_length_prices",
					{"stem_length": stem_length, "rate": rate},
				)

		self.set(
			"stem_length_prices",
			[row for row in self.stem_length_prices if row.stem_length in latest_rate],
		)

		self.save()
		return len(self.stem_length_prices)


def _find_or_create_webshop_item_prices(item):
	existing = frappe.db.exists("Webshop Item Prices", {"item_code": item.item_code})
	if not existing and frappe.db.exists("Webshop Item Prices", item.item_name):
		existing = item.item_name
	if existing:
		doc = frappe.get_doc("Webshop Item Prices", existing)
		updated = False
		if not doc.item_code:
			doc.item_code = item.item_code
			updated = True
		if not doc.item_group:
			doc.item_group = item.item_group
			updated = True
		if updated:
			doc.save()
		return doc, False

	doc = frappe.get_doc({
		"doctype": "Webshop Item Prices",
		"item_code": item.item_code,
		"item_name": item.item_name,
		"item_group": item.item_group,
	})
	doc.insert()
	return doc, True


SYNC_PROGRESS_EVENT = "webshop_prices_sync_progress"


SYNC_SOURCES = ("item_price", "stock_ledger_entry", "both")


def _normalize_source(source):
	if not source:
		return "both"
	source = str(source).strip().lower()
	if source not in SYNC_SOURCES:
		frappe.throw(f"Unknown sync source: {source}. Expected one of {SYNC_SOURCES}.")
	return source


@frappe.whitelist()
def sync_prices(run_async=True, source="both", price_list=None):
	"""Trigger a sync. By default enqueues a background job and returns immediately;
	pass run_async=False to run inline (used by the scheduler hook).

	`source` controls which doctype the data is pulled from:
	  - "item_price"         → refresh stem-length rates from Item Price only
	  - "stock_ledger_entry" → refresh stem-length stock_qty from SLE only
	  - "both" (default)     → refresh both in one pass

	`price_list` (optional) is the primary Price List to read NON-VARIANT
	per-length rates from (e.g. a Customer Price List chosen in the dialog); any
	length it lacks falls back to the configured Item price list. Blank → use the
	configured list only (original behaviour). Ignored for variant items.
	"""
	if isinstance(run_async, str):
		run_async = run_async.lower() not in ("0", "false", "no", "")

	source = _normalize_source(source)
	price_list = _validate_price_list(price_list)

	if not run_async:
		return _sync_webshop_item_prices(
			publish_progress=False, source=source, price_list=price_list
		)

	user = frappe.session.user
	frappe.enqueue(
		"upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices._sync_webshop_item_prices",
		queue="long",
		timeout=3600,
		job_name=f"Webshop Item Prices Sync ({source})",
		publish_progress=True,
		progress_user=user,
		source=source,
		price_list=price_list,
		enqueue_after_commit=True,
	)
	return {"enqueued": True, "source": source, "price_list": price_list}


def _validate_price_list(price_list):
	"""Return a usable Price List name or None. Rejects unknown values so a bad
	dialog input doesn't silently sync from nothing."""
	if not price_list:
		return None
	price_list = str(price_list).strip()
	if not price_list:
		return None
	if not frappe.db.exists("Price List", price_list):
		frappe.throw(frappe._("Price List {0} does not exist.").format(price_list))
	return price_list


# Back-compat alias for the original name.
@frappe.whitelist()
def sync_webshop_item_prices():
	return _sync_webshop_item_prices(publish_progress=False)


def _publish(user, progress, message):
	if not user:
		return
	try:
		frappe.publish_realtime(
			event=SYNC_PROGRESS_EVENT,
			message={"progress": progress, "message": message},
			user=user,
		)
	except Exception:
		pass


def _website_items():
	"""Items to refresh: every published Website Item.

	For variant templates we still need the *template's* item_code, since WIP
	records live on the template (variants share rates through it). Website
	Item.item_code already points at the right Item.
	"""
	return frappe.db.sql(
		"""
		SELECT i.name AS item_code, i.item_name, i.item_group
		FROM `tabWebsite Item` wi
		JOIN `tabItem` i ON i.name = wi.item_code
		WHERE wi.published = 1
		  AND i.disabled = 0
		ORDER BY i.name
		""",
		as_dict=True,
	)


def _write_stock_qty(wip_doc, qty_by_length):
	"""Apply per-length stock_qty onto an in-memory WIP doc. No save."""
	existing_rows = {
		row.stem_length: row
		for row in (wip_doc.stem_length_prices or [])
		if row.stem_length
	}
	for length, qty in qty_by_length.items():
		if length in existing_rows:
			row = existing_rows[length]
			if flt(row.stock_qty) != flt(qty):
				row.stock_qty = qty
		else:
			wip_doc.append(
				"stem_length_prices",
				{"stem_length": length, "rate": 0, "stock_qty": qty},
			)
	for length, row in existing_rows.items():
		if length not in qty_by_length and flt(row.stock_qty) != 0:
			row.stock_qty = 0


def _sync_item_prices_and_stock(item_code, source="both", price_list=None):
	"""Refresh rate and/or stock_qty for a single item.

	`source`:
	  - "item_price"         → only run fetch_stem_length_prices (rates from Item Price)
	  - "stock_ledger_entry" → only sum SLE into Stem Length Price.stock_qty
	  - "both"               → both, in one save

	`price_list`: primary list for non-variant rate reads (see fetch_stem_length_prices).
	"""
	if not item_code:
		return None

	source = _normalize_source(source)

	item = frappe.db.get_value(
		"Item", item_code, ["name", "item_name", "item_group"], as_dict=True
	)
	if not item:
		return None
	item.item_code = item.name

	doc, was_created = _find_or_create_webshop_item_prices(item)

	if source in ("item_price", "both"):
		doc.fetch_stem_length_prices(price_list=price_list)
		doc.reload()

	if source in ("stock_ledger_entry", "both"):
		qty_by_length = _sle_qty_by_normalized_length(item_code)
		_write_stock_qty(doc, qty_by_length)
		doc.save(ignore_permissions=True)

	return {"item_code": item_code, "created": was_created, "lengths": len(doc.stem_length_prices)}


_SOURCE_LABELS = {
	"item_price": "Item Price",
	"stock_ledger_entry": "Stock Ledger Entry",
	"both": "Item Price + Stock Ledger Entry",
}


def _sync_webshop_item_prices(publish_progress=False, progress_user=None, source="both", price_list=None):
	user = progress_user or (frappe.session.user if publish_progress else None)
	source = _normalize_source(source)
	source_label = _SOURCE_LABELS[source]
	if price_list:
		source_label = f"{source_label} · {price_list}"

	_publish(user, 0, f"Finding website items (source: {source_label})...")
	items = _website_items()

	total = len(items)
	created = 0
	updated = 0
	skipped = 0
	_publish(user, 1, f"Found {total} items. Starting sync from {source_label}...")

	for idx, item in enumerate(items, start=1):
		try:
			result = _sync_item_prices_and_stock(item.item_code, source=source, price_list=price_list)
			if result and result.get("created"):
				created += 1
			updated += 1
		except Exception as e:
			skipped += 1
			frappe.log_error(
				f"sync_webshop_item_prices failed for {item.item_code}: {e}",
				"Webshop Item Prices Sync",
			)

		if total and (idx % 5 == 0 or idx == total):
			pct = int((idx / total) * 100)
			_publish(user, pct, f"Synced {idx} of {total} ({item.item_name})")

	_publish(user, 100, f"Done. Processed {total}, created {created}, skipped {skipped}.")

	return {
		"items_processed": len(items),
		"docs_created": created,
		"price_refreshes": updated,
		"skipped": skipped,
		"source": source,
		"price_list": price_list,
	}


SLE_SYNC_LOCK_TTL = 120  # seconds


def _enqueue_sle_sync(item_code):
	"""Enqueue a sync for one item, deduped by Redis lock.

	A burst of SLE rows from a single Stock Entry / Material Receipt collapses
	to one background job per item. The lock TTL is short — long enough to
	cover the enqueue → run gap, short enough that a later genuine change
	doesn't get suppressed.
	"""
	lock_key = f"webshop_wip_sync:{item_code}"
	cache = frappe.cache()
	if cache.get_value(lock_key):
		return
	cache.set_value(lock_key, 1, expires_in_sec=SLE_SYNC_LOCK_TTL)

	frappe.enqueue(
		"upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices._run_sle_sync",
		queue="short",
		job_name=f"Webshop WIP sync {item_code}",
		item_code=item_code,
		enqueue_after_commit=True,
	)


def _run_sle_sync(item_code):
	try:
		_sync_item_prices_and_stock(item_code)
		frappe.db.commit()
	finally:
		frappe.cache().delete_value(f"webshop_wip_sync:{item_code}")


def on_stock_ledger_entry_change(doc, method=None):
	"""Doc event: enqueue a WIP refresh for the item if the SLE is in a Webshop
	warehouse. Fires on submit/cancel. Ignores SLEs outside the configured
	warehouse set so unrelated stock movements don't churn the queue.
	"""
	if not doc.item_code or not doc.warehouse:
		return
	if doc.warehouse not in set(_resolve_webshop_warehouses()):
		return
	if not frappe.db.exists("Website Item", {"item_code": doc.item_code, "published": 1}):
		return
	_enqueue_sle_sync(doc.item_code)


@frappe.whitelist()
def backfill_all_active_items():
	"""Create a Webshop Item Prices record for every active, non-template Item.

	Leaves the Stem Length Price child table empty — prices are entered manually
	on each record. Skips items that already have a record (matched by item_code).
	"""
	items = frappe.db.sql(
		"""
		SELECT name AS item_code, item_name, item_group
		FROM tabItem
		WHERE disabled = 0
		  AND has_variants = 0
		  AND (variant_of IS NULL OR variant_of = '')
		""",
		as_dict=True,
	)

	created = 0
	skipped = 0
	for item in items:
		if frappe.db.exists("Webshop Item Prices", {"item_code": item.item_code}):
			skipped += 1
			continue
		try:
			frappe.get_doc({
				"doctype": "Webshop Item Prices",
				"item_code": item.item_code,
				"item_name": item.item_name,
				"item_group": item.item_group,
			}).insert(ignore_permissions=True)
			created += 1
		except Exception as e:
			skipped += 1
			frappe.log_error(
				f"backfill_all_active_items failed for {item.item_code}: {e}",
				"Webshop Item Prices Backfill",
			)

	frappe.db.commit()
	return {"total": len(items), "created": created, "skipped": skipped}


@frappe.whitelist(allow_guest=True)
def get_item_length_price(item_code, length, currency=None, price_list=None):
	"""Look up the per-stem rate for an item at a given stem length.

	Reads exclusively from the Webshop Item Prices doctype. Returns None if
	no row exists for the given item/length pair.
	"""
	if not (item_code and length):
		return None

	normalized_length = _normalize_stem_length(length) or str(length).strip()

	parent_name = frappe.db.get_value(
		"Webshop Item Prices",
		{"item_code": item_code},
		"name",
	)
	if not parent_name:
		template = frappe.db.get_value("Item", item_code, "variant_of")
		if template:
			parent_name = frappe.db.get_value(
				"Webshop Item Prices",
				{"item_code": template},
				"name",
			)
	if not parent_name:
		return None

	rate = frappe.db.get_value(
		"Stem Length Price",
		{
			"parent": parent_name,
			"parenttype": "Webshop Item Prices",
			"stem_length": normalized_length,
		},
		"rate",
	)
	if rate in (None, ""):
		return None

	try:
		return {"price_list_rate": flt(rate)}
	except (TypeError, ValueError):
		return None


WAREHOUSE_CACHE_KEY = "webshop_wip_warehouses"


def _resolve_webshop_warehouses():
	"""Return exactly the warehouses listed in Webshop Settings → Warehouses.

	No group expansion: whatever the user typed in is the literal set. If they
	want children of a group counted, they must list them explicitly. This
	prevents picking up 'graded sold' / 'receiving' children when the user
	intended only 'available for sale'.

	Cached in Redis. The cache is busted by Webshop Settings.on_change when
	the warehouses table is edited.
	"""
	cached = frappe.cache().get_value(WAREHOUSE_CACHE_KEY)
	if cached is not None:
		return cached

	from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
		get_configured_warehouses,
	)

	resolved = sorted({wh for wh in get_configured_warehouses() if wh})
	frappe.cache().set_value(WAREHOUSE_CACHE_KEY, resolved)
	return resolved


def bust_warehouse_cache():
	frappe.cache().delete_value(WAREHOUSE_CACHE_KEY)


def _sle_qty_by_normalized_length(item_code):
	"""On-hand qty per normalized stem length, equal to Bin.actual_qty when all SLE rows are tagged.

	For each `(warehouse, custom_stem_length)` bucket we sum `actual_qty` — same
	identity ERPNext uses to derive Bin.actual_qty per (item, warehouse). Summed
	across the configured Webshop warehouses, the per-length totals on the
	product page reconcile to Bin exactly, *provided every SLE row carries a
	custom_stem_length*. Untagged rows are reported by `_log_missing_tag_delta`
	(called from the bulk sync), not silently bucketed.

	`custom_stem_length` is normally a Link to Stem Length (`name`); on some
	sites it stores the label directly. We join through Stem Length when we can
	and fall back to the raw value.

	Returns {} when no Webshop warehouses are configured.
	"""
	warehouses = _resolve_webshop_warehouses()
	if not warehouses:
		return {}

	placeholders = ",".join(["%s"] * len(warehouses))
	rows = frappe.db.sql(
		f"""
		SELECT sle.custom_stem_length AS raw_value,
		       sl.length              AS length_label,
		       SUM(sle.actual_qty)    AS qty
		FROM `tabStock Ledger Entry` sle
		LEFT JOIN `tabStem Length` sl ON sl.name = sle.custom_stem_length
		WHERE sle.item_code = %s
		  AND sle.is_cancelled = 0
		  AND sle.custom_stem_length IS NOT NULL
		  AND sle.custom_stem_length != ''
		  AND sle.warehouse IN ({placeholders})
		GROUP BY sle.custom_stem_length, sl.length
		""",
		(item_code, *warehouses),
		as_dict=True,
	)
	qty_by_length = {}
	for row in rows:
		norm = _normalize_stem_length(row.length_label) or _normalize_stem_length(row.raw_value)
		if not norm:
			continue
		qty = flt(row.qty)
		qty_by_length[norm] = qty_by_length.get(norm, 0.0) + qty
	return qty_by_length


def _bin_total_for_item(item_code):
	"""Bin.actual_qty summed across the configured Webshop warehouses."""
	warehouses = _resolve_webshop_warehouses()
	if not warehouses:
		return 0.0
	placeholders = ",".join(["%s"] * len(warehouses))
	total = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(actual_qty), 0)
		FROM `tabBin`
		WHERE item_code = %s
		  AND warehouse IN ({placeholders})
		""",
		(item_code, *warehouses),
	)
	return flt(total[0][0]) if total else 0.0


def _log_missing_tag_delta(item_code, qty_by_length):
	"""If per-length sum != Bin total for the configured warehouses, log a delta.

	The gap is exactly the qty sitting in SLE rows that have no custom_stem_length
	for this item — ops needs to tag them so storefront stock reconciles.
	"""
	bin_total = _bin_total_for_item(item_code)
	per_length_total = sum(flt(q) for q in qty_by_length.values())
	delta = flt(bin_total) - flt(per_length_total)
	if abs(delta) < 0.5:
		return
	frappe.log_error(
		title="Webshop Stock Reconciliation: missing stem length",
		message=(
			f"Item {item_code}: Bin total = {bin_total}, "
			f"per-length total = {per_length_total}, missing = {delta}. "
			"Tag the affected Stock Ledger Entry rows with a custom_stem_length "
			"so storefront stock matches Bin."
		),
	)


REPOST_PROGRESS_EVENT = "webshop_prices_sync_progress"  # reuse the same channel/listener


def _earliest_sle_date(item_code, warehouses):
	"""Earliest posting_date in SLE for this item across the given warehouses.

	Used to bound the Repost Item Valuation to the actual data window. Falls
	back to 1 year ago if no SLE exists (the repost will be a no-op anyway).
	"""
	if not warehouses:
		return None
	placeholders = ",".join(["%s"] * len(warehouses))
	row = frappe.db.sql(
		f"""
		SELECT MIN(posting_date)
		FROM `tabStock Ledger Entry`
		WHERE item_code = %s
		  AND warehouse IN ({placeholders})
		  AND is_cancelled = 0
		""",
		(item_code, *warehouses),
	)
	if row and row[0] and row[0][0]:
		return row[0][0]
	from frappe.utils import add_years, nowdate

	return add_years(nowdate(), -1)


def _existing_repost_pairs(warehouses):
	"""Set of (item_code, warehouse) already queued or running.

	Submitted Repost Item Valuation rows with status Queued/In Progress are
	picked up by the hourly cron; re-queueing the same pair would create
	duplicate work for ERPNext.
	"""
	if not warehouses:
		return set()
	placeholders = ",".join(["%s"] * len(warehouses))
	rows = frappe.db.sql(
		f"""
		SELECT item_code, warehouse
		FROM `tabRepost Item Valuation`
		WHERE docstatus = 1
		  AND status IN ('Queued', 'In Progress')
		  AND based_on = 'Item and Warehouse'
		  AND warehouse IN ({placeholders})
		""",
		tuple(warehouses),
		as_dict=True,
	)
	return {(r.item_code, r.warehouse) for r in rows}


def _publish_repost(user, progress, message):
	if not user:
		return
	try:
		frappe.publish_realtime(
			event=REPOST_PROGRESS_EVENT,
			message={"progress": progress, "message": message},
			user=user,
		)
	except Exception:
		pass


def _enqueue_repost_for_website_items(progress_user=None):
	"""Submit one Repost Item Valuation per (Website Item, configured warehouse).

	Skips pairs that already have a Queued/In Progress repost. The hourly
	`erpnext.stock.doctype.repost_item_valuation.repost_item_valuation.repost_entries`
	cron picks them up; you don't need to do anything else.
	"""
	user = progress_user
	warehouses = _resolve_webshop_warehouses()
	if not warehouses:
		return {"queued": 0, "skipped": 0, "reason": "No Webshop warehouses configured."}

	items = _website_items()
	already = _existing_repost_pairs(warehouses)

	total = len(items) * len(warehouses)
	queued = 0
	skipped = 0
	failed = 0
	processed = 0
	_publish_repost(user, 1, f"Queueing repost for {len(items)} items × {len(warehouses)} warehouses...")

	for item in items:
		earliest = _earliest_sle_date(item.item_code, warehouses)
		for wh in warehouses:
			processed += 1
			if (item.item_code, wh) in already:
				skipped += 1
			else:
				try:
					doc = frappe.get_doc({
						"doctype": "Repost Item Valuation",
						"based_on": "Item and Warehouse",
						"item_code": item.item_code,
						"warehouse": wh,
						"posting_date": earliest,
						"posting_time": "00:00:00",
						"allow_negative_stock": 1,
					})
					doc.flags.ignore_permissions = True
					doc.insert(ignore_permissions=True)
					doc.submit()
					queued += 1
				except Exception as e:
					failed += 1
					frappe.log_error(
						title="Webshop Repost Bin: enqueue failed",
						message=f"item={item.item_code} warehouse={wh}: {e}",
					)

			if total and (processed % 10 == 0 or processed == total):
				pct = max(1, int((processed / total) * 100))
				_publish_repost(user, pct, f"Queued {queued} | skipped {skipped} | failed {failed} ({processed}/{total})")

	_publish_repost(user, 100, f"Done. Queued {queued}, skipped {skipped}, failed {failed}.")
	frappe.db.commit()
	return {
		"queued": queued,
		"skipped": skipped,
		"failed": failed,
		"items": len(items),
		"warehouses": len(warehouses),
	}


@frappe.whitelist()
def enqueue_repost_for_website_items(run_async=True):
	"""Trigger Bin repost for every published Website Item × configured Webshop warehouse.

	Default: enqueues a long-queue background job and publishes progress on
	`webshop_prices_sync_progress`. Pass run_async=False for inline runs.
	"""
	if isinstance(run_async, str):
		run_async = run_async.lower() not in ("0", "false", "no", "")

	if not run_async:
		return _enqueue_repost_for_website_items(progress_user=None)

	user = frappe.session.user
	frappe.enqueue(
		"upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices._enqueue_repost_for_website_items",
		queue="long",
		timeout=3600,
		job_name="Webshop Repost Bin (all Website Items)",
		progress_user=user,
		enqueue_after_commit=True,
	)
	return {"enqueued": True}


def _non_variant_rose_items():
	"""All enabled non-variant rose / David Austin item_codes.

	Mirrors the item set the retired ``backfill_per_length_item_prices`` patch
	walked: plain items (not templates, not variants) whose item group matches
	the rose regexp. Per-length Item Prices only apply to this set; variants
	encode their length in the item code instead.
	"""
	return frappe.db.sql(
		"""
		SELECT name
		FROM tabItem
		WHERE disabled = 0
		  AND has_variants = 0
		  AND (variant_of IS NULL OR variant_of = '')
		  AND item_group REGEXP %s
		""",
		(_ROSE_ITEM_GROUP_REGEXP,),
		pluck="name",
	)


def _backfill_per_length_prices(progress_user=None):
	"""Seed per-length Item Price rows for every non-variant rose item.

	On-demand replacement for the retired backfill patch: loops the rose item
	set and calls ``ensure_per_length_item_prices`` on each. Idempotent — items
	that already have per-length rows produce no new rows. Returns a summary.
	"""
	if not frappe.db.has_column("Item Price", "custom_length"):
		_publish_repost(progress_user, 100, "Skipped: Item Price.custom_length field is missing.")
		return {"items": 0, "created": 0, "reason": "custom_length field missing"}

	items = _non_variant_rose_items()
	total = len(items)
	if not total:
		_publish_repost(progress_user, 100, "No non-variant rose items found.")
		return {"items": 0, "created": 0}

	_publish_repost(progress_user, 1, f"Backfilling per-length prices for {total} item(s)...")

	created_total = 0
	processed = 0
	for item_code in items:
		processed += 1
		try:
			created_total += ensure_per_length_item_prices(item_code)
		except Exception as e:
			frappe.log_error(
				title="Webshop Per-Length Backfill",
				message=f"backfill failed for {item_code}: {e}",
			)
		if processed % 10 == 0 or processed == total:
			pct = max(1, int((processed / total) * 100))
			_publish_repost(progress_user, pct, f"Created {created_total} row(s) ({processed}/{total})")

	_publish_repost(progress_user, 100, f"Done. Created {created_total} per-length price row(s) across {total} item(s).")
	frappe.db.commit()
	return {"items": total, "created": created_total}


@frappe.whitelist()
def enqueue_backfill_per_length_prices(run_async=True):
	"""First-run seeding of per-length Item Prices for non-variant rose items.

	Triggered manually from Webshop Settings — NOT on install/migrate. The
	ongoing per-item maintenance still runs via the Item ``validate`` hook;
	this only fills in items that pre-date that hook. Publishes progress on the
	shared ``webshop_prices_sync_progress`` channel.
	"""
	if isinstance(run_async, str):
		run_async = run_async.lower() not in ("0", "false", "no", "")

	if not run_async:
		return _backfill_per_length_prices(progress_user=None)

	user = frappe.session.user
	frappe.enqueue(
		"upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices._backfill_per_length_prices",
		queue="long",
		timeout=3600,
		job_name="Webshop Backfill Per-Length Prices",
		progress_user=user,
		enqueue_after_commit=True,
	)
	return {"enqueued": True}


def _items_with_stem_length_sle():
	"""All item_codes that have at least one SLE row tagged with a stem length."""
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT item_code
		FROM `tabStock Ledger Entry`
		WHERE is_cancelled = 0
		  AND custom_stem_length IS NOT NULL
		  AND custom_stem_length != ''
		""",
		as_dict=True,
	)
	return [r.item_code for r in rows if r.item_code]


def _refresh_stem_length_stock_for(item_code):
	"""Bootstrap WIP + Stem Length Price rows for an item and write per-length stock_qty.

	Returns {length: qty} for what was written, or an empty dict if the item
	has no stem-length-tagged SLE rows.
	"""
	qty_by_length = _sle_qty_by_normalized_length(item_code)
	if not qty_by_length:
		return {}

	item = frappe.db.get_value(
		"Item", item_code, ["name", "item_name", "item_group"], as_dict=True
	)
	if not item:
		return {}
	item.item_code = item.name

	wip_doc, _created = _find_or_create_webshop_item_prices(item)

	existing_rows = {
		row.stem_length: row
		for row in (wip_doc.stem_length_prices or [])
		if row.stem_length
	}

	written = {}
	for length, qty in qty_by_length.items():
		if length in existing_rows:
			row = existing_rows[length]
			if flt(row.stock_qty) != flt(qty):
				row.stock_qty = qty
		else:
			wip_doc.append(
				"stem_length_prices",
				{"stem_length": length, "rate": 0, "stock_qty": qty},
			)
		written[length] = flt(qty)

	# Zero out stock for lengths that previously had SLE but no longer do.
	for length, row in existing_rows.items():
		if length not in qty_by_length and flt(row.stock_qty) != 0:
			row.stock_qty = 0
			written[length] = 0.0

	wip_doc.save(ignore_permissions=True)
	return written


@frappe.whitelist()
def sync_stem_length_stock(item_code=None):
	"""Refresh `stock_qty` on Stem Length Price rows from Stock Ledger Entry.

	If WIP rows for an item don't exist yet, this bootstraps them (rate=0)
	so that the storefront can render per-length availability immediately.
	Existing rate values are preserved.

	Pass `item_code` to refresh one item; omit to walk every item that has
	stem-length-tagged SLE. Returns {item_code: {length: qty}}.
	"""
	if item_code:
		item_codes = [item_code]
	else:
		item_codes = _items_with_stem_length_sle()

	result = {}
	for ic in item_codes:
		written = _refresh_stem_length_stock_for(ic)
		if written:
			result[ic] = written

	frappe.db.commit()
	return result


# ── Webshop "enabled stock" publish (no stock movement) ──────────────────────
# The Stock tab on Webshop Settings / Floriday Settings / Biflorica Setting lets
# an admin tick item+length rows and publish a quantity to the storefront. Unlike
# the older shelf→online transfer, this moves NO stock: it only flips the
# `enabled` flag and writes `stock_qty` on the matching Stem Length Price child of
# the item's Webshop Item Prices doc. Enabled rows stay listed in the panel (with
# a checkmark) so the published qty can be edited or the row un-published later.
# The storefront reads `stock_qty` from enabled rows as the available quantity
# (see product_data_engine/query.get_enabled_qty_by_length and
# utils/product.get_web_item_qty_in_stock).


def _stem_length_price_row(wip_doc, stem_length):
	"""Find the Stem Length Price child for `stem_length`, creating it if absent.

	Match is on the canonical "<n>cm" form so "52CM"/"52 cm"/"52cm" all collapse
	to one row, mirroring how rates/stock are stored elsewhere."""
	canon = _normalize_stem_length(stem_length) or (stem_length or "").strip()
	for row in wip_doc.stem_length_prices or []:
		if _normalize_stem_length(row.stem_length) == canon or row.stem_length == canon:
			return row
	return wip_doc.append(
		"stem_length_prices",
		{"stem_length": canon, "rate": 0, "stock_qty": 0},
	)


@frappe.whitelist()
def set_webshop_enabled_stock(items, enabled=1, source_warehouse=None):
	"""Publish (or un-publish) per-length stock to the storefront. No stock move.

	`items`: JSON list of {item_code, stem_length, qty}. For each entry the item's
	Webshop Item Prices doc is found/created, the Stem Length Price row for that
	length is found/created, its `enabled` flag is set to `enabled`, and (when
	enabling) its `stock_qty` is set to `qty` — the quantity shown on the webshop.

	The published qty is CAPPED at the current available stock for that (item,
	length): you can never enable more than is physically available. By default the
	cap reads shelf + configured-warehouse stock. `source_warehouse` (the Customer
	Settings picker) ADDS that warehouse's Bin stock to the cap, so items that live
	only in a customer's warehouse can still be enabled. This is the server-side
	guard behind the panel's per-row max, so a stale page or a direct API call can't
	over-publish. Returns {updated, items, capped}.
	"""
	import json

	from upande_webshop.upande_webshop.utils.shelf_transfer import (
		_canon_length,
		available_qty_by_key,
	)

	if isinstance(items, str):
		items = json.loads(items or "[]")
	enabled = 1 if str(enabled) not in ("0", "false", "False", "", "no") else 0

	# Current availability, only needed when enabling (capping doesn't apply to a
	# disable). One pass over shelf + warehouse rows, plus the customer warehouse
	# when one is supplied (its items aren't in the default shelf/warehouse sets).
	avail = available_qty_by_key() if enabled else {}
	if enabled and source_warehouse:
		from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
			get_customer_warehouse_rows,
		)

		for r in get_customer_warehouse_rows(source_warehouse):
			key = (r.get("item_code"), _canon_length(r.get("stem_length")))
			avail[key] = avail.get(key, 0.0) + flt(r.get("shelf_qty"))

	# Group requested lengths per item so each WIP doc is saved once.
	by_item = {}
	for entry in items or []:
		item_code = (entry.get("item_code") or "").strip()
		stem_length = (entry.get("stem_length") or "").strip()
		if not item_code:
			continue
		by_item.setdefault(item_code, []).append(
			{"stem_length": stem_length, "qty": flt(entry.get("qty"))}
		)

	updated = 0
	capped = 0
	touched_items = []
	for item_code, lengths in by_item.items():
		item = frappe.db.get_value(
			"Item", item_code, ["name", "item_name", "item_group"], as_dict=True
		)
		if not item:
			continue
		item.item_code = item.name
		wip_doc, _created = _find_or_create_webshop_item_prices(item)

		for L in lengths:
			row = _stem_length_price_row(wip_doc, L["stem_length"])
			row.enabled = enabled
			if enabled:
				qty = flt(L["qty"])
				# Cap at available stock for this (item, length).
				available = flt(avail.get((item_code, _canon_length(L["stem_length"]))))
				if qty > available:
					qty = available
					capped += 1
				row.stock_qty = qty
			updated += 1

		wip_doc.save(ignore_permissions=True)
		touched_items.append(item_code)

	frappe.db.commit()
	return {"updated": updated, "items": touched_items, "capped": capped}


@frappe.whitelist()
def get_webshop_enabled_rows():
	"""Currently-enabled (item, length, published qty) rows for the Stock panel.

	Returns a list of {item_code, item_name, stem_length, stock_qty, bunch_size},
	one per enabled Stem Length Price child. Lets the picker keep showing published
	rows with a checkmark — and their correct bunch step — even after the physical
	shelf/warehouse stock is gone. bunch_size is parsed from the item's sales UOM
	(Bunch(10)→10), matching the live shelf/warehouse rows."""
	from upande_webshop.upande_webshop.doctype.box_type.box_type import (
		_stems_per_bunch_from_uom,
	)

	rows = frappe.db.sql(
		"""
		SELECT wip.item_code, wip.item_name, slp.stem_length,
		       slp.stock_qty, i.sales_uom, i.stock_uom
		FROM `tabStem Length Price` slp
		JOIN `tabWebshop Item Prices` wip ON wip.name = slp.parent
		LEFT JOIN `tabItem` i ON i.name = wip.item_code
		WHERE slp.parenttype = 'Webshop Item Prices'
		  AND slp.enabled = 1
		ORDER BY wip.item_name, slp.stem_length
		""",
		as_dict=True,
	)
	for r in rows:
		r["stock_qty"] = flt(r.get("stock_qty"))
		size = _stems_per_bunch_from_uom(r.get("sales_uom") or r.get("stock_uom"))
		r["bunch_size"] = size if size and size > 0 else 1
	return rows
