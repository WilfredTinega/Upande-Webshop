from frappe import _

from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
	get_setup_check_fields,
)

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.body_class = "product-page"

	data = get_setup_check_fields()
	checked = data["fields"]
	missing = [f for f in checked if not f["exists"]]

	groups = {}
	for f in checked:
		groups.setdefault(f["doctype"], []).append(f)

	context.groups = groups
	context.missing = missing
	context.all_ok = len(missing) == 0
	context.use_sales_order = data["use_sales_order"]
	context.title = _("Webshop Setup Check")
