# Floriday Sales Order & Order Fulfillment

## Overview

Two API modules handle the Floriday integration lifecycle:

| Module | File | Purpose |
|--------|------|---------|
| Sales Order Sync | `floriday_sales_order.py` | Pulls orders from Floriday and creates ERPNext Sales Orders |
| Order Fulfillment | `floriday_order_fullfillment.py` | Creates fulfillment orders in Floriday for submitted Sales Orders |

---

## 1. Floriday Sales Order Sync

### Endpoint Called
| Method | URL | Parameters |
|--------|-----|------------|
| GET | `{BASE_URL}/sales-orders` | `supplierOrganizationId`, `startDateTime`, `endDateTime`, `pageSize=100`, `limitResult=1000` |

### Time Range
Fetches orders from the **last 1 hour** (`startDateTime = now - 1h`, `endDateTime = now`).

### Required: Floriday Settings Fields
| Field | Description |
|-------|-------------|
| `api_key` | Floriday API key |
| `base_url` | Floriday API base URL |
| `access_token` | Bearer token for authorization |
| `organization_supplier_id` | Supplier org ID used as `supplierOrganizationId` |
| `warehouse` | Default warehouse for Sales Order items |
| `company` | ERPNext company |

### DocTypes Queried
| DocType | Purpose | Key Filters |
|---------|---------|-------------|
| Floriday Settings | Load API credentials | `limit_page_length=1` |
| Sales Order | Check for duplicate orders | `po_no = floriday_order_id`, `docstatus < 2` |
| Customer | Match buyer by Floriday org ID | `custom_floriday_id = customer_org_id` |
| Delivery Point | Map GLN to delivery location | `custom_floriday_delivery_id = gln_code` |
| Floriday Item Mapping | Resolve item code | `trade_item_id = floriday_trade_item_id` |
| Item | Fallback item lookup | `floriday_trade_item_id = value` |
| Stock Entry / Detail | Get farm & business unit from item | `item_code = item_code`, `docstatus = 1` |
| Currency Exchange | Get EUR→KES exchange rate | `from_currency`, `to_currency`, `date` |
| Company | Get company name | — |
| Warehouse | Get default warehouse | `company`, `is_group = 0` |

### Custom Fields — Sales Order
| Field | Value Source |
|-------|-------------|
| `custom_order_name` | Sequential per customer (e.g. `CUST-001`) |
| `custom_sales_order_type` | Hardcoded: `"Floriday"` |
| `custom_delivery_point` | Delivery Point name from GLN mapping |
| `custom_floriday_delivery_gln` | Raw GLN (if no Delivery Point mapping found) |
| `custom_delivery_address` | From Floriday order `deliveryLocation.address` |
| `custom_delivery_city` | From Floriday order `deliveryLocation.city` |
| `custom_delivery_country` | From Floriday order `deliveryLocation.country` |
| `custom_delivery_postal_code` | From Floriday order `deliveryLocation.postalCode` |
| `custom_ordered_stems` | Total stems from order lines |
| `custom_farm` | From Stock Entry of item |
| `custom_business_unit` | From Stock Entry of item |

### Custom Fields — Other DocTypes
| DocType | Field | Purpose |
|---------|-------|---------|
| Customer | `custom_floriday_id` | Maps ERPNext customer to Floriday buyer org |
| Delivery Point | `custom_floriday_delivery_id` | Maps GLN code to ERPNext Delivery Point |
| Item | `floriday_trade_item_id` | Maps Floriday trade item to ERPNext item |

### Logic Flow
1. Load Floriday Settings
2. Fetch orders from `GET /sales-orders` (last 1 hour, status = `COMMITTED`)
3. For each order, skip if already exists (`po_no` check)
4. Resolve customer via `custom_floriday_id` — create if not found
5. Map delivery GLN → Delivery Point via `custom_floriday_delivery_id`
6. Resolve item code via Floriday Item Mapping or `Item.floriday_trade_item_id`
7. Get farm/business unit from latest Stock Entry for item
8. Get exchange rate (EUR → KES)
9. Create, insert, and submit Sales Order

---

