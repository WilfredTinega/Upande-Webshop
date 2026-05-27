# Copyright (c) 2026, Upande LTD and contributors
# License: GNU General Public License v3. See license.txt

no_cache = 1

from upande_webshop.upande_webshop.shopping_cart.cart import get_cart_quotation
from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
	apply_webshop_setup_guard,
)


def get_context(context):
	if apply_webshop_setup_guard(context):
		return
	context.body_class = "product-page"
	context.update(get_cart_quotation())
