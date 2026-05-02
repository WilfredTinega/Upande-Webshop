# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import re

import frappe
import requests
from frappe.model.document import Document

ROSE_ITEM_GROUPS = ("Spray Roses", "Standard Roses")
ALLOWED_SITE = "kaitet.local"


_NAME_PREFIXES = (
	"rosa large flowered",
	"rosa spray",
	"rosa",
	"alstroemeria",
	"gypsophila",
	"lepidium",
	"leather fern",
)


def _strip_floriday_prefixes(text):
	"""Remove botanical/category prefixes from Floriday tradeItemName.nl."""
	t = (text or "").lower()
	for p in _NAME_PREFIXES:
		if t.startswith(p + " "):
			t = t[len(p) + 1 :]
			break
	# Strip trailing " - Length 70" pattern -> "70"
	t = re.sub(r"\s*-\s*length\s+", " ", t)
	return t


def _normalize_name(text):
	"""Lowercase, strip non-alphanumeric. Used for cultivar names only."""
	if not text:
		return ""
	return re.sub(r"[^a-z0-9]+", "", str(text).lower())


def _split_name_and_length(text):
	"""
	Split a Floriday name like 'Miss Bombastic 60' or 'Sofie 70cm'
	into (normalized_cultivar_name, length_int).
	Length pattern: trailing digits, optionally followed by 'cm'.
	"""
	stripped = _strip_floriday_prefixes(text)
	m = re.search(r"^(.*?)(\d+)\s*(?:cm)?\s*$", stripped)
	if not m:
		return None, None
	name = _normalize_name(m.group(1))
	length = int(m.group(2)) if m.group(2) else None
	return name, length


def _floriday_length_for(stem_length):
	"""
	Map an ERPNext stem length to Floriday's grading.
	Floriday rounds down to nearest 10: 52 -> 50, 62 -> 60, 72 -> 70, etc.
	"""
	m = re.search(r"\d+", str(stem_length or ""))
	if not m:
		return None
	return (int(m.group(0)) // 10) * 10


def _alert(message, indicator="orange"):
	frappe.msgprint(message, alert=True, indicator=indicator)


class FloridayItems(Document):
	@frappe.whitelist()
	def fetch_stem_length_prices(self):
		if not self.item_code:
			_alert("Item Code is required to fetch prices.", "red")
			return 0

		filters = {"item_code": self.item_code}
		price_list = frappe.db.get_value("Floriday Settings", None, "price_list")
		if price_list:
			filters["price_list"] = price_list

		item_prices = frappe.get_all(
			"Item Price",
			filters=filters,
			fields=["custom_length", "price_list_rate"],
		)

		latest_rate = {}
		for row in item_prices:
			if not row.custom_length:
				continue
			latest_rate[row.custom_length] = row.price_list_rate

		existing = {row.stem_length: row for row in self.table_ppvq if row.stem_length}

		for stem_length, rate in latest_rate.items():
			if stem_length in existing:
				existing[stem_length].rate = rate
			else:
				self.append(
					"table_ppvq",
					{"stem_length": stem_length, "rate": rate},
				)

		self.set(
			"table_ppvq",
			[row for row in self.table_ppvq if row.stem_length in latest_rate],
		)

		self.save()
		return len(self.table_ppvq)

	def apply_trade_item_ids(self, article_lookup):
		matched = 0
		for row in self.table_ppvq:
			if row.refresh_trade_item_id(article_lookup, item_name=self.item_name):
				matched += 1
		return matched

	@frappe.whitelist()
	def fetch_trade_item_ids(self):
		if not self.item_name:
			_alert("Item Name is required to match Floriday trade items.", "red")
			return {"total_rows": 0, "matched": 0}
		if not self.table_ppvq:
			_alert("Add stem length rows first (run Fetch Stem Length Prices).", "orange")
			return {"total_rows": 0, "matched": 0}

		try:
			article_lookup = _fetch_floriday_trade_items()
		except Exception as e:
			_alert(f"Could not fetch trade items: {e}", "red")
			return {"total_rows": len(self.table_ppvq), "matched": 0}

		matched = self.apply_trade_item_ids(article_lookup)
		self.save()
		return {"total_rows": len(self.table_ppvq), "matched": matched}


def _get_floriday_settings():
	settings_list = frappe.get_all("Floriday Settings", limit_page_length=1)
	if not settings_list:
		frappe.throw("Floriday Settings not configured")
	settings = frappe.get_doc("Floriday Settings", settings_list[0].name)
	if not (settings.base_url and settings.access_token and settings.api_key):
		frappe.throw("Floriday Settings missing base_url, access_token, or api_key.")
	return settings


def _fetch_floriday_trade_items():
	settings = _get_floriday_settings()
	try:
		response = requests.get(
			f"{settings.base_url}trade-items/",
			headers={
				"Authorization": f"Bearer {settings.access_token}",
				"X-Api-Key": settings.api_key,
				"Accept": "application/json",
			},
			timeout=60,
		)
	except Exception as e:
		frappe.throw(f"Floriday request failed: {e}")

	if response.status_code != 200:
		frappe.throw(
			f"Floriday returned {response.status_code}: {response.text[:500]}"
		)

	data = response.json()
	trade_items = data.get("results", data) if isinstance(data, dict) else data
	if not isinstance(trade_items, list):
		frappe.throw("Unexpected Floriday response shape.")

	article_lookup = {}
	for ti in trade_items:
		nl = (ti.get("tradeItemName") or {}).get("nl") or ""
		trade_item_id = ti.get("tradeItemId")
		if not (nl and trade_item_id):
			continue
		name, length = _split_name_and_length(nl)
		if not name or length is None:
			continue
		key = (name, length)
		if key not in article_lookup:
			article_lookup[key] = trade_item_id
	return article_lookup


def _find_or_create_floriday_item(item):
	existing = frappe.db.exists("Floriday Items", {"item_code": item.item_code})
	if not existing and frappe.db.exists("Floriday Items", item.item_name):
		existing = item.item_name
	if existing:
		doc = frappe.get_doc("Floriday Items", existing)
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
		"doctype": "Floriday Items",
		"item_code": item.item_code,
		"item_name": item.item_name,
		"item_group": item.item_group,
	})
	doc.insert()
	return doc, True


