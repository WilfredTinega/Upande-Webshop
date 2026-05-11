import frappe
from frappe.model.document import Document
from frappe.utils import flt

from upande_webshop.upande_webshop.doctype.floriday_items.floriday_items import (
	_normalize_stem_length,
	_stem_length_rates_from_item_prices,
	_stem_length_rates_from_variants,
)


# Match item groups whose name contains "rose" or "roses" as a whole word
# (e.g. "Roses", "Standard Roses", "Spray Roses", "Premium Rose Hybrids").
_ROSE_ITEM_GROUP_REGEXP = r"(^|[^[:alnum:]])(rose|roses)([^[:alnum:]]|$)"


def _alert(message, indicator="orange"):
	frappe.msgprint(message, alert=True, indicator=indicator)


USD_PRICE_LIST = "USD Price List"


def _resolve_price_list():
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
	price_list = frappe.db.get_single_value("Webshop Settings", "price_list")
	if price_list:
		return price_list
	return frappe.db.get_value("Floriday Settings", None, "price_list")


class WebshopItemPrices(Document):
	@frappe.whitelist()
	def fetch_stem_length_prices(self):
		if not self.item_code:
			_alert("Item Code is required to fetch prices.", "red")
			return 0

		price_list = _resolve_price_list()

		has_variants = frappe.db.get_value("Item", self.item_code, "has_variants")
		if has_variants:
			latest_rate = _stem_length_rates_from_variants(self.item_code, price_list)
		else:
			latest_rate = _stem_length_rates_from_item_prices(self.item_code, price_list)

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


@frappe.whitelist()
def sync_prices(run_async=True):
	"""Trigger a sync. By default enqueues a background job and returns immediately;
	pass run_async=False to run inline (used by the scheduler hook)."""
	# normalize string "0"/"false" from the form payload
	if isinstance(run_async, str):
		run_async = run_async.lower() not in ("0", "false", "no", "")

	if not run_async:
		return _sync_webshop_item_prices(publish_progress=False)

	user = frappe.session.user
	frappe.enqueue(
		"upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices._sync_webshop_item_prices",
		queue="long",
		timeout=3600,
		job_name="Webshop Item Prices Sync",
		publish_progress=True,
		progress_user=user,
		enqueue_after_commit=True,
	)
	return {"enqueued": True}


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


def _sync_webshop_item_prices(publish_progress=False, progress_user=None):
	user = progress_user or (frappe.session.user if publish_progress else None)

	_publish(user, 0, "Finding rose items...")
	items = frappe.db.sql(
		"""
		SELECT i.name AS item_code, i.item_name, i.item_group
		FROM tabItem i
		WHERE i.disabled = 0
		  AND (i.variant_of IS NULL OR i.variant_of = '')
		  AND i.item_group REGEXP %s
		""",
		(_ROSE_ITEM_GROUP_REGEXP,),
		as_dict=True,
	)

	total = len(items)
	created = 0
	updated = 0
	skipped = 0
	_publish(user, 1, f"Found {total} items. Starting sync...")

	for idx, item in enumerate(items, start=1):
		try:
			doc, was_created = _find_or_create_webshop_item_prices(item)
			if was_created:
				created += 1
			doc.fetch_stem_length_prices()
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
	}


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
