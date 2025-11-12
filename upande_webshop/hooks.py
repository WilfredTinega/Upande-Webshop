app_name = "upande_webshop"
app_title = "Upande Webshop"
app_publisher = "Upande LTD"
app_description = "Upande Webshop"
app_email = "info@upande.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "upande_webshop",
# 		"logo": "/assets/upande_webshop/logo.png",
# 		"title": "Upande Webshop",
# 		"route": "/upande_webshop",
# 		"has_permission": "upande_webshop.api.permission.has_app_permission"
# 	}
# ]

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

fixtures = [
	{
		"dt": "DocType",
		"filters": [
			[
				"name",
				"in",
				[
                    "Web Page",
                    "Web Form",
                    "Website Sidebar",
                    "Website Slideshow",
                    "Website Route Meta",
                    "Website Settings",
                    "Website Theme",
                    "Website Script",
                    "Portal Settings",
				],
			]
		],
	},
	# {
	# 	"dt": "Server Script",
	# 	"filters": [
	# 		[
	# 			"name",
	# 			"in",
	# 			[
	# 				"Auto-Promotion Script: Unskilled → Semi-skilled",
	# 				"Calculate Monthly Earned Leave",
	# 				"Holiday List Update",
	# 				"Preview 1/3 rule",
	# 				"Bulk Salary Structure Assignment Restriction",
	# 				"Salary Structure Assignment Restriction",
	# 				"Salary Structure Restriction",
	# 				"Payslip Restriction",
	# 				"Stock Entry Script",
	# 				"Stock Entry After Save",
	# 				"Scan Timestamp",
	# 				"Harvest Stock Entry",
	# 				"Automate Rejects Material Issue",
	# 				"Create Box Labels",
	# 				"Update Grading Forecast Tracker",
	# 				"Update Sales Order ID on Save",
	# 				"Update Forecast Tracker (During Grading)",
	# 				"Update Tracker (During Grading Cancel)",
	# 				"Update Tracker (Grading Forecast)",
	# 				"Forecast Entry",
	# 				"Allow Packing Of Returned Bunches",
	# 				"FPL Block New Version",
	# 				"Lock Dates On Submit of Sales Invoice",
	# 				"Validate unique bucket ID",
	# 				"Set Bucket Id Status",
	# 				"Create delivery trip",
	# 				"Request Concession",
	# 				"Filtering based on Role",
	# 				"Work Order, Event; on_submit",
	# 				"Material Issue Notification",
	# 				"Start Trip Transfer",
	# 				"End Trip Transfer",
	# 				"Gps",
	# 				"Repack",
	# 				"Create Invoice From Dispatch Form",
	# 				"Create Field Reject Entry",
	# 				"Vehicle Location Update",
	# 				"Create Sales Invoice",
	# 				"Production Forecast Analysis Generation",
	# 				"Payroll Access Restriction",
	# 				"Receive Goods Returned",
	# 				"CFU AM CHECKLIST Assign",
	# 				"CSU AM Checksheet → Support Issue",
	# 				"Packhouse AM Checklist → Support Issue",
	# 				"Tractor Inspection Checksheet → Support Issue",
	# 				"Truck Inspection Checksheet",
	# 				"Reefer Truck CLIT → Support Issue",
	# 				"Total in asset Repair",
	# 				"Calculate total",
	# 				"Test Updated Material Request Server Script",
	# 				"Delivery Note Stock Removal",
	# 				"Create Rejects Stock Entry",
	# 				"Create Yoghurt Sales Invoice",
	# 				"Add Length to Stock Ledger",
	# 				"Biometric Verification",
	# 				"Cheque Ref Number Autogenerates",
	# 				"Auto Assign for Issue and ToDo",
	# 				"Lead Notification",
	# 				"Craete Sales Invoice",
	# 				"Setting Company on Webform Submission",
	# 				"Shipping and Billing Address Creation",
    #       "Cows Calculation Validation",
    #       "Biometric Submission Notification",
    #       "Enforce Ordered Stems Non-zero",
    #       "Create Standing Order",
    #       "Standing Order Cron Job",
    #       "Remove Old Shelf Items",
	# 				"Generate Box Labels for Std Roses",
    #       "Create CAR"
	# 				"Get sales order from floriday"
	# 				"Cows Calculation Validation",
	# 				"Biometric Submission Notification",
	# 				"Enforce Ordered Stems Non-zero",
	# 				"Create Standing Order",
	# 				"Standing Order Cron Job",
	# 				"Remove Old Shelf Items",
	# 				"Generate Box Labels for Std Roses",
    #       "Daily Attendance Report",
    #       "Get sales order from floriday",
    #       "Poultry Transactions",
    #       "Dairy Transactions",
    #       "Payroll Transactions",
    #       "HR Transactions",
    #       "Stores Transactions",
    #       "Sales Transactions",
    #       "Asset Maintenance",
    #       "Agriculture Transactions",
    #       "Spray Roses : Order to Invoice",
    #       "CRM Transactions",
    #       "Asset Management",
    #       "Floriday",
    #       "Procurement Transactions",
    #       "Batch Creation In Floriday",
    #       "Sales Accounting",
    #       "Purchasing Accounting",
    #       "Biflorica Access Token",
    #       "Create Biflorica Offers",
    #       "Floriday Customer Offers",
    #       "Standard Roses: Order to Invoice",
    #       "Check the Update Price Approver",
    #       "Floriday Supplyline"
	# 			],
	# 		]
	# 	],
	# },
	# {
	# 	"dt": "Client Script",
	# 	"filters": [
	# 		[
	# 			"name",
	# 			"in",
	# 			[
	# 				"Salary Section Restriction",
	# 				"Years of Service Auto-Populate",
	# 				"Weekly offs",
	# 				"Auto-populate Base Pay",
	# 				"Leave Balance After Auto-Calculation",
	# 				"Leave Encashment Amount Auto-Calculation",
	# 				"Qr Code gen",
	# 				"Close Box Button",
	# 				"Scan Via Honeywell",
	# 				"Scan Data Field Listener",
	# 				"Scan QR Button",
	# 				"Populate Number of Items",
	# 				"Grading Stock Entry",
	# 				"Archive Employee",
	# 				"Transfer Grading Stock",
	# 				"Generate Bucket Codes",
	# 				"Harvest Scan",
	# 				"New Form After Save",
	# 				"Remove Read Only on Field",
	# 				"Ensure Bucket Is Scanned On Save",
	# 				"Hide Filter Button 2",
	# 				"Hide Filter Button (Bucket QR Code List) 2",
	# 				"Ensure Uppercase in Bay Field",
	# 				"Grading Traceability Symbols",
	# 				"SO target warehouse Population",
	# 				"Set List View Limit to 500(GRADER)",
	# 				"Set List View Limit to 500(BUNCH)",
	# 				"Set List View Limit to 500(BUCKET)",
	# 				"Restrict Bay to Alphabets",
	# 				"Autopopulate Sales Order ID in CPL",
	# 				"Ensure Items are in SO Before Manually Adding (FPL)",
	# 				"Authorise Under Pack Button in FPL",
	# 				"Autopopulate Sales Order ID in FPL",
	# 				"Amount Calc Based on IGP",
	# 				"Under Pack Cancel Button",
	# 				"Combined Script",
	# 				"Request Concession Button",
	# 				"Request Concession 2",
	# 				"Employee Filtering",
	# 				"Yoghurt Manufacturing Stock Entry",
	# 				"Work Order",
	# 				"Geo",
	# 				"Hide Fields in Work Order",
	# 				"Loss Mandatory",
	# 				"Stock Entry Type Automation",
	# 				"Default Source and Target Warehouse",
	# 				"Allow Valuation Rate",
	# 				"Start Job Script",
	# 				"Fetch Farm and Business Unit",
	# 				"Update Source Warehouse",
	# 				"Trip Button",
	# 				"Populate WIP and Target Warehoise in Work Order",
	# 				"Auto-fetch Company from BOM in Work Order",
	# 				"Auto-fetch Company",
	# 				"Auto-set Company on BOM based on Item's Warehouse",
	# 				"Repack Button",
	# 				"Create Delivery Note Button",
	# 				"Autopopulate Farm and Business Unit (SO)",
	# 				"Custom Workflow Approval (Delivery note)",
	# 				"Fetch SO Details",
	# 				"Yoghurt Delivery Workflow",
	# 				"Autopopulate Week Number",
	# 				"Populate Available Qty Field" "CSU AM Checksheet",
	# 				"Tractor Inspection Checksheet",
	# 				"Truck Inspection Checksheet",
	# 				"Packhouse Equipment and Machine AM Checklist",
	# 				"CFU Inspection Checksheet",
	# 				"CSU AM Checksheet",
	# 				"Tractor Inspection Checksheet" "Refresh Items Table",
	# 				"Reason for scrapping",
	# 				"Material Request button",
	# 				"checksheets button",
	# 				"Bed Sampling Script",
	# 				"Mapping Sections to Greenhouse",
	# 				"Persist Variety, Farm and Greenhouse",
	# 				"Variety Select Dialog",
	# 				"Set Source and Target Warehouse",
	# 				"Rate based on Length",
	# 				"Visibility of length and packrate fields",
	# 				"Dynamic Spec Items Population",
	# 				"Calculate Zerobending and Production Dates",
	# 				"Agriculture Production Plan Creation",
	# 				"Agriculture Tasks Filter",
	# 				"Create Tracking Form from Grower Production Plan",
	# 				"Updated Production Tracking Form for Manual Creation" "Get-Items-From-button(SI)",
	# 				"Hide Extra Quotation Options",
	# 				"Populate Company Field on Lead Doctype",
	# 				"Autofill Company",
	# 				"Initiate Shopify Stock Transfer",
	# 				"Autopopulate Item Fields",
	# 				"Copy From Last Transfer Button",
	# 				"Dynamic Naming of Crop Cycles",
	# 				"Reason for scrapping" "Sampling Area and Variety Area Population",
	# 				"Reverse Transfer Button",
	# 				"Find Variety in Its Shelf",
	# 				"Set Quotation Price List",
	# 				"OPL Connections to SO",
	# 				"Consolidate Sales Invoice",
	# 				"Update Total Boxes",
	# 				"Auto Populate Lead Status",
	# 				"Load Yoghurt Invoice Form",
	# 				"Biometric Verification Button",
	# 				"Cheque Ref Number Autogenerate",
	# 				"Autopopulate Spec Details",
	# 				"Fill Qualified By field when Lead Converted",
	# 				"Change Organization Name to Upper Case",
	# 				"Set Business Unit on Lead",
	# 				"match country to territory",
	# 				"Autopopulate Price List",
	# 				"Autopopulate Price List on Customer",
	# 				"Dynamically Populate Plan Type Child Table",
	# 				"OPL dialog",
	# 				"Quotation Price Calculation",
	# 				"Karen Roses Quotation Print Format",
	# 				"Set Business Unit on Lead",
	# 				"Filter City list",
	# 				"Map Mobile No to WhatsApp Field",
	# 				"Autopopulate Currency from Price list",
	# 				"Display Rose Related fields",
	# 				"autopopulate price",
	# 				"Show Shelf and Qty Shelved",
	# 				"Show Pick List",
	# 				"Update Line Name",
    #       "Autopopulate Truck Details",
    #       "Cows Feeds Calculation",
    #       "Mixed Box Dialog",
	# 				"Prevent selection of previous dates",
    #       "Consignee Select Dialog", 
	# 				"Persist Farm",
    #       "Shipping Agent Permission",
    #       "Filter Cost Center",
    #       "PO Creation Restriction",
    #       "TW Payment Calculation",
	# 				"Autopopulate payments",
	# 				"autopopulate actual cost",
	# 				"Auto-populate tasks when Task Work Plan is selected",
	# 				"Create Task Assignment",
	# 				"Task Work Request Automation",
	# 				"Autopopulate Hours in Bulk Overtime Request",
	# 				"Additional Salary Button",
	# 				"Autopopulate claim from bulk ref",
	# 				"Employee Table on TW Form",
	# 				"Sum of Task Workers",
	# 				"Bulk OT Requisition",
	# 				"Filter for task workers",
	# 				"Total Pay for Task Workers", "Update Forecastable Items"
	# 			],
	# 		]
	# 	],
	# },
	# {
	# 	"dt": "Print Format",
	# 	"filters": [
	# 		[
	# 			"name",
	# 			"in",
	# 			[
	# 				"Salary Slip",
	# 				"QR Code Only",
	# 				"Box Label",
	# 				"Harvest Label",
	# 				"Grader QR Print Format",
	# 				"Bunch QR Code",
	# 				"Trial Bunch Print Format",
	# 				"Grader QR Print format 2",
	# 				"Harvest Label 2",
	# 				"Box Label 2",
	# 				"Pick List - Kaitet",
	# 				"Yoghurt Commercial Invoice",
	# 				"Shelf QR Code",
	# 				"fpl 2",
	# 				"Karen Roses Quotation",
	# 			],
	# 		]
	# 	],
	# },
	# {
	# 	"dt": "Report",
	# 	"filters": [
	# 		[
	# 			"name",
	# 			"in",
	# 			[
	# 				"Harvest and Field Rejects Report",
	# 				"Harvest by Item Group",
	# 				"Harvest Pick Report",
	# 				"Harvest Received Report",
	# 				"Harvest Summary by Time of Day",
	# 				"Harvest Totals by Variety",
	# 				"Available for Sale Stock Balance",
	# 				"Stock Sheet_Available for Sale",
	# 				"Stock Sheet_Ungraded",
	# 				"Ungraded Stock Balance",
	# 				"Field Rejects Report",
	# 				"Overall Discards and Rejects Report",
	# 				"Weekly Discards/Rejects Report",
	# 				"Harvesting Stock Entries",
	# 				"Grading Stock Entries",
	# 				"Receiving Stock Entries",
	# 				"Packhouse Discards or Rejects Details",
	# 				"Packhouse Discards or Rejects Report",
	# 				"Sales Invoiced Report",
	# 				"Sales Invoice Details",
	# 				"Sales Order Report",
	# 				"Sales per Variety Report (SO)",
	# 				"Daily Sales Ops Summary",
	# 				"Bed Sampling Summary",
	# 				"Bed Sampling Report",
	# 				"Forecast Report",
	# 				"Consolidated Forecast Report",
	# 				"Yield Budget Report",
	# 				"Stock Balance by Stem Length",
	# 				"Supplier Ledger Report",
	# 				"Shelving Report",
	# 			],
	# 		]
	# 	],
	# },

]