def get_item_mapping():
	rows = frappe.db.sql(
		"""
		select fi.item_code, slp.trade_item_id, slp.stem_length
		from `tabFloriday Items` fi
		join `tabStem Length Price` slp on slp.parent = fi.name
		where ifnull(slp.trade_item_id, '') != ''
		""",
		as_dict=True,
	)
	mapping = {}
	for r in rows:
		if r.item_code and r.item_code not in mapping:
			mapping[r.item_code] = r.trade_item_id
	return mapping


def get_item_code_from_trade_item_id(trade_item_id):
	if not trade_item_id:
		return None
	row = frappe.db.sql(
		"""
		select fi.item_code
		from `tabFloriday Items` fi
		join `tabStem Length Price` slp on slp.parent = fi.name
		where slp.trade_item_id = %s
		limit 1
		""",
		(trade_item_id,),
		as_dict=True,
	)
	return row[0].item_code if row else None


@frappe.whitelist()
def sync_system_items(force=False):
	if frappe.local.site != ALLOWED_SITE:
		return {"skipped": True, "reason": f"sync_system_items only runs on {ALLOWED_SITE}"}

	if not force and not frappe.db.get_single_value("Floriday Settings", "fi_enabled"):
		return {"skipped": True, "reason": "Floriday Items sync is disabled (fi_enabled = 0)"}

	items = frappe.get_all(
		"Item",
		filters={"item_group": ["in", ROSE_ITEM_GROUPS], "disabled": 0},
		fields=["item_code", "item_name", "item_group"],
	)

	created = 0
	updated_prices = 0
	skipped = 0
	for item in items:
		try:
			doc, was_created = _find_or_create_floriday_item(item)
			if was_created:
				created += 1
			doc.fetch_stem_length_prices()
			updated_prices += 1
		except Exception as e:
			skipped += 1
			frappe.log_error(
				f"sync_system_items failed for {item.item_code} / {item.item_name}: {e}",
				"Floriday Items Sync",
			)

	return {
		"items_processed": len(items),
		"floriday_docs_created": created,
		"price_refreshes": updated_prices,
		"skipped": skipped,
	}


@frappe.whitelist()
def update_trade_item_ids(force=False):
	if frappe.local.site != ALLOWED_SITE:
		return {"skipped": True, "reason": f"update_trade_item_ids only runs on {ALLOWED_SITE}"}

	if not force and not frappe.db.get_single_value("Floriday Settings", "fi_enabled"):
		return {"skipped": True, "reason": "Floriday Items sync is disabled (fi_enabled = 0)"}

	try:
		article_lookup = _fetch_floriday_trade_items()
	except Exception as e:
		frappe.log_error(f"Could not fetch trade items: {e}", "Floriday Items Sync")
		return {
			"trade_items_fetched": 0,
			"rows_matched": 0,
			"error": str(e),
		}

	floriday_docs = frappe.get_all("Floriday Items", pluck="name")
	total_matched = 0
	total_rows = 0
	unmatched = []  # {item_code, item_name, stem_length}
	docs_processed = 0
	docs_with_no_table = 0
	for name in floriday_docs:
		try:
			doc = frappe.get_doc("Floriday Items", name)
			if not doc.table_ppvq:
				docs_with_no_table += 1
				continue
			matched = doc.apply_trade_item_ids(article_lookup)
			for row in doc.table_ppvq:
				total_rows += 1
				if not row.trade_item_id:
					unmatched.append({
						"item_code": doc.item_code,
						"item_name": doc.item_name,
						"stem_length": row.stem_length,
					})
			if matched:
				doc.save()
				total_matched += matched
			docs_processed += 1
		except Exception as e:
			frappe.log_error(
				f"update_trade_item_ids failed for {name}: {e}",
				"Floriday Items Sync",
			)

	if unmatched and total_matched < total_rows:
		sample_lines = [
			f"{u['item_code']} ({u['item_name']}) / {u['stem_length']}"
			for u in unmatched[:10]
		]
		sample_keys = list(article_lookup.keys())[:10]
		frappe.log_error(
			"Unmatched rows (sample):\n"
			+ "\n".join(sample_lines)
			+ "\n\nFloriday lookup keys (sample):\n"
			+ "\n".join(repr(k) for k in sample_keys),
			"Floriday Items Sync — unmatched debug",
		)

	return {
		"trade_items_fetched": len(article_lookup),
		"docs_processed": docs_processed,
		"docs_with_no_table": docs_with_no_table,
		"rows_matched": total_matched,
		"total_rows": total_rows,
		"unmatched": unmatched,
	}


@frappe.whitelist()
def sync_floriday_items(force=False):
	system = sync_system_items(force=force)
	trade = update_trade_item_ids(force=force)
	return {**system, **trade}
