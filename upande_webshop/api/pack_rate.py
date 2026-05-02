# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""
Pack rate lookup API.

Lookup chain (first hit wins):
  1. Variety Pack Rate where variety = item template (resolved from variant_of)
  2. Variety Pack Rate where variety = item itself
  3. Item Group Pack Rate where item_group = item's group (fallback, e.g. "Spray Roses")

Box matching: the box_name string is matched against Box Type records to resolve
its box_group ('zim' or 'std'), then any row with matching box_group + length_cm wins.
This means ZIM, WAFEX, TFH HUB, FDT, JUMBO all resolve to the same pack rate
because they share box_group='zim'.
"""

import frappe
from frappe import _


CACHE_KEY = "pack_rate_cache"
CACHE_TTL = 3600  # 1 hour; cleared automatically on doctype save


def _get_box_group(box_name):
	"""Resolve a box name (free-text from the dropdown) to its box_group.

	Tries exact match first, then falls back to substring matching on box_type_name
	for backwards compatibility with names like 'ZIM Box' or 'Standard 100x33x20'.
	"""
	if not box_name:
		return None

	# Exact match on Box Type name
	box_group = frappe.db.get_value("Box Type", box_name, "box_group")
	if box_group:
		return box_group

	# Fallback: substring match (handles legacy free-text box names)
	bn = (box_name or "").lower()
	all_boxes = frappe.get_all(
		"Box Type",
		filters={"is_active": 1},
		fields=["box_type_name", "box_group"],
	)
	for b in all_boxes:
		if b.box_type_name.lower() in bn or bn in b.box_type_name.lower():
			return b.box_group

	# Last-resort hardcoded fallback (matches original JS logic exactly)
	if "standard" in bn:
		return "std"
	if any(k in bn for k in ("zim", "wafex", "tfh", "fdt", "jumbo")):
		return "zim"
	return None


def _get_item_template(item_code):
	"""Return the template item code if item_code is a variant, else item_code itself."""
	if not item_code:
		return None
	variant_of = frappe.db.get_value("Item", item_code, "variant_of")
	return variant_of or item_code


def _lookup_in_doctype(doctype, parent_name, box_group, length_cm):
	"""Find a matching pack rate row in either Variety or Item Group Pack Rate."""
	if not parent_name:
		return None
	rows = frappe.db.sql(
		"""
		SELECT detail.stems_per_box
		FROM `tabVariety Pack Rate Detail` detail
		INNER JOIN `tab{parent}` parent ON detail.parent = parent.name
		WHERE detail.parent = %(parent_name)s
		  AND detail.parenttype = %(parent_type)s
		  AND detail.box_group = %(box_group)s
		  AND detail.length_cm = %(length_cm)s
		  AND parent.is_active = 1
		LIMIT 1
		""".format(parent=doctype),
		{
			"parent_name": parent_name,
			"parent_type": doctype,
			"box_group": box_group,
			"length_cm": int(length_cm),
		},
		as_dict=True,
	)
	return rows[0].stems_per_box if rows else None


@frappe.whitelist(allow_guest=True)
def get_pack_rate(item_code=None, variety_name=None, box_name=None, length_cm=None):
	"""Look up the stems-per-box pack rate for a given item/box/length.

	Args:
		item_code: Preferred — the actual item code (variant or template).
		variety_name: Fallback — used only if item_code is not provided
		              (legacy callers passing item_name like "Ever Red").
		box_name: The box type name from the dropdown.
		length_cm: Length in cm (40, 50, 60, 70, 80).

	Returns:
		dict with keys: pack_rate (int or None), source (str), debug (dict)
	"""
	if not (box_name and length_cm):
		return {"pack_rate": None, "source": None, "debug": {"reason": "missing box or length"}}

	try:
		length_cm = int(length_cm)
	except (TypeError, ValueError):
		return {"pack_rate": None, "source": None, "debug": {"reason": "invalid length"}}

	box_group = _get_box_group(box_name)
	if not box_group:
		return {
			"pack_rate": None,
			"source": None,
			"debug": {"reason": "unknown box", "box_name": box_name},
		}

	# Cache key includes all inputs
	cache_key = f"pack_rate:{item_code or ''}:{variety_name or ''}:{box_group}:{length_cm}"
	cached = frappe.cache().hget(CACHE_KEY, cache_key)
	if cached is not None:
		return cached

	result = {"pack_rate": None, "source": None, "debug": {"box_group": box_group}}

	# Resolve the item to look up
	resolved_item = None
	if item_code:
		resolved_item = item_code
	elif variety_name:
		# Legacy lookup: find an item template whose item_name matches (case-insensitive)
		resolved_item = frappe.db.sql(
			"""
			SELECT name FROM `tabItem`
			WHERE LOWER(item_name) = LOWER(%s)
			ORDER BY has_variants DESC, creation ASC
			LIMIT 1
			""",
			(variety_name.strip(),),
		)
		resolved_item = resolved_item[0][0] if resolved_item else None

	if resolved_item:
		# 1. Try template
		template = _get_item_template(resolved_item)
		rate = _lookup_in_doctype("Variety Pack Rate", template, box_group, length_cm)
		if rate:
			result.update({"pack_rate": rate, "source": f"variety:{template}"})
			frappe.cache().hset(CACHE_KEY, cache_key, result)
			return result

		# 2. Try item itself (in case it's not a variant)
		if resolved_item != template:
			rate = _lookup_in_doctype("Variety Pack Rate", resolved_item, box_group, length_cm)
			if rate:
				result.update({"pack_rate": rate, "source": f"variety:{resolved_item}"})
				frappe.cache().hset(CACHE_KEY, cache_key, result)
				return result

		# 3. Item Group fallback
		item_group = frappe.db.get_value("Item", resolved_item, "item_group")
		if item_group:
			rate = _lookup_in_doctype("Item Group Pack Rate", item_group, box_group, length_cm)
			if rate:
				result.update({"pack_rate": rate, "source": f"group:{item_group}"})
				frappe.cache().hset(CACHE_KEY, cache_key, result)
				return result

	# Nothing found
	result["debug"]["resolved_item"] = resolved_item
	frappe.cache().hset(CACHE_KEY, cache_key, result)
	return result


@frappe.whitelist(allow_guest=True)
def get_box_types():
	"""Return all active box types for populating dropdowns."""
	return frappe.get_all(
		"Box Type",
		filters={"is_active": 1},
		fields=["name", "box_type_name", "box_group", "description"],
		order_by="box_type_name asc",
	)
