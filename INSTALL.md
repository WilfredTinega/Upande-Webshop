# Pack Rate DocType Migration — Installation Guide

This package replaces the hardcoded `PACK_RATES` object in `item_configure.js`
with three editable DocTypes, so Yvonne (or any sales/stock manager) can update
pack rates without a developer.

---

## What's included

```
upande_webshop/
├── doctype/
│   ├── box_type/                       (1) Master: ZIM, WAFEX, STANDARD, etc.
│   ├── variety_pack_rate/              (2) Per-variety rates (parent)
│   ├── variety_pack_rate_detail/       (3) Pack rate rows (child table)
│   └── item_group_pack_rate/           (4) Fallback rates per Item Group
├── api/
│   └── pack_rate.py                    Whitelisted lookup API
├── patches/
│   └── seed_pack_rates.py              Seeds all 32 varieties from old JS
└── public/js/
    └── item_configure.js               Drop-in replacement (API-driven)
```

---

## Installation steps

Run from your bench root: `~/my-v16-bench`

### 1. Copy files into the app

Each folder/file goes to:

```
apps/upande_webshop/upande_webshop/doctype/box_type/
apps/upande_webshop/upande_webshop/doctype/variety_pack_rate/
apps/upande_webshop/upande_webshop/doctype/variety_pack_rate_detail/
apps/upande_webshop/upande_webshop/doctype/item_group_pack_rate/
apps/upande_webshop/upande_webshop/api/pack_rate.py
apps/upande_webshop/upande_webshop/patches/seed_pack_rates.py
apps/upande_webshop/upande_webshop/public/js/item_configure.js  (REPLACES existing)
```

**Important:** Back up the existing `item_configure.js` first:
```bash
cp apps/upande_webshop/upande_webshop/public/js/item_configure.js \
   apps/upande_webshop/upande_webshop/public/js/item_configure.js.bak
```

### 2. Verify the module name

Open `apps/upande_webshop/upande_webshop/modules.txt` and check the module name.
The DocType JSONs use `"module": "Upande Webshop"` — if your module is named
differently, find-and-replace in all 4 doctype `.json` files.

```bash
grep -l '"module"' apps/upande_webshop/upande_webshop/doctype/*/*.json
```

### 3. Register the seed patch

Add this line to `apps/upande_webshop/upande_webshop/patches.txt`:

```
upande_webshop.patches.seed_pack_rates
```

If the file doesn't exist yet, create it with that one line.

### 4. Migrate

```bash
bench --site austin.localhost migrate
bench --site austin.localhost clear-cache
bench --site austin.localhost build --app upande_webshop
```

The migrate step will:
- Create the 4 new DocTypes
- Run `seed_pack_rates.py` once, populating all data from the old JS
- Print a summary of what was seeded vs. skipped

Expected output:
```
  Box Types created/verified: 6
  Variety Pack Rates created: 26
  Variety Pack Rates skipped (already exist): 0
  Variety Pack Rates skipped (template missing): 0
  Item Group Pack Rates created: 1
```

### 5. Restart and verify

```bash
bench restart
```

Then:
1. Go to a product page (e.g. Paloma) → click Select Variant → pick length + box → confirm pack rate appears (should say "200 stems/box" for Paloma + ZIM + 70cm).
2. Go to Desk → search "Variety Pack Rate" → confirm 26 records exist.
3. Edit one (e.g. change Paloma ZIM 70cm from 200 to 999), save, refresh the product page → confirm the new value shows.

---

## Where Yvonne edits rates

| Task | Location |
|------|----------|
| Add a new box type | Desk → **Box Type** → New |
| Change a variety's pack rate | Desk → **Variety Pack Rate** → open variety → edit table |
| Add a new variety's rates | Desk → **Variety Pack Rate** → New (pick Item template) |
| Set a fallback for an item group | Desk → **Item Group Pack Rate** → New |

**Lookup priority (first hit wins):**
1. Variety Pack Rate matching the item's template (e.g. `EVER-RED-50CM` → `Ever-Red`)
2. Variety Pack Rate matching the item directly
3. Item Group Pack Rate matching the item's group (e.g. Spray Roses fallback)

---

## What was NOT migrated (per your decision)

These 3 eucalyptus rates from the old JS were skipped because the live Item
templates have different names (`Baby Blue`, `Silver-Dollar`, `Pervifolia`).
Yvonne can add them manually via Desk → Variety Pack Rate → New. The values
from the old JS, for reference:

```
eucalyptus parvifolia    zim: 40→1000  50→800  60→600  70→400  80→200
eucalyptus silver dollar zim: 40→1000  50→800  60→600  70→400  80→200
eucalyptus baby blue     zim: 40→1000  50→800  60→600  70→400  80→200
```

Also note: `Wild-Fox` exists as a live template but had no pack rate in the
old JS, so it has no pack rate now either. Add via Desk when needed.

---

## Rollback

If anything breaks:

```bash
# 1. Restore old item_configure.js
cp apps/upande_webshop/upande_webshop/public/js/item_configure.js.bak \
   apps/upande_webshop/upande_webshop/public/js/item_configure.js

# 2. Remove the patch line from patches.txt

# 3. Drop the doctypes (in system console / bench console)
import frappe
for dt in ["Variety Pack Rate", "Variety Pack Rate Detail",
           "Item Group Pack Rate", "Box Type"]:
    if frappe.db.exists("DocType", dt):
        frappe.delete_doc("DocType", dt, force=True)
frappe.db.commit()

# 4. Rebuild
bench --site austin.localhost migrate
bench --site austin.localhost clear-cache
bench restart
```

---

## Quick API reference

```python
# Python
from upande_webshop.api.pack_rate import get_pack_rate

result = get_pack_rate(
    item_code="EVER-RED-50CM",  # or item_code=None and pass variety_name
    box_name="ZIM",
    length_cm=50,
)
# → {"pack_rate": 350, "source": "variety:Ever-Red", "debug": {...}}
```

```javascript
// Frontend
frappe.call({
    method: 'upande_webshop.api.pack_rate.get_pack_rate',
    args: { item_code: 'EVER-RED-50CM', box_name: 'ZIM', length_cm: 50 },
    callback: (r) => console.log(r.message.pack_rate),  // 350
});
```

---

## Caching note

The API caches results in Redis under key `pack_rate_cache`. The cache is
auto-cleared whenever a Variety Pack Rate, Item Group Pack Rate, or Box Type
is saved. If you ever need to manually clear it:

```python
frappe.cache().delete_key("pack_rate_cache")
```
