app_name = "upande_webshop"
app_title = "Upande Webshop"
app_publisher = "Upande LTD"
app_description = "Upande Webshop"
app_email = "wilfred@upande.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext","payments","webshop"]

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "upande_webshop",
		"logo": "/assets/upande_webshop/images/UpandeLogo.png",
		"title": "Upande Webshop",
		"route": "/webshop",
		# "has_permission": "upande_webshop.api.permission.has_app_permission"
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/upande_webshop/css/upande_webshop.css"
# app_include_js = "/assets/upande_webshop/js/upande_webshop.js"

# include js, css files in header of web template
# web_include_css = "/assets/upande_webshop/css/upande_webshop.css"
# web_include_js = "/assets/upande_webshop/js/upande_webshop.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "upande_webshop/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
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
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "upande_webshop.utils.jinja_methods",
# 	"filters": "upande_webshop.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "upande_webshop.install.before_install"
# after_install = "upande_webshop.install.after_install"

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

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"upande_webshop.tasks.all"
# 	],
# 	"daily": [
# 		"upande_webshop.tasks.daily"
# 	],
# 	"hourly": [
# 		"upande_webshop.tasks.hourly"
# 	],
# 	"weekly": [
# 		"upande_webshop.tasks.weekly"
# 	],
# 	"monthly": [
# 		"upande_webshop.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "upande_webshop.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "upande_webshop.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "upande_webshop.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "upande_webshop.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["upande_webshop.utils.before_request"]
# after_request = ["upande_webshop.utils.after_request"]

# Job Events
# ----------
# before_job = ["upande_webshop.utils.before_job"]
# after_job = ["upande_webshop.utils.after_job"]

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


fixtures = [
	{"dt": "Web Page", "filters": []},
	{"dt": "Website Sidebar", "filters": []},
	{"dt": "Website Slideshow", "filters": []},
	{"dt": "Website Settings", "filters": []},
	{"dt": "Portal Settings", "filters": []},
	{"dt": "Website Script", "filters": []},
	
]
