#!/usr/bin/env python3
import json, csv

p = '/home/wilfredtinega/Floriday/tradeitems.json'
out_md = '/home/wilfredtinega/Floriday/tradeitems_table.md'
out_csv = '/home/wilfredtinega/Floriday/tradeitems_table.csv'

with open(p, 'r', encoding='utf-8') as f:
    data = json.load(f)

with open(out_md, 'w', encoding='utf-8') as fmd, open(out_csv, 'w', encoding='utf-8', newline='') as fc:
    fmd.write('|tradeItemId|tradeItemName|\n|---|---|\n')
    writer = csv.writer(fc)
    writer.writerow(['tradeItemId', 'tradeItemName'])
    for itm in data:
        tid = itm.get('tradeItemId', '')
        tname = itm.get('tradeItemName')
        if isinstance(tname, dict):
            # prefer 'nl' if present, else first value
            name = tname.get('nl') or (next(iter(tname.values())) if tname else '')
        else:
            name = tname or ''
        safe_md = str(name).replace('\n', ' ').replace('|', '\\|')
        fmd.write(f'|{tid}|{safe_md}|\n')
        writer.writerow([tid, name])

print('WROTE', out_md, out_csv)
