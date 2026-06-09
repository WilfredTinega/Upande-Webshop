from . import __version__ as _version

app_name = "upande_webshop"
app_title = "Upande Webshop"
app_publisher = "Upande LTD"
app_description = "Upande Webshop"
app_email = "wilfred@upande.com"
app_license = "mit"
app_version = _version

# Apps
# ------------------

required_apps = ["erpnext","payments"]

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "upande_webshop",
		"logo": "/assets/upande_webshop/images/UpandeLogo.png",
		"title": "Webshop",
		"route": "/app/upande-webshop"
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/upande_webshop/css/upande_webshop.css"
# app_include_js = "/assets/upande_webshop/js/upande_webshop.js"

# include js, css files in header of web template
web_include_css = "webshop-web.bundle.css"
web_include_js = "web.bundle.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "upande_webshop/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Item": "public/js/override/item.js",
    "Homepage": "public/js/override/homepage.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "upande_webshop/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
website_generators = ["Website Item", "Item Group"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
jinja = {
	"methods": [
		"upande_webshop.upande_webshop.doctype.stem_length_bin.stem_length_bin.get_stock_by_length",
	],
}

# Installation
# ------------

before_install = "upande_webshop.setup.stem_length_guard.guard"
after_install = "upande_webshop.setup.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "upande_webshop.uninstall.before_uninstall"
# after_uninstall = "upande_webshop.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "upande_webshop.utils.before_app_install"
# after_app_install = "upande_webshop.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "upande_webshop.utils.before_app_uninstall"
# after_app_uninstall = "upande_webshop.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "upande_webshop.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

has_website_permission = {
    "Website Item": "upande_webshop.upande_webshop.doctype.website_item.website_item.has_website_permission_for_website_item",
    "Item Group": "upande_webshop.upande_webshop.doctype.website_item.website_item.has_website_permission_for_item_group"
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    "Item": {
        "on_update": [
            "upande_webshop.upande_webshop.crud_events.item.update_website_item.execute",
            "upande_webshop.upande_webshop.crud_events.item.invalidate_item_variants_cache.execute",
            "upande_webshop.upande_webshop.crud_events.item.ensure_per_length_item_prices.execute",
        ],
        "before_rename": [
            "upande_webshop.upande_webshop.crud_events.item.validate_duplicate_website_item.execute",
        ],
        "after_rename": [
            "upande_webshop.upande_webshop.crud_events.item.invalidate_item_variants_cache.execute",
        ],
        # "onload" hook removed because:
        # 1. You have an override class for Item that can handle onload functionality
        # 2. The module path was incorrect (utils/item.py doesn't exist)
        # 3. If onload functionality is needed, add it to the WebshopItem class in override_doctype/item.py
    },
    "Sales Taxes and Charges Template": {
        "on_update": [
            "upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings.validate_cart_settings",
        ],
    },
    "Tax Rule": {
        "validate": [
            "upande_webshop.upande_webshop.crud_events.tax_rule.validate_use_for_cart.execute",
        ],
    },
    "Stock Ledger Entry": {
        "on_submit": [
            "upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices.on_stock_ledger_entry_change",
        ],
        "on_cancel": [
            "upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices.on_stock_ledger_entry_change",
        ],
    },
    "Stock Entry": {
        "before_save": [
            "upande_webshop.upande_webshop.crud_events.stock.stem_length_carry.stock_entry_before_save",
        ],
        "on_submit": [
            "upande_webshop.upande_webshop.crud_events.stock.stem_length_carry.stock_entry_on_submit",
            "upande_webshop.server_scripts.update_stem_length_bin.on_stock_entry_submit",
        ],
        "on_cancel": [
            "upande_webshop.server_scripts.update_stem_length_bin.on_stock_entry_cancel",
        ],
    },
    "Sales Order": {
        "on_submit": [
            "upande_webshop.server_scripts.update_stem_length_bin.on_sales_order_submit",
        ],
        "on_cancel": [
            "upande_webshop.server_scripts.update_stem_length_bin.on_sales_order_cancel",
        ],
    },
}

# Override Methods
# ------------------------------
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "upande_webshop.task.get_dashboard_data"
# }

override_doctype_class = {
    "Payment Request": "upande_webshop.upande_webshop.doctype.override_doctype.payment_request.PaymentRequest",
    "Item Group": "upande_webshop.upande_webshop.doctype.override_doctype.item_group.WebshopItemGroup",
    "Item": "upande_webshop.upande_webshop.doctype.override_doctype.item.WebshopItem",
    "Item Price": "upande_webshop.upande_webshop.doctype.override_doctype.item_price.WebshopItemPrice",
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
before_request = [
    "upande_webshop.upande_webshop.shopping_cart.utils.redirect_non_desk_users_from_desk",
]
after_request = ["upande_webshop.upande_webshop.shopping_cart.utils.redirect_customer_after_login"]

# If another app already owns the `Stem Length` doctype on this site, hide our
# on-disk copy before Frappe's doctype sync runs — otherwise migrate would
# overwrite the existing record with our version.
before_migrate = [
	"upande_webshop.setup.stem_length_guard.guard",
]

# after_migrate runs in this order:
#   0. remove_legacy_pages — drop DB records for Pages we no longer ship
#      (e.g. the old bulk-publish-items Desk page).
#   1. resync_app_resources — force-reloads every JSON resource we ship
#      (workspace, doctypes, …). Frappe's normal sync
#      skips files whose `modified` is older than the DB record, so once the
#      workspace is edited in the UI new shortcuts in the JSON never reach the
#      site. We bypass that with reload_doc(..., force=True).
#   1b. normalize_webshop_workspace — runs right after the resync so the
#      reloaded JSON can't leave name/title/label out of sync. Forces them all
#      to "Upande Webshop" and clears any self-referential parent_page, so the
#      Desk icon always opens /app/upande-webshop instead of a 404.
#   2. add_custom_fields — re-applies custom field definitions (Item Group,
#      Item Price, Website Item, Quotation Item, …) so additions show up
#      without reinstall.
#   3. ensure_variant_attributes — create Stem Length / Box Type Item Attribute
#      records if missing, so variant Items can be built against them.
#   4. apply_webshop_settings_defaults — set storefront flags
#      (enable_field_filters, enable_variants, show_stem_length, show_box_type,
#      show_bunch) only where currently 0/null, never overwriting an explicit
#      admin choice.
#   5. cleanup_blocking_property_setters — remove Property Setters known to
#      break checkout (e.g. Sales Order.shipping_address_name reqd=1, which
#      blocks add-to-cart for guests before they reach the cart-page address
#      step).
#   6. Floriday + Biflorica resync_scheduled_jobs — restore Scheduled Job Type
#      rows that Frappe's scheduler sync prunes (user-configured per Settings
#      doc, not declared in scheduler_events).
after_migrate = [
	"upande_webshop.setup.install.remove_legacy_pages",
	"upande_webshop.setup.install.resync_app_resources",
	"upande_webshop.setup.install.normalize_webshop_workspace",
	"upande_webshop.setup.install.ensure_desktop_icon",
	"upande_webshop.setup.install.add_custom_fields",
	"upande_webshop.setup.install.ensure_variant_attributes",
	"upande_webshop.setup.install.apply_webshop_settings_defaults",
	"upande_webshop.setup.install.cleanup_blocking_property_setters",
	"upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.resync_scheduled_jobs",
	"upande_webshop.upande_webshop.doctype.biflorica_setting.biflorica_setting.resync_scheduled_jobs",
]

scheduler_events = {
	"cron": {
		"0 0 * * *": [
			"upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices._sync_webshop_item_prices",
		],
	},
}

# /webshop-item-prices is not a public storefront page — it's an admin doctype.
# Bounce storefront visitors to the Desk list view (Frappe core then redirects /app -> /desk).
website_redirects = [
	{"source": "/webshop-item-prices", "target": "/app/webshop-item-prices"},
]

# Job Events
# ----------
# before_job = ["upande_webshop.utils.before_job"]
# after_job = ["upande_webshop.utils.after_job"]

on_logout = "upande_webshop.upande_webshop.shopping_cart.utils.clear_cart_count"
on_login = "upande_webshop.upande_webshop.shopping_cart.utils.redirect_after_login"
on_session_creation = [
    "upande_webshop.upande_webshop.utils.portal.update_debtors_account",
    "upande_webshop.upande_webshop.shopping_cart.utils.set_cart_count",
    "upande_webshop.upande_webshop.shopping_cart.utils.redirect_customer_on_session_creation",
    "upande_webshop.upande_webshop.shopping_cart.pending_cart.replay_for_user",
]
update_website_context = [
    "upande_webshop.upande_webshop.shopping_cart.utils.update_website_context",
]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"upande_webshop.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# fixtures = [
# 	{"dt": "Web Page", "filters": []},
# 	{"dt": "Website Sidebar", "filters": []},
# 	{"dt": "Website Slideshow", "filters": []},
# 	{"dt": "Website Settings", "filters": []},
# 	{"dt": "Portal Settings", "filters": []},
# 	{"dt": "Website Script", "filters": []},
# ]