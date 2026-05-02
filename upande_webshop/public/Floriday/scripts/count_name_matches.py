#!/usr/bin/env python3
import json, re, csv

tradeitems_path = '/home/wilfredtinega/Floriday/tradeitems.json'
items_path = '/home/wilfredtinega/Floriday/items.json'

# Normalization: lowercase, strip, remove trailing size tokens like "- Length 70", " 70cm", " 70", " 70/25"
size_regex = re.compile(r"\s*(?:-|–)?\s*(?:length\s*)?(?:\d{2}(?:/\d{2})?(?:cm)?)\s*$", re.I)

def normalize(name):
    if not name:
        return ''
    s = name.strip().lower()
    # remove common prefixes/suffixes like '- length 70'
    s = size_regex.sub('', s)
    # collapse multiple spaces
    s = re.sub(r"\s+", ' ', s)
    return s

# load target names (items.json). It appears newline-separated, so read lines and strip empties
with open(items_path, 'r', encoding='utf-8') as f:
    raw = f.read().strip().splitlines()
    targets = [line.strip() for line in raw if line.strip()]

# normalize targets
normalized_targets = {normalize(t): t for t in targets}

# prepare counts
counts = {t: 0 for t in normalized_targets.keys()}
matched_ids = {t: [] for t in normalized_targets.keys()}

# load tradeitems (large JSON array)
with open(tradeitems_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for itm in data:
    tname = itm.get('tradeItemName')
    if isinstance(tname, dict):
        # prefer nl
        name = tname.get('nl') or (next(iter(tname.values())) if tname else '')
    else:
        name = tname or ''
    norm = normalize(name)
    if norm in normalized_targets:
        counts[norm] += 1
        matched_ids[norm].append(itm.get('tradeItemId'))

# produce summary
total_matches = sum(counts.values())

# write CSV report
out_csv = '/home/wilfredtinega/Floriday/match_counts.csv'
with open(out_csv, 'w', encoding='utf-8', newline='') as fc:
    writer = csv.writer(fc)
    writer.writerow(['target_name','normalized_target','count','example_tradeItemIds'])
    for norm, original in normalized_targets.items():
        writer.writerow([original, norm, counts.get(norm,0), ';'.join(matched_ids.get(norm,[])[:5])])

print('Total matched trade items:', total_matches)
for norm, original in normalized_targets.items():
    print(f"{original}: {counts.get(norm,0)}")
print('\nWrote', out_csv)
