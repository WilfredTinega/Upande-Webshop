import os

import frappe
import click

from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.modules.utils import reload_doc


def after_install():
	add_custom_fields()
	navbar_add_products_link()
	resync_app_resources()
	normalize_webshop_workspace()
	ensure_desktop_icon()
	ensure_variant_attributes()
	apply_webshop_settings_defaults()
	cleanup_blocking_property_setters()
	say_thanks()


# Frappe's migrate skips JSON resources when the DB record's `modified` is newer
# than the file (see frappe/modules/import_file.py). UI edits or other apps'
# after_migrate hooks bump that timestamp, so workspace/page/etc. updates we
# ship in upande_webshop silently never reach the site. This helper force-reloads
# every JSON resource the app owns, bypassing the timestamp + hash check.
_RESOURCE_DIRS = (
	"doctype",
	"page",
	"report",
	"print_format",
	"notification",
	"workspace",
	"web_template",
	"web_form",
	"web_page",
	"dashboard",
	"dashboard_chart",
	"number_card",
	"module_onboarding",
	"onboarding_step",
	"form_tour",
	"client_script",
	"server_script",
	"custom",
)


def resync_app_resources():
	"""Force-reload every JSON resource (doctype, workspace, page, ...) that
	upande_webshop ships, ignoring DB-vs-file timestamps. Safe to run repeatedly."""
	module_root = frappe.get_app_path("upande_webshop", "upande_webshop")
	module_name = "Upande Webshop"

	for dt in _RESOURCE_DIRS:
		dt_root = os.path.join(module_root, dt)
		if not os.path.isdir(dt_root):
			continue
		for dn in os.listdir(dt_root):
			doc_dir = os.path.join(dt_root, dn)
			if not os.path.isdir(doc_dir):
				continue
			if not os.path.exists(os.path.join(doc_dir, f"{dn}.json")):
				continue
			try:
				reload_doc(module_name, dt, dn, force=True)
			except Exception:
				frappe.log_error(
					title=f"upande_webshop resync_app_resources: {dt}/{dn}",
					message=frappe.get_traceback(),
				)


# Workspace identity field we standardise on. Frappe requires a Workspace's
# name == title == label, and derives the Desk route from slug(name)
# (frappe/public/js/frappe/views/workspace/workspace.js). We want the admin
# workspace to live at /app/ecommerce (slug of "Ecommerce"), distinct from the
# /webshop storefront URL shortcut inside it. A stale install/UI edit can leave
# title or label out of sync (showing the wrong text) or set parent_page to the
# workspace itself (nesting it under a missing parent, which 404s the icon).
# Normalise all of that here so every install/migrate lands the same working
# state. Safe to run repeatedly.
_WORKSPACE_NAME = "Ecommerce"
# The workspace was originally shipped as "Upande Webshop". Already-installed
# sites still hold a Workspace record under that name; rename it once so the
# route, title, and sidebar all flip to "Ecommerce" without orphaning the row.
_LEGACY_WORKSPACE_NAME = "Upande Webshop"


def normalize_webshop_workspace():
	"""Force the webshop Workspace's name/title/label consistent and clear any
	self-referential parent_page so the Desk icon opens /app/ecommerce."""
	# Migrate the legacy "Upande Webshop" record to "Ecommerce" on existing sites.
	if (
		frappe.db.exists("Workspace", _LEGACY_WORKSPACE_NAME)
		and not frappe.db.exists("Workspace", _WORKSPACE_NAME)
	):
		try:
			frappe.rename_doc(
				"Workspace", _LEGACY_WORKSPACE_NAME, _WORKSPACE_NAME,
				force=True, ignore_permissions=True,
			)
		except Exception:
			frappe.log_error(
				title="upande_webshop rename workspace to Ecommerce",
				message=frappe.get_traceback(),
			)

	if not frappe.db.exists("Workspace", _WORKSPACE_NAME):
		return

	current = frappe.db.get_value(
		"Workspace",
		_WORKSPACE_NAME,
		["title", "label", "parent_page"],
		as_dict=True,
	)
	needs_fix = (
		current.title != _WORKSPACE_NAME
		or current.label != _WORKSPACE_NAME
		or current.parent_page == _WORKSPACE_NAME
	)
	if not needs_fix:
		return

	try:
		# Write the identity fields directly. Going through doc.save() risks
		# Workspace's on_update rename trigger (it collapses name->title when
		# label == name), which would fight us; a db_set keeps name stable.
		frappe.db.set_value(
			"Workspace",
			_WORKSPACE_NAME,
			{"title": _WORKSPACE_NAME, "label": _WORKSPACE_NAME, "parent_page": ""},
			update_modified=False,
		)
		# The sidebar header (Workspace Sidebar) mirrors the title; keep it in step.
		if frappe.db.exists("Workspace Sidebar", _WORKSPACE_NAME):
			frappe.db.set_value(
				"Workspace Sidebar", _WORKSPACE_NAME, "title", _WORKSPACE_NAME,
				update_modified=False,
			)
	except Exception:
		frappe.log_error(
			title="upande_webshop normalize_webshop_workspace",
			message=frappe.get_traceback(),
		)


