# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""
Pack rate lookup API.

Pack rate now lives on the Box Type doctype itself (child table 'pack_rates'),
keyed by length_cm. This means the rate is uniform across items for a given
box type and length, and you maintain it in one place per box.

Lookup:
  Box Type -> pack_rates child table -> row where length_cm matches -> stems_per_box

The item_code / variety_name args are accepted for backwards compatibility with
existing callers but are no longer consulted.
"""

import re

import frappe


CACHE_KEY = "pack_rate_cache"


def _get_box_pack_rate(box_name, length_cm):
	"""Look up stems_per_box for a given box and length from the Box Type child table."""
	if not (box_name and length_cm):
		return None

	rows = frappe.db.sql(
		"""
		SELECT detail.stems_per_box
		FROM `tabBox Type Pack Rate` detail
		INNER JOIN `tabBox Type` parent ON detail.parent = parent.name
		WHERE detail.parent = %(box_name)s
		  AND detail.parenttype = 'Box Type'
		  AND detail.length_cm = %(length_cm)s
		  AND parent.is_active = 1
		LIMIT 1
		""",
		{"box_name": box_name, "length_cm": int(length_cm)},
		as_dict=True,
	)
	return rows[0].stems_per_box if rows else None


@frappe.whitelist(allow_guest=True)
def get_pack_rate(item_code=None, variety_name=None, box_name=None, length_cm=None):
	"""Look up the stems-per-box pack rate from the Box Type's pack_rates child table.

	Args:
		item_code: Accepted but unused (legacy).
		variety_name: Accepted but unused (legacy).
		box_name: Box Type name from the toggle.
		length_cm: Length in cm.

	Returns:
		dict with keys: pack_rate (int or None), source (str), debug (dict)
	"""
	if not (box_name and length_cm):
		return {"pack_rate": None, "source": None, "debug": {"reason": "missing box or length"}}

	try:
		length_cm = int(length_cm)
	except (TypeError, ValueError):
		return {"pack_rate": None, "source": None, "debug": {"reason": "invalid length"}}

	cache_key = f"pack_rate:{box_name}:{length_cm}"
	cached = frappe.cache().hget(CACHE_KEY, cache_key)
	if cached is not None:
		return cached

	rate = _get_box_pack_rate(box_name, length_cm)
	if rate:
		result = {"pack_rate": int(rate), "source": f"box:{box_name}"}
	else:
		result = {
			"pack_rate": None,
			"source": None,
			"debug": {"box_name": box_name, "length_cm": length_cm},
		}

	frappe.cache().hset(CACHE_KEY, cache_key, result)
	return result


@frappe.whitelist(allow_guest=True)
def get_box_types():
	"""Return all active box types for populating the box selector."""
	return frappe.get_all(
		"Box Type",
		filters={"is_active": 1},
		fields=["name", "box_type_name", "box_group", "description"],
		order_by="box_type_name asc",
	)


@frappe.whitelist(allow_guest=True)
def get_item_bunch_size(item_code):
	"""Return the stems-per-bunch for an item.

	Reads the item's sales_uom and resolves the bunch size in this order:
	1. UOM Conversion Detail row on the Item (uom -> conversion_factor).
	2. Digits inside parentheses in the UOM name itself (e.g. "Bunch(12)" -> 12).

	Falls back to 1 if neither source yields a value.
	"""
	if not item_code:
		return {"bunch_size": 1}

	sales_uom = frappe.db.get_value("Item", item_code, "sales_uom")
	if not sales_uom:
		return {"bunch_size": 1, "sales_uom": None}

	factor = frappe.db.get_value(
		"UOM Conversion Detail",
		{"parent": item_code, "uom": sales_uom},
		"conversion_factor",
	)
	bunch_size = None
	try:
		if factor:
			bunch_size = int(float(factor))
	except (TypeError, ValueError):
		bunch_size = None

	if not bunch_size or bunch_size <= 1:
		match = re.search(r"\((\d+)\)", sales_uom)
		if match:
			bunch_size = int(match.group(1))

	return {"bunch_size": max(bunch_size or 1, 1), "sales_uom": sales_uom}
