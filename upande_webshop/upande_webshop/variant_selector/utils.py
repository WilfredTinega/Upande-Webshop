import frappe
from frappe.utils import cint, flt

from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
    get_shopping_cart_settings,
)
from upande_webshop.upande_webshop.shopping_cart.cart import _set_price_list
from upande_webshop.upande_webshop.variant_selector.item_variants_cache import ItemVariantsCacheManager
from erpnext.utilities.product import get_price
from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses


def get_item_codes_by_attributes(attribute_filters, template_item_code=None):
    items = []

    for attribute, values in attribute_filters.items():
        attribute_values = values if isinstance(values, list) else [values]

        if not attribute_values:
            continue

        wheres = ["( attribute = %s and attribute_value = %s )" for _ in attribute_values]
        query_values = [val for pair in zip([attribute]*len(attribute_values), attribute_values, strict=True) for val in pair]

        attribute_query = " or ".join(wheres)

        variant_of_query = ""
        if template_item_code:
            variant_of_query = "AND t2.variant_of = %s"
            query_values.append(template_item_code)

        query = f"""
            SELECT t1.parent
            FROM `tabItem Variant Attribute` t1
            WHERE 1 = 1
                AND ({attribute_query})
                AND EXISTS (
                    SELECT 1
                    FROM `tabItem` t2
                    WHERE t2.name = t1.parent
                    {variant_of_query}
                )
            GROUP BY t1.parent
            ORDER BY NULL
        """

        item_codes = set([r[0] for r in frappe.db.sql(query, query_values)])  # nosemgrep
        items.append(item_codes)

    return list(set.intersection(*items)) if items else []


@frappe.whitelist(allow_guest=True)
def get_attributes_and_values(item_code):
    """Build a list of attributes and their possible values."""
    item_cache = ItemVariantsCacheManager(item_code)
    item_variants_data = item_cache.get_item_variants_data()

    attributes = get_item_attributes(item_code)
    attribute_list = [a.attribute for a in attributes]

    valid_options = {}
    for _item_code, attribute, attribute_value in item_variants_data:  # B007 fix
        if attribute in attribute_list:
            valid_options.setdefault(attribute, set()).add(attribute_value)

    item_attribute_values = frappe.db.get_all(
        "Item Attribute Value", ["parent", "attribute_value", "idx"], order_by="parent asc, idx asc"
    )
    ordered_attribute_value_map = frappe._dict()
    for iv in item_attribute_values:
        ordered_attribute_value_map.setdefault(iv.parent, []).append(iv.attribute_value)

    for attr_name in attribute_list:
        if attr_name not in ordered_attribute_value_map:
            numeric_list = sorted(
                [i for i in valid_options[attr_name] if i.replace(".", "").isnumeric()], key=float
            )
            ordered_attribute_value_map[attr_name] = numeric_list

    # build attribute values in idx order
    for attr in attributes:
        valid_attribute_values = valid_options.get(attr.attribute, [])
        ordered_values = ordered_attribute_value_map.get(attr.attribute, [])
        attr["values"] = [v for v in ordered_values if v in valid_attribute_values]

    return attributes


@frappe.whitelist(allow_guest=True)
def get_next_attribute_and_values(item_code, selected_attributes):
    """Find next attribute, valid options, exact match, and available qty for selected attributes."""
    selected_attributes = frappe.parse_json(selected_attributes)

    item_cache = ItemVariantsCacheManager(item_code)
    item_variants_data = item_cache.get_item_variants_data()
    attributes = get_item_attributes(item_code)
    attribute_list = [a.attribute for a in attributes]

    filtered_items = get_items_with_selected_attributes(item_code, selected_attributes)

    next_attribute = next((a for a in attribute_list if a not in selected_attributes), None)

    valid_options_for_attributes = frappe._dict({a: set() for a in attribute_list})
    for a in attribute_list:
        if a in selected_attributes:
            valid_options_for_attributes[a].add(selected_attributes[a])

    for _item_code, attribute, attribute_value in item_variants_data:  # B007 fix
        if _item_code in filtered_items and attribute not in selected_attributes and attribute in attribute_list:
            valid_options_for_attributes[attribute].add(attribute_value)

    optional_attributes = item_cache.get_optional_attributes()
    exact_match = []
    if len(selected_attributes) >= (len(attribute_list) - len(optional_attributes)):
        item_attribute_value_map = item_cache.get_item_attribute_value_map()
        for _item_code, attr_dict in item_attribute_value_map.items():  # B007 fix
            if _item_code in filtered_items and set(attr_dict.keys()) == set(selected_attributes.keys()):
                exact_match.append(_item_code)

    filtered_items_count = len(filtered_items)
    product_info, product_id, warehouse = None, "", ""

    if exact_match or filtered_items:
        if exact_match and len(exact_match) == 1:
            product_id = exact_match[0]
        elif filtered_items_count == 1:
            product_id = next(iter(filtered_items))  # RUF015 fix

        if product_id:
            warehouse = frappe.get_cached_value(
                "Website Item", {"item_code": product_id}, "website_warehouse"
            )

            cart_settings = get_shopping_cart_settings()
            if exact_match and product_id:
                product_info = get_item_variant_price_dict(product_id, cart_settings)
                if product_info:
                    product_info["is_stock_item"] = frappe.get_cached_value("Item", product_id, "is_stock_item")
                    product_info["allow_items_not_in_stock"] = cint(cart_settings.allow_items_not_in_stock)

    available_qty = 0.0
    if warehouse and frappe.get_cached_value("Warehouse", warehouse, "is_group") == 1:
        warehouses = get_child_warehouses(warehouse)
    else:
        warehouses = [warehouse] if warehouse else []

    for wh in warehouses:
        available_qty += flt(frappe.db.get_value("Bin", {"item_code": product_id, "warehouse": wh}, "actual_qty"))

    return {
        "next_attribute": next_attribute,
        "valid_options_for_attributes": valid_options_for_attributes,
        "filtered_items_count": filtered_items_count,
        "filtered_items": filtered_items if filtered_items_count < 10 else [],
        "exact_match": exact_match,
        "product_info": product_info,
        "available_qty": available_qty,
    }


def get_items_with_selected_attributes(item_code, selected_attributes):
    item_cache = ItemVariantsCacheManager(item_code)
    attribute_value_item_map = item_cache.get_attribute_value_item_map()
    items = [set(attribute_value_item_map.get((attr, val), [])) for attr, val in selected_attributes.items()]
    return set.intersection(*items) if items else set()


# utilities

def get_item_attributes(item_code):
    attributes = frappe.db.get_all(
        "Item Variant Attribute",
        fields=["attribute"],
        filters={"parenttype": "Item", "parent": item_code},
        order_by="idx asc",
    )

    optional_attributes = ItemVariantsCacheManager(item_code).get_optional_attributes()
    for a in attributes:
        if a.attribute in optional_attributes:
            a.optional = True

    return attributes


def get_item_variant_price_dict(item_code, cart_settings):
    if cart_settings.enabled and cart_settings.show_price:
        is_guest = frappe.session.user == "Guest"
        if not is_guest or not cart_settings.hide_price_for_guest:
            price_list = _set_price_list(cart_settings, None)
            price = get_price(
                item_code, price_list, cart_settings.default_customer_group, cart_settings.company
            )
            return {"price": price}
    return None
