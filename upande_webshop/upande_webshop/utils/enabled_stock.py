"""Admin-published ("enabled") webshop stock.

The Stock tab on Webshop Settings (and Floriday / Biflorica Setting) lets an
admin tick item (+length, where lengths exist) rows and publish a quantity to the
storefront via `webshop_item_prices.set_webshop_enabled_stock`. That flips the
`enabled` flag and writes `stock_qty` on the matching `Stem Length Price` child of
the item's `Webshop Item Prices` doc — NO stock is moved.

This module is the storefront's read side. The feature is a GATE: once ANY row on
the site is enabled, the storefront stops showing live Bin/shelf stock for plain
items and instead shows ONLY the admin-published quantities. A plain item with no
enabled rows then reads as 0 / out of stock — it is not published until an admin
ticks it. (Before the first row is ever enabled the gate is off, so existing sites
behave exactly as before.)

Lengths are keyed on the canonical "<n>cm" form so "52CM"/"52 cm"/"52cm" resolve
to one row. Rows with no length (warehouse mode, where the item carries no stem
length) publish a single whole-item quantity; they contribute to the item total
but never to the per-length picker.
"""

import re

import frappe
from frappe.utils import flt


def _canon_length(value):
	"""Canonical "<n>cm" form, or "" when there's no number."""
	if value is None:
		return ""
	m = re.search(r"\d+", str(value))
	return f"{int(m.group(0))}cm" if m else ""


def enabled_feature_active():
	"""True when the storefront should show ONLY admin-published stock for plain items.

	The gate turns on in either of two ways:
	  1. Webshop Settings → "Show Only Enabled Stock?" is ticked. This forces the
	     gate on even with zero enabled rows, so a freshly-set-up site shows nothing
	     until items are published — items with no enabled row read as out of stock.
	  2. (Auto-detect, for sites that never set the toggle) at least one Stem Length
	     Price row is enabled site-wide. This preserves the original behaviour where
	     the feature only kicks in once the first row is published.

	When active, plain items show only published quantities (non-enabled → 0).
	Cached per request — read once per listing build and once per product page.
	"""
	flag = "_webshop_enabled_stock_active"
	cached = frappe.local.flags.get(flag)
	if cached is not None:
		return cached
	active = _publish_only_toggle_on() or bool(
		frappe.db.exists(
			"Stem Length Price", {"parenttype": "Webshop Item Prices", "enabled": 1}
		)
	)
	frappe.local.flags[flag] = active
	return active


# The "Show Only Enabled Stock?" gate toggle lives on each channel's settings
# Single (Webshop / Floriday / Biflorica). Any one switched on turns the gate on
# for the shared storefront read — the enabled flag itself is channel-agnostic.
_PUBLISH_ONLY_SINGLES = (
	"Webshop Settings",
	"Floriday Settings",
	"Biflorica Setting",
)


def _publish_only_toggle_on():
	"""True when any channel's 'Show Only Enabled Stock?' toggle is on.

	Guarded per-Single: a doctype that lacks the field (older install) or doesn't
	exist on the site is simply skipped, never raises."""
	for doctype in _PUBLISH_ONLY_SINGLES:
		try:
			if not frappe.get_meta(doctype).has_field("publish_enabled_stock_only"):
				continue
			if frappe.db.get_single_value(doctype, "publish_enabled_stock_only"):
				return True
		except Exception:
			continue
	return False


def enabled_qty_by_length(item_code):
	"""Published {canonical_length: qty} for an item's enabled lengths.

	Empty dict when the item has no Webshop Item Prices doc or no enabled rows
	(the common case), so callers can cheaply treat "empty" as "not published".
	"""
	if not item_code:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT slp.stem_length, slp.stock_qty
		FROM `tabStem Length Price` slp
		JOIN `tabWebshop Item Prices` wip ON wip.name = slp.parent
		WHERE slp.parenttype = 'Webshop Item Prices'
		  AND slp.enabled = 1
		  AND wip.item_code = %s
		""",
		(item_code,),
		as_dict=True,
	)
	out = {}
	for r in rows:
		length = _canon_length(r.stem_length)
		if not length:
			continue
		out[length] = out.get(length, 0.0) + flt(r.stock_qty)
	return out


def enabled_total_qty(item_code):
	"""Total published qty for an item across ALL its enabled rows (0.0 if none).

	Includes whole-item (empty-length) rows, so this is the right figure for the
	item-level total / in-stock badge in BOTH shelf mode (per-length rows) and
	warehouse mode (a single empty-length row). Use enabled_qty_by_length() when
	you specifically need the per-length breakdown for the length picker."""
	if not item_code:
		return 0.0
	total = frappe.db.sql(
		"""
		SELECT SUM(slp.stock_qty)
		FROM `tabStem Length Price` slp
		JOIN `tabWebshop Item Prices` wip ON wip.name = slp.parent
		WHERE slp.parenttype = 'Webshop Item Prices'
		  AND slp.enabled = 1
		  AND wip.item_code = %s
		""",
		(item_code,),
	)
	return flt(total[0][0]) if total and total[0] else 0.0


def has_enabled_lengths(item_code):
	"""True when the item has at least one enabled length published."""
	if not item_code:
		return False
	return bool(
		frappe.db.exists(
			"Stem Length Price",
			{
				"parenttype": "Webshop Item Prices",
				"enabled": 1,
				"parent": frappe.db.get_value(
					"Webshop Item Prices", {"item_code": item_code}, "name"
				)
				or "__none__",
			},
		)
	)


def enabled_total_qty_for_items(item_codes):
	"""Batched {item_code: total_published_qty} for a list of items.

	One query for the whole list; items with no enabled rows are simply absent
	from the result (caller treats missing as "not published").
	"""
	item_codes = [c for c in (item_codes or []) if c]
	if not item_codes:
		return {}
	placeholders = ", ".join(["%s"] * len(item_codes))
	rows = frappe.db.sql(
		f"""
		SELECT wip.item_code, SUM(slp.stock_qty) AS qty
		FROM `tabStem Length Price` slp
		JOIN `tabWebshop Item Prices` wip ON wip.name = slp.parent
		WHERE slp.parenttype = 'Webshop Item Prices'
		  AND slp.enabled = 1
		  AND wip.item_code IN ({placeholders})
		GROUP BY wip.item_code
		""",
		tuple(item_codes),
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}