# The launcher tile on /desk and /apps is a Desktop Icon. We ship one as a
# standard fixture (desktop_icon/upande_webshop.json), but Frappe also
# auto-generates a Desktop Icon from the public Workspace (labelled with the
# workspace name "Ecommerce", linking to the bare "/ecommerce" route that 404s).
# That auto-row shadows our fixture. Mirror upande_ta's approach: upsert our
# External-link icon every install/migrate and drop the stale auto-generated one,
# so the tile opens /app/ecommerce.
#
# IMPORTANT: the icon's label MUST equal the Workspace title ("Ecommerce"). The
# Desk sidebar header and the workspace breadcrumb both resolve their icon (and
# the clickable "back to workspace" crumb) via
# frappe.utils.get_desktop_icon_by_label(sidebar_title), where sidebar_title is
# the active workspace title. A mismatch (e.g. label "Webshop" vs title
# "Ecommerce") means get_desktop_icon_by_label() returns nothing and the
# workspace breadcrumb is silently dropped -- doctypes opened from the workspace
# then show no clickable crumb back to it. Keeping label == "Ecommerce" restores
# the breadcrumb. (frappe/public/js/frappe/views/breadcrumbs.js
# set_workspace_breadcrumb; ui/sidebar/sidebar_header.js.)
_DESKTOP_ICON_NAME = "Ecommerce"
# Drop the pre-rename ("Upande Webshop") and the old brand-labelled ("Webshop")
# icons so only the title-matched "Ecommerce" icon remains.
_STALE_DESKTOP_ICON_NAMES = ("Upande Webshop", "Webshop")


def ensure_desktop_icon():
	"""Create / refresh the launcher Desktop Icon for the webshop workspace."""
	# Drop the auto-generated workspace icon(s) that link to the broken route.
	for stale in _STALE_DESKTOP_ICON_NAMES:
		if frappe.db.exists("Desktop Icon", stale):
			frappe.delete_doc(
				"Desktop Icon", stale,
				ignore_permissions=True, force=True,
			)

	payload = {
		"doctype": "Desktop Icon",
		"name": _DESKTOP_ICON_NAME,
		"label": _DESKTOP_ICON_NAME,
		"app": "upande_webshop",
		"icon_type": "App",
		"link_type": "External",
		"link": "/app/ecommerce",
		"logo_url": "/assets/upande_webshop/images/UpandeLogo.png",
		"force_show": 1,
		"hidden": 0,
		"standard": 1,
	}

	if frappe.db.exists("Desktop Icon", _DESKTOP_ICON_NAME):
		doc = frappe.get_doc("Desktop Icon", _DESKTOP_ICON_NAME)
		for k, v in payload.items():
			if k in ("doctype", "name"):
				continue
			doc.set(k, v)
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc(payload).insert(ignore_permissions=True, ignore_if_duplicate=True)

	frappe.clear_cache()


def remove_legacy_pages():
	"""Delete Page records this app once shipped but no longer does.

	The "Bulk Publish Items" feature moved from a standalone Desk Page into the
	Webshop Settings dialog; its backend now lives in webshop_settings.py. The
	on-disk page was deleted, but the DB record lingers on already-installed
	sites, so drop it explicitly. Safe to run repeatedly."""
	if frappe.db.exists("Page", "bulk-publish-items"):
		frappe.delete_doc("Page", "bulk-publish-items", force=True, ignore_permissions=True)


