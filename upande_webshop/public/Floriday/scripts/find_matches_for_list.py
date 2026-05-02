#!/usr/bin/env python3
import json, re

tradeitems_path = '/home/wilfredtinega/Floriday/tradeitems.json'

names = [
"Bellalinda Bricks",
"Bellalinda Mostaza",
"Cherry Blossom",
"Dima Bombastic",
"Eye Liner",
"Fire Flash",
"Happy Wedding",
"Harper",
"Holly",
"In Love",
"Inker Kristin",
"Julieta",
"Julieta Cerise",
"Julietta Cerise",
"Keijers Coral",
"Keijsers Coral",
"Lovely Harper",
"Mansfield Park",
"Milky Way",
"Misty Bubbles",
"Namaskar",
"Orange Babe",
"Pink Dimension",
"Pushkin",
"Radiant Rabecca",
"Radiant Rebecca",
"Red Trophy",
"Royal Porcellina",
"Silver Pink",
"Snow Bubbles",
"Snowy Trendsetter",
"Summer Rose",
"Sweet Giselle",
"Sweet Harper",
"Wedding Invite",
"Yellow Babe",
]

size_regex = re.compile(r"\s*(?:-|–)?\s*(?:length\s*)?(?:\d{2}(?:/\d{2})?(?:cm)?)\s*$", re.I)

def normalize(s):
    if not s:
        return ''
    s = s.lower()
    s = size_regex.sub('', s)
    s = re.sub(r"[^a-z0-9]+", ' ', s)
    s = re.sub(r"\s+", ' ', s).strip()
    return s

with open(tradeitems_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

index = []
for itm in data:
    tid = itm.get('tradeItemId')
    sup = itm.get('supplierArticleCode') or ''
    tname = itm.get('tradeItemName')
    if isinstance(tname, dict):
        tname_val = tname.get('nl') or next(iter(tname.values()))
    else:
        tname_val = tname or ''
    index.append((tid, tname_val, sup, normalize(tname_val), normalize(sup)))

results = {}
for name in names:
    norm = normalize(name)
    found = []
    for tid, tname_val, sup, n_tname, n_sup in index:
        if norm in n_tname or norm in n_sup:
            found.append((tid, tname_val, sup))
    results[name] = found[:5]

# print results
for name, items in results.items():
    print(f"{name}: {len(items)} matches")
    for tid, tname_val, sup in items:
        print(f"  {tid} | {tname_val} | {sup}")
    print()

# also print unique tradeItemIds found
all_tids = set()
for items in results.values():
    for tid, *_ in items:
        all_tids.add(tid)
print('TOTAL UNIQUE TIDS FOUND:', len(all_tids))
