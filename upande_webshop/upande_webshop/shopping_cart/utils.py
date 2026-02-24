# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import frappe
from frappe import _

from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import is_cart_enabled


def show_cart_count():
	if (
		is_cart_enabled()
		and frappe.db.get_value("User", frappe.session.user, "user_type") == "Website User"
	):
		return True

	return False


def set_cart_count(login_manager):
	# since this is run only on hooks login event
	# make sure user is already a customer
	# before trying to set cart count
	user_is_customer = is_customer()
	if not user_is_customer:
		return

	if show_cart_count():
		from upande_webshop.upande_webshop.shopping_cart.cart import set_cart_count

		# set_cart_count will try to fetch existing cart quotation
		# or create one if non existent (and create a customer too)
		# cart count is calculated from this quotation's items
		set_cart_count()


def redirect_customer_after_login(response, request):
	"""Called via after_request hook — runs after the full login response is built.
	For Customer role users (System Users), override message='Logged In' to 'No App'
	so login.js uses redirect_to directly instead of routing through the desk router.
	"""
	import json

	# Only act on login POST requests
	is_login = (
		request.method == "POST"
		and (
			request.form.get("cmd") == "login"
			or request.path in ("/login", "/api/method/login")
		)
	)
	if not is_login:
		return

	# Only act if we have a JSON response with message='Logged In'
	content_type = response.content_type or ""
	if "json" not in content_type:
		return

	try:
		data = json.loads(response.get_data(as_text=True))
	except Exception:
		return

	message = data.get("message")
	# Handle both System Users (Logged In) and Website Users (No App) with Customer role
	if message not in ("Logged In", "No App"):
		return

	lm = getattr(frappe.local, "login_manager", None)
	user = getattr(lm, "user", None) if lm else None
	if not user or user == "Guest":
		user = frappe.session.user if frappe.session else None

	if not user or user == "Guest":
		return

	# Use a fresh DB query to avoid stale cached roles from the current request.
	# On first login, on_session_creation may have just assigned the Customer role
	# but frappe.get_roles() returns the cached pre-login role list.
	roles = frappe.db.get_values(
		"Has Role", {"parent": user, "parenttype": "User"}, "role", pluck="role"
	) or frappe.get_roles(user)
	meaningful_roles = [r for r in roles if r not in ("All", "Guest")]

	# Redirect if Customer role is present and user has no other meaningful roles,
	# OR if user is a Website User with no meaningful roles yet (first-login race condition).
	user_type = frappe.db.get_value("User", user, "user_type")
	is_customer_redirect = (
		meaningful_roles == ["Customer"]
		or (not meaningful_roles and user_type == "Website User")
	)
	if is_customer_redirect:
		data["message"] = "No App"
		data["redirect_to"] = "/upande-webshop"
		data["home_page"] = "/upande-webshop"
		response.set_data(json.dumps(data))


def redirect_after_login(login_manager):
	pass


def redirect_customer_on_session_creation(login_manager):
	pass


def clear_cart_count(login_manager):
	if show_cart_count():
		frappe.local.cookie_manager.delete_cookie("cart_count")


def update_website_context(context):
	cart_enabled = is_cart_enabled()
	context["shopping_cart_enabled"] = cart_enabled

	# Expose app logo URL for the webshop sub-navbar via an inline script in <head>
	from frappe.core.doctype.navbar_settings.navbar_settings import get_app_logo
	import json
	app_logo = get_app_logo() or ""
	context["webshop_app_logo"] = app_logo
	logo_script = f'<script>window.webshop_app_logo = {json.dumps(app_logo)};</script>'
	context["head_include"] = (context.get("head_include") or "") + logo_script

	# Remove "My Account" from the top navbar — it's now in the webshop sub-navbar dropdown
	if context.get("post_login"):
		context["post_login"] = [
			item for item in context["post_login"]
			if item.get("label") not in ("My Account", _("My Account"))
		]

	# Remove "My Account" from top_bar_items if present
	if context.get("top_bar_items"):
		context["top_bar_items"] = [
			item for item in context["top_bar_items"]
			if item.get("label") not in ("My Account", _("My Account"))
		]


def is_customer():
	if frappe.session.user and frappe.session.user != "Guest":
		contact_name = frappe.get_value("Contact", {"email_id": frappe.session.user})
		if contact_name:
			contact = frappe.get_doc("Contact", contact_name)
			for link in contact.links:
				if link.link_doctype == "Customer":
					return True

		return False