def _delivery_point_doctype():
	"""Resolve the Delivery Point doctype name for THIS site.

	Named "Delivery Point" (singular) in upande_webshop/upande_kaitet but
	"Delivery Points" (plural) in upande_tambuzi. Some sites have BOTH installed
	(one empty, one populated), so prefer whichever holds records, then whichever
	exists. Point the Link field at that so it resolves and validates. Falls back
	to the singular so a fresh webshop-only site still creates a usable field.
	"""
	existing = [n for n in ("Delivery Point", "Delivery Points") if frappe.db.exists("DocType", n)]
	if not existing:
		return "Delivery Point"
	populated = [n for n in existing if frappe.db.count(n)]
	return (populated or existing)[0]


def add_custom_fields():
	delivery_point_doctype = _delivery_point_doctype()
	custom_fields = {
		"Quotation": [
			{
				"fieldname": "custom_delivery_point",
				"fieldtype": "Link",
				"label": "Delivery Point",
				"options": delivery_point_doctype,
				"insert_after": "shipping_address_name",
			},
			{
				"fieldname": "custom_box_type",
				"fieldtype": "Link",
				"label": "Box Type",
				"options": "Box Type",
				"insert_after": "custom_delivery_point",
			},
		],
		"Item Price": [
			{
				"fieldname": "custom_length",
				"fieldtype": "Link",
				"label": "Stem Length",
				"options": "Stem Length",
				"insert_after": "item_name",
				"description": "Set for non-variant rose items priced per stem length. Variants leave this blank.",
			},
		],
		"Item": [
			{
				"default": 0,
				"depends_on": "published_in_website",
				"fieldname": "published_in_website",
				"fieldtype": "Check",
				"ignore_user_permissions": 1,
				"insert_after": "default_manufacturer_part_no",
				"label": "Published In Website",
				"read_only": 1,
				"no_copy": 1,
			}
		],
		"Item Group": [
			{
				"fieldname": "custom_website_settings",
				"fieldtype": "Section Break",
				"label": "Website Settings",
				"insert_after": "taxes",
			},
			{
				"default": "0",
				"description": "Make Item Group visible in website",
				"fieldname": "show_in_website",
				"fieldtype": "Check",
				"label": "Show in Website",
				"insert_after": "custom_website_settings",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "route",
				"fieldtype": "Data",
				"label": "Route",
				"no_copy": 1,
				"unique": 1,
				"insert_after": "show_in_website",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "website_title",
				"fieldtype": "Data",
				"label": "Title",
				"insert_after": "route",
			},
			{
				"depends_on": "show_in_website",
				"description": "HTML / Banner that will show on the top of product list.",
				"fieldname": "description",
				"fieldtype": "Text Editor",
				"label": "Description",
				"insert_after": "website_title",
			},
			{
				"default": "0",
				"depends_on": "show_in_website",
				"description": "Include Website Items belonging to child Item Groups",
				"fieldname": "include_descendants",
				"fieldtype": "Check",
				"label": "Include Descendants",
				"insert_after": "website_title",
			},
			{
				"fieldname": "column_break_16",
				"fieldtype": "Column Break",
				"insert_after": "include_descendants",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "weightage",
				"fieldtype": "Int",
				"label": "Weightage",
				"insert_after": "column_break_16",
			},
			{
				"depends_on": "show_in_website",
				"description": "Show this slideshow at the top of the page",
				"fieldname": "slideshow",
				"fieldtype": "Link",
				"label": "Slideshow",
				"options": "Website Slideshow",
				"insert_after": "weightage",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "website_specifications",
				"fieldtype": "Table",
				"label": "Website Specifications",
				"options": "Item Website Specification",
				"insert_after": "description",
			},
			{
				"collapsible": 1,
				"depends_on": "show_in_website",
				"fieldname": "website_filters_section",
				"fieldtype": "Section Break",
				"label": "Website Filters",
				"insert_after": "website_specifications",
			},
			{
				"fieldname": "filter_fields",
				"fieldtype": "Table",
				"label": "Item Fields",
				"options": "Website Filter Field",
				"insert_after": "website_filters_section",
			},
			{
				"fieldname": "filter_attributes",
				"fieldtype": "Table",
				"label": "Attributes",
				"options": "Website Attribute",
				"insert_after": "filter_fields",
			},
		],
		"Website Item": [
			{
				"fieldname": "custom_length",
				"fieldtype": "Link",
				"label": "Stem Length",
				"options": "Stem Length",
				"insert_after": "item_name",
				"description": "Stem length variant. Drives storefront stem-length filter.",
			},
			{
				"fieldname": "custom_box_type",
				"fieldtype": "Link",
				"label": "Box Type",
				"options": "Box Type",
				"insert_after": "custom_length",
				"description": "Box type variant. Drives storefront box-type filter.",
			},
		],
		# enable_variants ships as a Custom Field rather than a DocField because
		# editing the Webshop Settings doctype JSON gets reverted on migrate when
		# developer_mode=1 (Frappe re-exports DocType JSON from DB state).
		"Webshop Settings": [
			{
				"default": "1",
				"fieldname": "enable_variants",
				"fieldtype": "Check",
				"label": "Enable Variant Selector",
				"insert_after": "show_stem_length",
			},
		],
	}

	frappe.make_property_setter(
		{
			"doctype": "Item Group",
			"doctype_or_field": "DocType",
			"fieldname": "allow_guest_to_view",
			"property": "allow_guest_to_view",
			"value": 1,
			"property_type": "Check"
		},
		is_system_generated=True,
	)

	return create_custom_fields(custom_fields)


