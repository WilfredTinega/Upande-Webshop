#!/usr/bin/env python3
"""
Post sales orders from sales_order.json to ERPNext.
Creates each Sales Order as a draft and then submits (confirms) it.

Configuration via environment variables:
- ERP_URL (required) e.g. https://erp.example.com
- ERP_API_KEY and ERP_API_SECRET (preferred) OR ERP_USERNAME and ERP_PASSWORD

Usage:
    python3 scripts/post_sales_orders_to_erpnext.py [--dry-run] [--rate-limit MS] [--sales-file path]

Notes:
- Expects `sales_order.json` to contain an array of objects matching ERPNext Sales Order fields.
- You may need to adapt the field mapping before running.
"""
import os
import json
import time
import argparse
import logging
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_SALES_FILE = os.path.join(os.path.dirname(__file__), '..', 'sales_order.json')

class ERPClient:
    def __init__(self, base_url: str, api_key: Optional[str]=None, api_secret: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        if api_key and api_secret:
            self.session.headers.update({'Authorization': f'token {api_key}:{api_secret}'})
        elif username and password:
            self.session.auth = (username, password)
        # Common headers
        self.session.headers.update({'Content-Type': 'application/json'})

    def insert_doc(self, doctype: str, doc: dict) -> dict:
        url = f"{self.base_url}/api/method/frappe.client.insert"
        payload = {"doc": {"doctype": doctype, **doc}}
        r = self.session.post(url, json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Insert failed: {r.status_code} {r.text}")
        return r.json()

    def submit_doc(self, doctype: str, name: str) -> dict:
        url = f"{self.base_url}/api/method/frappe.client.submit"
        payload = {"doctype": doctype, "name": name}
        r = self.session.post(url, json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"Submit failed: {r.status_code} {r.text}")
        return r.json()

    def get_resource(self, doctype: str, name: Optional[str] = None, fields: Optional[list] = None, limit: int = 1) -> dict:
        """Retrieve resource(s) from ERPNext. If name is provided, fetch that document; otherwise return up to `limit` docs."""
        if name:
            url = f"{self.base_url}/api/resource/{requests.utils.requote_uri(doctype)}/{requests.utils.requote_uri(name)}"
        else:
            # request list
            qs_fields = f"&fields={json.dumps(fields)}" if fields else "&fields=[\"*\"]"
            url = f"{self.base_url}/api/resource/{requests.utils.requote_uri(doctype)}?limit_page_length={limit}{qs_fields}"
        r = self.session.get(url)
        if r.status_code != 200:
            raise RuntimeError(f"Get resource failed: {r.status_code} {r.text}")
        return r.json()

    def get_floriday_settings(self, name: Optional[str] = None) -> Optional[dict]:
        """Convenience to fetch Floriday Settings doctype. Returns the first record when name is None."""
        doctype = 'Floriday Settings'
        resp = self.get_resource(doctype, name=name, fields=["*"] , limit=1)
        # response for list is {"data": [...]}, for single resource it's {"data": {...}}
        data = resp.get('data')
        if isinstance(data, list):
            return data[0] if data else None
        return data


def load_sales_orders(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit('sales_order.json must contain a JSON array of sales orders')
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='Do everything except POST to ERPNext')
    ap.add_argument('--rate-limit', type=int, default=500, help='Milliseconds to wait between requests')
    ap.add_argument('--sales-file', default=DEFAULT_SALES_FILE, help='Path to sales_order.json')
    ap.add_argument('--continue-on-error', action='store_true', help='Continue processing next orders when one fails')
    args = ap.parse_args()

    # config from env
    erp_url = os.getenv('ERP_URL')
    api_key = os.getenv('ERP_API_KEY')
    api_secret = os.getenv('ERP_API_SECRET')
    username = os.getenv('ERP_USERNAME')
    password = os.getenv('ERP_PASSWORD')

    if not erp_url and not args.dry_run:
        raise SystemExit('ERP_URL environment variable is required (or run with --dry-run)')

    client = None
    if not args.dry_run:
        client = ERPClient(erp_url, api_key=api_key, api_secret=api_secret, username=username, password=password)

    # Optionally fetch sales orders from Floriday using stored headers in ERPNext
    orders = None
    if args.fetch_from_floriday:
        if args.dry_run:
            logger.info('Requested fetch-from-floriday but running in dry-run mode; will only attempt to fetch settings')
        if not client:
            raise SystemExit('ERP client not initialized; set ERP_URL and credentials when using --fetch-from-floriday')
        settings_name = os.getenv('FLORIDAY_SETTINGS_NAME')
        try:
            settings = client.get_floriday_settings(name=settings_name)
            logger.info('Fetched Floriday Settings: %s', {k: v for k, v in settings.items() if k in ('name','endpoint','sales_endpoint')})
        except Exception as e:
            raise SystemExit(f'Failed to fetch Floriday Settings from ERPNext: {e}')

        # Expect settings to contain an endpoint and headers info. We try multiple keys.
        # Prefer explicit fields used by your Frappe integration: api_key, access_token, base_url
        floriday_endpoint = settings.get('sales_endpoint') or settings.get('endpoint') or settings.get('base_url') or os.getenv('FLORIDAY_ENDPOINT')

        # Build headers similar to the Frappe function: Authorization: Bearer <access_token> and X-Api-Key
        floriday_headers = {}
        api_key_field = settings.get('api_key') or settings.get('API_KEY') or os.getenv('FLORIDAY_API_KEY')
        access_token_field = settings.get('access_token') or settings.get('ACCESS_TOKEN') or os.getenv('FLORIDAY_ACCESS_TOKEN')
        if access_token_field:
            floriday_headers['Authorization'] = f'Bearer {access_token_field}'
        if api_key_field:
            floriday_headers['X-Api-Key'] = api_key_field
        # sensible defaults
        floriday_headers.setdefault('Content-Type', 'application/json')
        floriday_headers.setdefault('Accept', 'application/json')

        if not floriday_endpoint:
            raise SystemExit('Floriday endpoint not found in Floriday Settings and FLORIDAY_ENDPOINT not set')

        logger.info('Fetching sales orders from Floriday endpoint: %s', floriday_endpoint)
        if args.dry_run:
            logger.info('[DRY-RUN] Would GET %s with headers %s', floriday_endpoint, floriday_headers)
            orders = []
        else:
            r = requests.get(floriday_endpoint, headers=floriday_headers)
            if r.status_code != 200:
                raise SystemExit(f'Failed to fetch sales orders from Floriday: {r.status_code} {r.text}')
            orders = r.json()
            if not isinstance(orders, list):
                # try to find list under data key
                if isinstance(orders, dict) and 'data' in orders and isinstance(orders['data'], list):
                    orders = orders['data']
                else:
                    raise SystemExit('Floriday response is not a list of orders')
    else:
        orders = load_sales_orders(args.sales_file)
    logger.info('Loaded %d sales orders from %s', len(orders), args.sales_file)

    results = []
    for i, order in enumerate(orders, start=1):
        logger.info('Processing order %d/%d', i, len(orders))
        try:
            # Remove any existing meta fields that would break insert
            order_doc = dict(order)
            order_doc.pop('name', None)  # let ERPNext generate the name

            if args.dry_run:
                logger.info('[DRY-RUN] Would create Sales Order with fields: %s', {k:v for k,v in order_doc.items() if k in ['customer','transaction_date','items']})
                results.append({'status': 'dry-run', 'order': order_doc})
                continue

            # Insert as draft
            resp = client.insert_doc('Sales Order', order_doc)
            message = resp.get('message')
            if not message or 'name' not in message:
                raise RuntimeError(f'Unexpected insert response: {resp}')
            name = message['name']
            logger.info('Created Sales Order %s (draft)', name)

            # Submit the document (confirm)
            resp2 = client.submit_doc('Sales Order', name)
            logger.info('Submitted Sales Order %s', name)
            results.append({'status': 'submitted', 'name': name})

            # rate-limit
            time.sleep(args.rate_limit / 1000.0)

        except Exception as e:
            logger.exception('Failed to process order %d: %s', i, e)
            results.append({'status': 'error', 'error': str(e), 'order': order.get('name') or order.get('supplier_reference')})
            if not args.continue_on_error:
                break

    # Summary
    success = [r for r in results if r.get('status') == 'submitted']
    errors = [r for r in results if r.get('status') == 'error']
    logger.info('Finished processing: %d submitted, %d errors', len(success), len(errors))
    # write report
    out = os.path.join(os.path.dirname(args.sales_file), 'erp_post_report.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump({'results': results}, f, indent=2)
    logger.info('Wrote report to %s', out)


if __name__ == '__main__':
    main()
