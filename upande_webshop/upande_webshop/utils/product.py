import frappe



def get_web_item_qty_in_stock(item_code, item_warehouse_field, warehouse=None):
	"""Total available qty across the storefront warehouse set, in sales UOM.

	Source-of-truth choice mirrors shopping_cart.cart._stock_uom_qty_available:
	  - Variant or template items resolve length at the item level (each
	    variant = one length), so core Bin is correct.
	  - Plain items read core Bin too, summed across the warehouse set.

	Warehouse resolution prefers the storefront list (Webshop Settings →
	Warehouses) so the qty matches what the listing card displays. Falls back
	to the per-item website_warehouse if that list is empty, matching the
	prior behavior."""
	in_stock = 0
	item_meta = frappe.db.get_value(
		"Item", item_code, ["variant_of", "has_variants", "is_stock_item"], as_dict=True
	)
	if not item_meta:
		# Virtual variant code (e.g. "Beatrice-73CM") that isn't a real Item.
		# Treat as non-stock, not-in-stock so callers don't crash.
		return frappe._dict({"in_stock": 0, "stock_qty": 0, "is_stock_item": 0})
	template_item_code = item_meta.variant_of
	is_stock_item = item_meta.is_stock_item
	is_variant_or_template = bool(item_meta.has_variants) or bool(template_item_code)

	if not warehouse:
		warehouse = frappe.db.get_value("Website Item", {"item_code": item_code}, item_warehouse_field)

	if not warehouse and template_item_code and template_item_code != item_code:
		warehouse = frappe.db.get_value(
			"Website Item", {"item_code": template_item_code}, item_warehouse_field
		)

	# Gated: once the publish feature is active, plain items show ONLY their
	# published total (0 / out of stock if this item was never enabled).
	from upande_webshop.upande_webshop.utils.enabled_stock import (
		enabled_feature_active,
		enabled_total_qty,
	)
	if not is_variant_or_template and enabled_feature_active():
		published_total = enabled_total_qty(item_code)
		return frappe._dict(
			{
				"in_stock": 1 if published_total > 0 else 0,
				"stock_qty": published_total,
				"is_stock_item": is_stock_item,
			}
		)

	# Plain items read from the shelf when shelf mode is on. Shelf qty is in stems
	# (the stock UOM); no warehouse scoping applies.
	from upande_webshop.upande_webshop.utils.shelf_stock import (
		get_shelf_qty,
		use_shelf_stock,
	)
	if not is_variant_or_template and use_shelf_stock():
		total_stock = get_shelf_qty(item_code)
		return frappe._dict(
			{
				"in_stock": 1 if total_stock > 0 else 0,
				"stock_qty": total_stock,
				"is_stock_item": is_stock_item,
			}
		)

	# Use storefront warehouse set (matches listing's _attach_stock_qty); fall back
	# to the resolved per-item warehouse if no storefront set is configured.
	from upande_webshop.upande_webshop.product_data_engine.query import (
		_all_storefront_warehouses,
	)
	warehouses = _all_storefront_warehouses(warehouse)

	total_stock = 0.0
	in_stock = 0
	if warehouses:
		placeholders = ",".join(["%s"] * len(warehouses))
		# Both variants and plain items read core Bin, applying the item's
		# sales-UOM conversion factor.
		rows = frappe.db.sql(
			"""
			SELECT S.actual_qty / IFNULL(C.conversion_factor, 1)
			FROM `tabBin` S
			INNER JOIN `tabItem` I ON S.item_code = I.Item_code
			LEFT JOIN `tabUOM Conversion Detail` C
			  ON I.sales_uom = C.uom AND C.parent = I.Item_code
			WHERE S.item_code = %s AND S.warehouse IN ({})
			""".format(placeholders),
			(item_code, *warehouses),
		)
		for row in rows:
			total_stock += row[0] or 0

		in_stock = total_stock > 0 and 1 or 0

	return frappe._dict(
		{"in_stock": in_stock, "stock_qty": total_stock, "is_stock_item": is_stock_item}
	)


def get_non_stock_item_status(item_code, item_warehouse_field):
	# if item is a product bundle, check if its bundle items are in stock
	if frappe.db.exists("Product Bundle", item_code):
		items = frappe.get_doc("Product Bundle", item_code).get_all_children()
		bundle_warehouse = frappe.db.get_value(
			"Website Item", {"item_code": item_code}, item_warehouse_field
		)
		return all(
			get_web_item_qty_in_stock(d.item_code, item_warehouse_field, bundle_warehouse).in_stock
			for d in items
		)
	else:
		return 1