def navbar_add_products_link():
	website_settings = frappe.get_doc("Website Settings")
	if website_settings.top_bar_items:
		return

	website_settings.append(
		"top_bar_items",
		{
			"label": _("Products"),
			"url": "/all-products",
			"right": False,
		},
	)

	website_settings.save()


# Stem Length / Box Type Item Attributes need to exist before variant Items can
# be created against them. The storefront variant selector reads Item Variant
# Attribute rows on the parent Item to render the pill rows on the product page.
_VARIANT_ATTRIBUTES = ("Stem Length", "Box Type")


def ensure_variant_attributes():
	"""Create the Item Attribute records used by the variant selector if missing.
	Does not touch existing attribute values — admins curate those per site."""
	for attr in _VARIANT_ATTRIBUTES:
		if frappe.db.exists("Item Attribute", attr):
			continue
		doc = frappe.new_doc("Item Attribute")
		doc.attribute_name = attr
		doc.numeric_values = 0
		doc.insert(ignore_permissions=True)


# Storefront defaults we want every site to start from. The values here only
# get applied when the field is currently 0/None (falsy) — we never overwrite
# an explicit admin choice. Run on after_install AND after_migrate so that
# sites configured before these defaults existed (e.g. mona, tambuzi) get
# upgraded the next time migrate runs.
_WEBSHOP_SETTINGS_DEFAULTS = {
	"enable_field_filters": 1,
	"enable_variants": 1,
	"show_stem_length": 1,
	"show_box_type": 1,
	"show_bunch": 1,
}


def apply_webshop_settings_defaults():
	"""Fill in Webshop Settings flags that haven't been set yet. Never overwrites
	a value the admin has explicitly turned off."""
	if not frappe.db.exists("DocType", "Webshop Settings"):
		return
	settings = frappe.get_single("Webshop Settings")
	dirty = False
	for fieldname, value in _WEBSHOP_SETTINGS_DEFAULTS.items():
		if not settings.meta.has_field(fieldname):
			continue
		current = settings.get(fieldname)
		if not current:
			settings.set(fieldname, value)
			dirty = True
	if dirty:
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		settings.save()


# Property Setters that we know break the storefront cart flow. The cart
# enforces shipping/billing presence at the cart page (see
# upande_webshop/shopping_cart/cart.py::place_order); making the SO field
# itself `reqd=1` blocks add-to-cart for guests and new customers before they
# even reach checkout. Drop these every migrate so a stray Customize Form
# tweak can't break checkout again.
_PROPERTY_SETTERS_TO_REMOVE = (
	# (doc_type, field_name, property)
	("Sales Order", "shipping_address_name", "reqd"),
)


def cleanup_blocking_property_setters():
	"""Remove Property Setters known to break the storefront checkout flow."""
	for doc_type, field_name, property_ in _PROPERTY_SETTERS_TO_REMOVE:
		rows = frappe.get_all(
			"Property Setter",
			filters={"doc_type": doc_type, "field_name": field_name, "property": property_},
			pluck="name",
		)
		for name in rows:
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)


def say_thanks():
	click.secho("Thank you for installing Upande Webshop!", color="green")
