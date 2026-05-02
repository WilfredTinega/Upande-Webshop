Post sales orders to ERPNext (draft -> submit)

Overview

This repository script posts sales orders from `sales_order.json` to an ERPNext instance. Each Sales Order is created (draft) and then submitted (confirmed).

Requirements

- Python 3.8+
- requests (pip install requests)

Environment variables (set before running)

- ERP_URL: e.g. https://erp.example.com
- ERP_API_KEY and ERP_API_SECRET (recommended) OR
- ERP_USERNAME and ERP_PASSWORD (basic auth)

Usage

Dry run (no network calls):

```bash
python3 scripts/post_sales_orders_to_erpnext.py --dry-run
```

Real run (create and submit orders):

```bash
export ERP_URL=https://erp.example.com
export ERP_API_KEY=yourkey
export ERP_API_SECRET=yoursecret
python3 scripts/post_sales_orders_to_erpnext.py --rate-limit 500
```

Options

- --dry-run : don't POST, only print what would be done
- --rate-limit MS : milliseconds to sleep between requests (default 500)
- --sales-file PATH : path to sales_order.json
- --continue-on-error : continue processing remaining orders when one fails

Notes and caveats

- The script expects `sales_order.json` to contain an array of objects matching ERPNext Sales Order fields (customer, items, delivery_date, etc.). If your data uses different field names, map them to ERPNext fields before running.
- The script uses the frappe.client.insert and frappe.client.submit API methods. If your ERPNext version or deployment uses different auth or API constraints, adjust accordingly.
- Always test with `--dry-run` and a small subset of orders first.
