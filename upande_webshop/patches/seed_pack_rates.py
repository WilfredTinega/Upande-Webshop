# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""
Seed Box Types, Variety Pack Rates, and Item Group Pack Rates from
the data previously hardcoded in item_configure.js.

Idempotent: safe to run multiple times. Skips records that already exist.
"""

import frappe


# ============================================================================
# DATA (mirrors the original PACK_RATES object exactly)
# ============================================================================

BOX_TYPES = [
	# (box_type_name, box_group, description)
	("ZIM",                     "zim", "ZIM-style box"),
	("WAFEX",                   "zim", "WAFEX box (same capacity as ZIM)"),
	("TFH HUB",                 "zim", "TFH HUB box (same capacity as ZIM)"),
	("FDT",                     "zim", "FDT box (same capacity as ZIM)"),
	("JUMBO",                   "zim", "JUMBO box (same capacity as ZIM)"),
	("STANDARD 100x33x20",      "std", "Standard box 100cm x 33cm x 20cm"),
]

# Map JS variety key (lowercase) → Item template name
# Built from the live template list. JS aliases (e.g. 'everred' / 'ever red') collapse to one Item.
VARIETY_MAPPING = {
	"ever red":         "Ever-Red",
	"everred":          "Ever-Red",        # alias
	"proud":            "Proud",
	"athena":           "Athena",
	"revival":          "Revival",
	"sweet revival":    "Sweet-Revival",
	"confidential":     "Confidential",
	"madam cerise":     "Madam-Cerise",
	"paloma":           "Paloma",
	"gold finch":       "Gold-Finch",
	"goldfinch":        "Gold-Finch",      # alias
	"madam red":        "Madam-Red",
	"mayfair":          "May-Fair",
	"goodtimes":        "Good-Times",
	"everpink":         "Ever-Pink",
	"ever pink":        "Ever-Pink",       # alias
	"deep purple":      "Deep-Purple",
	"fireworks":        "Fireworks",
	"snowflakes":       "Snow-Flakes",
	"sweet sara":       "Sweet-Sara",
	"dinara":           "Dinara",
	"mirabel":          "Mirabel",
	"leila":            "Leila",
	"reflex":           "Reflex",
	"tralala":          "Tralala",
	"odilia":           "Odilia",
	"salinero":         "Salinero",
	"alicia":           "Alicia",
	# Skipped per user decision (Yvonne will add manually):
	#   eucalyptus parvifolia, eucalyptus silver dollar, eucalyptus baby blue
}

# Pack rates from original JS, keyed by JS variety key
PACK_RATES_DATA = {
	"ever red":      {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 220, 60: 180, 70: 140}},
	"everred":       {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 220, 60: 180, 70: 140}},
	"proud":         {"zim": {40: 500, 50: 300, 60: 300, 70: 250}, "std": {50: 200, 60: 160, 70: 140}},
	"athena":        {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 220, 60: 180, 70: 140}},
	"revival":       {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 200, 60: 180, 70: 140}},
	"sweet revival": {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 200, 60: 180, 70: 140}},
	"confidential":  {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 240, 60: 180, 70: 140}},
	"madam cerise":  {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 240, 60: 180, 70: 140}},
	"paloma":        {"zim": {40: 400, 50: 300, 60: 250, 70: 200}, "std": {50: 200, 60: 160, 70: 140}},
	"gold finch":    {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 200, 60: 160, 70: 140}},
	"goldfinch":     {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 200, 60: 160, 70: 140}},
	"madam red":     {"zim": {40: 500, 50: 350, 60: 300, 70: 250}, "std": {50: 220, 60: 180, 70: 140}},
	"mayfair":       {"std": {50: 240, 60: 180, 70: 140}},
	"goodtimes":     {"std": {50: 220, 60: 180, 70: 140}},
	"everpink":      {"std": {50: 220, 60: 180, 70: 140}},
	"ever pink":     {"std": {50: 220, 60: 180, 70: 140}},
	"deep purple":   {"std": {50: 220, 60: 180, 70: 140}},
	"fireworks":     {"std": {50: 200, 60: 180, 70: 120}},
	"snowflakes":    {"std": {50: 200, 60: 180, 70: 120}},
	"sweet sara":    {"std": {50: 200, 60: 180, 70: 120}},
	"dinara":        {"std": {50: 180, 60: 160, 70: 120}},
	"mirabel":       {"std": {50: 200, 60: 180, 70: 120}},
	"leila":         {"std": {50: 200, 60: 180, 70: 120}},
	"reflex":        {"std": {50: 200, 60: 180, 70: 120}},
	"tralala":       {"std": {50: 180, 60: 160, 70: 120}},
	"odilia":        {"std": {50: 200, 60: 180, 70: 120}},
	"salinero":      {"std": {50: 200, 60: 180, 70: 120}},
	"alicia":        {"std": {50: 200, 60: 180, 70: 120}},
}

# Item-group fallback rule (per user decision: spray roses → group fallback)
ITEM_GROUP_RATES = {
	# (item_group_name, rates_by_box_group_and_length)
	"Spray Roses": {"zim": {50: 300, 60: 220, 70: 180, 80: 150}},
}


# ============================================================================
# SEED LOGIC
# ============================================================================

# Pick a representative box_type_name per box_group (used when building child rows
# from the hardcoded data, which only has the group, not the specific box).
REPRESENTATIVE_BOX = {"zim": "ZIM", "std": "STANDARD 100x33x20"}


def execute():
	frappe.db.commit()  # checkpoint
	print("=" * 70)
	print("Seeding Pack Rate data from item_configure.js hardcoded values")
	print("=" * 70)

	created_boxes = seed_box_types()
	created_varieties, skipped_missing, skipped_existing = seed_variety_pack_rates()
	created_groups = seed_item_group_rates()

	print()
	print(f"  Box Types created/verified: {created_boxes}")
	print(f"  Variety Pack Rates created: {created_varieties}")
	print(f"  Variety Pack Rates skipped (already exist): {skipped_existing}")
	print(f"  Variety Pack Rates skipped (template missing): {skipped_missing}")
	print(f"  Item Group Pack Rates created: {created_groups}")
	print("=" * 70)
	frappe.db.commit()


def seed_box_types():
	count = 0
	for name, group, desc in BOX_TYPES:
		if frappe.db.exists("Box Type", name):
			print(f"  [exists]  Box Type: {name}")
		else:
			doc = frappe.get_doc({
				"doctype": "Box Type",
				"box_type_name": name,
				"box_group": group,
				"is_active": 1,
				"description": desc,
			})
			doc.insert(ignore_permissions=True)
			print(f"  [created] Box Type: {name} (group={group})")
		count += 1
	return count


def seed_variety_pack_rates():
	created = 0
	skipped_missing = []
	skipped_existing = 0

	# Track which Items we've already seeded to handle JS aliases
	# (e.g. 'ever red' and 'everred' both → Ever-Red, but we only insert once)
	seeded_items = set()

	for js_key, item_template in VARIETY_MAPPING.items():
		if item_template in seeded_items:
			continue

		# Verify the Item template exists
		if not frappe.db.exists("Item", item_template):
			skipped_missing.append((js_key, item_template))
			print(f"  [SKIP]    Item template missing: '{js_key}' → {item_template}")
			continue

		# Skip if already created
		if frappe.db.exists("Variety Pack Rate", item_template):
			skipped_existing += 1
			seeded_items.add(item_template)
			print(f"  [exists]  Variety Pack Rate: {item_template}")
			continue

		rates = PACK_RATES_DATA.get(js_key, {})
		if not rates:
			print(f"  [SKIP]    No rate data for '{js_key}'")
			continue

		# Build the child rows
		pack_rate_rows = []
		for box_group, length_map in rates.items():
			box_type_name = REPRESENTATIVE_BOX.get(box_group)
			if not box_type_name:
				continue
			for length_cm, stems in length_map.items():
				pack_rate_rows.append({
					"box_type": box_type_name,
					"length_cm": length_cm,
					"stems_per_box": stems,
				})

		if not pack_rate_rows:
			print(f"  [SKIP]    No usable rows for '{js_key}'")
			continue

		doc = frappe.get_doc({
			"doctype": "Variety Pack Rate",
			"variety": item_template,
			"is_active": 1,
			"pack_rates": pack_rate_rows,
			"notes": f"Seeded from item_configure.js (key: '{js_key}')",
		})
		doc.insert(ignore_permissions=True)
		seeded_items.add(item_template)
		created += 1
		print(f"  [created] Variety Pack Rate: {item_template} ({len(pack_rate_rows)} rows)")

	return created, skipped_missing, skipped_existing


def seed_item_group_rates():
	count = 0
	for group_name, rates in ITEM_GROUP_RATES.items():
		# Resolve the actual item_group name (case-insensitive)
		actual = frappe.db.sql(
			"SELECT name FROM `tabItem Group` WHERE LOWER(name) = LOWER(%s) LIMIT 1",
			(group_name,),
		)
		if not actual:
			print(f"  [SKIP]    Item Group not found: {group_name}")
			continue
		actual_name = actual[0][0]

		if frappe.db.exists("Item Group Pack Rate", actual_name):
			print(f"  [exists]  Item Group Pack Rate: {actual_name}")
			continue

		pack_rate_rows = []
		for box_group, length_map in rates.items():
			box_type_name = REPRESENTATIVE_BOX.get(box_group)
			if not box_type_name:
				continue
			for length_cm, stems in length_map.items():
				pack_rate_rows.append({
					"box_type": box_type_name,
					"length_cm": length_cm,
					"stems_per_box": stems,
				})

		doc = frappe.get_doc({
			"doctype": "Item Group Pack Rate",
			"item_group": actual_name,
			"is_active": 1,
			"priority": 10,
			"pack_rates": pack_rate_rows,
			"notes": "Fallback rule seeded from item_configure.js ('spray roses' key)",
		})
		doc.insert(ignore_permissions=True)
		count += 1
		print(f"  [created] Item Group Pack Rate: {actual_name} ({len(pack_rate_rows)} rows)")

	return count
