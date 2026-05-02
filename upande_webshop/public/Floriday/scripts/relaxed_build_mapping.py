#!/usr/bin/env python3
import json, re

tradeitems_path = '/home/wilfredtinega/Floriday/tradeitems.json'
items_path = '/home/wilfredtinega/Floriday/items.json'
existing_mapping_path = '/home/wilfredtinega/Floriday/item_mapping.py'
output_mapping_path = existing_mapping_path

size_regex = re.compile(r"\s*(?:-|–)?\s*(?:length\s*)?(?:\d{2}(?:/\d{2})?(?:cm)?)\s*$", re.I)

def normalize(s):
    if not s:
        return ''
    s = s.lower()
    s = size_regex.sub('', s)
    s = re.sub(r"[^a-z0-9]+", ' ', s)
    s = re.sub(r"\s+", ' ', s).strip()
    return s

# load targets
with open(items_path, 'r', encoding='utf-8') as f:
    raw = f.read().strip().splitlines()
    targets = [line.strip() for line in raw if line.strip()]

normalized_targets = {t: normalize(t) for t in targets}

# load tradeitems
with open(tradeitems_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# build search index: for each item produce normalized tradeItemName (nl) and supplierArticleCode
index = []
for itm in data:
    tid = itm.get('tradeItemId')
    sup = (itm.get('supplierArticleCode') or '')
    tname = itm.get('tradeItemName')
    if isinstance(tname, dict):
        tname_val = tname.get('nl') or next(iter(tname.values()))
    else:
        tname_val = tname or ''
    norm_name = normalize(tname_val)
    norm_sup = normalize(sup)
    index.append((tid, norm_name, norm_sup, tname_val, sup))

mapping = {}

for orig, norm in normalized_targets.items():
    chosen = None
    # first try exact normalized match
    for tid, nname, nsup, tname_val, sup in index:
        if nname == norm:
            chosen = tid; break
    # then try substring in tname
    if not chosen:
        for tid, nname, nsup, tname_val, sup in index:
            if norm and norm in nname:
                chosen = tid; break
    # then try substring in supplierArticleCode
    if not chosen:
        for tid, nname, nsup, tname_val, sup in index:
            if norm and norm in nsup:
                chosen = tid; break
    mapping[orig] = chosen

# write python mapping file
with open(output_mapping_path, 'w', encoding='utf-8') as f:
    f.write('# Auto-generated ITEM_MAPPING (relaxed substring matching)\n')
    f.write('ITEM_MAPPING = {\n')
    for k in targets:
        v = mapping.get(k)
        if v is None:
            f.write(f'    {json.dumps(k)}: None,\n')
        else:
            f.write(f'    {json.dumps(k)}: {json.dumps(v)},\n')
    f.write('}\n')

print('WROTE', output_mapping_path)