## 2. Order Fulfillment

### Endpoint Called
| Method | URL | Purpose |
|--------|-----|---------|
| POST | `{BASE_URL}/fulfillment-orders` | Create fulfillment order |

### Time Range
Processes Sales Orders created in the **last 1 hour** (`creation >= now - 1h`).

### Required: Floriday Settings Fields
| Field | Description |
|-------|-------------|
| `api_key` | Floriday API key |
| `base_url` | Floriday API base URL |
| `access_token` | Bearer token for authorization |
| `organization_supplier_id` | Supplier org ID (carrier + packing agent) |
| `default_gln` | Fallback GLN if Delivery Point has no GLN set |

### DocTypes Queried
| DocType | Purpose | Key Filters |
|---------|---------|-------------|
| Floriday Settings | Load API credentials | `limit_page_length=1` |
| Sales Order | Find orders to fulfill | `docstatus=1`, `customer_group="Floriday"`, `po_no != ""`, `creation >= start_time` |
| Delivery Point | Get delivery GLN | `name = custom_delivery_point` |
| Delivery Note | Update with fulfillment ID | `docstatus=1`, `against_sales_order = SO name` |

### Custom Fields — Sales Order
| Field | Usage |
|-------|-------|
| `custom_delivery_point` | Links to Delivery Point to retrieve GLN |
| `remarks` | Appended with fulfillment ID, stems, packages, GLN |

### Custom Fields — Delivery Point
| Field | Usage |
|-------|-------|
| `custom_floriday_delivery_id` | GLN sent as `deliveryLocationGln` in payload |

### POST /fulfillment-orders Payload
```json
{
  "fulfillmentOrderId": "<new UUID>",
  "carrierOrganizationId": "<organization_supplier_id>",
  "logisticHub": "NONE",
  "oneLabelOnly": false,
  "loadCarriers": [
    {
      "loadCarrierType": "NONE",
      "numberOfAdditionalLayers": 0,
      "sortIndex": 0,
      "loadCarrierReference": "<last 14 chars of SO name>",
      "loadCarrierItems": [
        {
          "fulfillmentRequestId": "<po_no (Floriday salesOrderId)>",
          "numberOfPackages": "<ceil(total_stems / 200)>",
          "serviceCode": 1,
          "packingAgentOrganizationId": "<organization_supplier_id>",
          "sortIndex": 0,
          "deliveryRemarks": "<delivery_notes or 'Standard delivery'>",
          "commercialInvoiceReference": "<last 10 of po_no>-<last 8 of SO name> (max 26 chars)"
        }
      ]
    }
  ],
  "deliveryLocationGln": "<from Delivery Point or default_gln>"
}
```

### Package Calculation
```
number_of_packages = ceil(total_stems / 200)
```
Where `total_stems = sum of item.qty across all Sales Order items`.

### Logic Flow
1. Load Floriday Settings
2. Query submitted Sales Orders from last 1 hour (`customer_group = "Floriday"`, `po_no` set)
3. For each order:
   - Sum item quantities → `total_stems`
   - Calculate `number_of_packages`
   - Resolve delivery GLN from `custom_delivery_point` → `custom_floriday_delivery_id`
   - Fallback to `settings.default_gln` if not found
   - Generate references and new UUID for `fulfillmentOrderId`
   - POST to `/fulfillment-orders`
4. On success (200/201): append fulfillment info to Sales Order remarks, update Delivery Note
5. On 400 "already fulfilled": treat as success (idempotent)

---

## Field Dependency Map

```
Floriday Order
    └── salesOrderId        → Sales Order.po_no
    └── buyerOrganizationId → Customer.custom_floriday_id
    └── deliveryGln         → Delivery Point.custom_floriday_delivery_id
    └── tradeItemId         → Item.floriday_trade_item_id
                              or Floriday Item Mapping.trade_item_id

Sales Order
    └── custom_delivery_point → Delivery Point.custom_floriday_delivery_id
                                    → fulfillment payload.deliveryLocationGln
    └── po_no               → fulfillment payload.fulfillmentRequestId
    └── items[].qty         → total_stems → numberOfPackages
```
