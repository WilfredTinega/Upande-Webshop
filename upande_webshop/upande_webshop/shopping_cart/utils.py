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
	user_is_customer = is_customer()
	if not user_is_customer:
		return

	if show_cart_count():
		from upande_webshop.upande_webshop.shopping_cart.cart import set_cart_count

		set_cart_count()


def redirect_customer_after_login(response, request):
	"""Called via after_request hook — runs after the full login response is built.
	For Customer role users (System Users), override message='Logged In' to 'No App'
	so login.js uses redirect_to directly instead of routing through the desk router.
	"""
	import json

	is_login = (
		request.method == "POST"
		and (
			request.form.get("cmd") == "login"
			or request.path in ("/login", "/api/method/login")
		)
	)
	if not is_login:
		return

	content_type = response.content_type or ""
	if "json" not in content_type:
		return

	try:
		data = json.loads(response.get_data(as_text=True))
	except Exception:
		return

	message = data.get("message")
	if message not in ("Logged In", "No App"):
		return

	lm = getattr(frappe.local, "login_manager", None)
	user = getattr(lm, "user", None) if lm else None
	if not user or user == "Guest":
		user = frappe.session.user if frappe.session else None

	if not user or user == "Guest":
		return

	# Fresh DB query — frappe.get_roles() returns cached pre-login roles, missing the
	# Customer role just assigned by on_session_creation on first login.
	roles = frappe.db.get_values(
		"Has Role", {"parent": user, "parenttype": "User"}, "role", pluck="role"
	) or frappe.get_roles(user)
	meaningful_roles = [r for r in roles if r not in ("All", "Guest")]

	user_type = frappe.db.get_value("User", user, "user_type")
	is_customer_redirect = (
		meaningful_roles == ["Customer"]
		or (not meaningful_roles and user_type == "Website User")
	)
	if is_customer_redirect:
		# If a guest just stashed a pending cart and we replayed it during
		# on_session_creation, land them on /cart so they see the order.
		target = "/cart" if getattr(frappe.local.flags, "pending_cart_replayed", False) else "/webshop"
		data["message"] = "No App"
		data["redirect_to"] = target
		data["home_page"] = target
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

	from frappe.core.doctype.navbar_settings.navbar_settings import get_app_logo
	import json
	app_logo = get_app_logo() or ""
	context["webshop_app_logo"] = app_logo

	show_bouquets_page = bool(
		frappe.db.get_single_value("Webshop Settings", "show_bouquets_page")
	)
	context["webshop_show_bouquets_page"] = show_bouquets_page

	customer_is_linked = is_customer()
	context["webshop_user_is_customer"] = customer_is_linked

	user_image = frappe.session.user_image if getattr(frappe.session, "user_image", None) else ""
	user_fullname = frappe.session.user_fullname or frappe.session.user or ""
	context["webshop_user_image"] = user_image
	context["webshop_user_fullname"] = user_fullname

	boot_script = (
		f'<script>'
		f'window.webshop_app_logo = {json.dumps(app_logo)};'
		f'window.webshop_show_bouquets_page = {json.dumps(show_bouquets_page)};'
		f'window.webshop_user_is_customer = {json.dumps(customer_is_linked)};'
		f'window.webshop_user_image = {json.dumps(user_image)};'
		f'window.webshop_user_fullname = {json.dumps(user_fullname)};'
		f'</script>'
	)
	context["head_include"] = (context.get("head_include") or "") + boot_script

	if context.get("post_login"):
		context["post_login"] = [
			item for item in context["post_login"]
			if item.get("label") not in ("My Account", _("My Account"))
		]

	if context.get("top_bar_items"):
		context["top_bar_items"] = [
			item for item in context["top_bar_items"]
			if item.get("label") not in ("My Account", _("My Account"))
		]

	context["show_sidebar"] = False
	context["sidebar_items"] = []


def is_customer():
	if frappe.session.user and frappe.session.user != "Guest":
		contact_name = frappe.get_value("Contact", {"email_id": frappe.session.user})
		if contact_name:
			contact = frappe.get_doc("Contact", contact_name)
			for link in contact.links:
				if link.link_doctype == "Customer":
					return True

		return False
