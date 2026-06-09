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


def _redirect(location, code=302):
	"""Raise a werkzeug-style redirect that frappe.app turns into a response.

	frappe.Redirect is only interpreted by the website page renderer, which runs
	*after* before_request — raising it that early bubbles up as a 500. A werkzeug
	HTTPException, by contrast, is converted to its response by frappe.app at the
	init_request level, so a redirect raised here actually works.
	"""
	from werkzeug.exceptions import HTTPException
	from werkzeug.utils import redirect as _wz_redirect

	class RedirectException(HTTPException):
		code = 302

		def get_response(self, environ=None, scope=None):
			return _wz_redirect(location, code=code)

	raise RedirectException()


def redirect_non_desk_users_from_desk():
	"""before_request hook — if a logged-in user without Desk access hits a desk
	route (/app, /desk), send them to /webshop instead of Frappe's bare
	"Not Permitted" page.

	Desk access = user_type 'System User'. Website-only users (Customers) get the
	storefront. Guests are left alone (they should log in normally).
	"""
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		return

	path = (frappe.request.path or "").strip("/") if frappe.request else ""
	# Only intercept the desk app routes.
	if not (path == "app" or path.startswith("app/") or path == "desk" or path.startswith("desk/")):
		return

	# System Users can use the desk — leave them be.
	if frappe.db.get_value("User", user, "user_type") == "System User":
		return

	_redirect("/webshop")


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

	_set_webshop_breadcrumbs(context)

	# Webshop Settings → Full Width: drop the .container wrapper on every
	# webshop-rendered page (not just /webshop). The desk's navbar toggle does
	# this globally via body.full-width; this is the website-side equivalent.
	meta = frappe.get_meta("Webshop Settings")
	full_width_setting = 0
	if meta.has_field("full_width") and frappe.db.get_single_value(
		"Webshop Settings", "full_width"
	):
		context["full_width"] = 1
		full_width_setting = 1

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

	user_image = ""
	user_fullname = frappe.session.user_fullname or frappe.session.user or ""
	user_theme = "light"
	if frappe.session.user and frappe.session.user != "Guest":
		# Read the live User image so a freshly-uploaded photo shows immediately,
		# rather than the (possibly stale) value cached on the session.
		user_image = frappe.db.get_value("User", frappe.session.user, "user_image") or ""
		stored_theme = (
			frappe.db.get_value("User", frappe.session.user, "desk_theme") or ""
		).lower()
		# Only light/dark are offered in the webshop; treat anything else
		# (e.g. a legacy "Automatic" desk_theme) as light.
		if stored_theme == "dark":
			user_theme = "dark"
	context["webshop_user_image"] = user_image
	context["webshop_user_fullname"] = user_fullname

	# Apply the user's theme synchronously in <head> so dark mode doesn't flash
	# light first. Mirrors what frappe.ui.set_theme does on /app, but executed
	# at parse time instead of after DOMContentLoaded.
	theme_init = (
		'(function(){'
		'try{'
		f'var defaultMode = {json.dumps(user_theme)};'
		'var stored = null;'
		'try { stored = localStorage.getItem("desk_theme_mode"); } catch (e) {}'
		'var mode = (stored === "dark" || stored === "light") ? stored : defaultMode;'
		'document.documentElement.setAttribute("data-theme-mode", mode);'
		'document.documentElement.setAttribute("data-theme", mode);'
		'} catch (e) {}'
		'})();'
	)
	boot_script = (
		f'<script>'
		f'{theme_init}'
		f'window.webshop_app_logo = {json.dumps(app_logo)};'
		f'window.webshop_show_bouquets_page = {json.dumps(show_bouquets_page)};'
		f'window.webshop_user_is_customer = {json.dumps(customer_is_linked)};'
		f'window.webshop_user_image = {json.dumps(user_image)};'
		f'window.webshop_user_fullname = {json.dumps(user_fullname)};'
		f'window.webshop_full_width_default = {json.dumps(bool(full_width_setting))};'
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


# The account-menu pages, keyed by their (leading-slash-stripped) route. Each
# value is the breadcrumb label shown for that page. Mirrors the dropdown in
# shopping_cart.js so the trail matches the nav. /webshop is the webshop "home"
# and is the "Home" root crumb on every other page (and gets no breadcrumb
# itself).
_WEBSHOP_BREADCRUMB_PAGES = {
	"orders": "Orders",
	"invoices": "Invoices",
	"cart": "Cart",
	"bouquet": "Bouquet",
	"wishlist": "Wishlist",
	"shipments": "Shipments",
	"issues": "Issues",
	"contact": "Contact",
	"webshop-setting": "Setting",
}


def _set_webshop_breadcrumbs(context):
	"""Render `Products / <Page>` breadcrumbs on the account-menu pages.

	The standard breadcrumbs.html only renders when `parents` is set on the
	context. The webshop landing (/webshop) and the doctype list pages
	(/orders, /invoices, …) don't set it, so no trail shows. Detail pages
	(e.g. /orders/SO-0001) already populate their own `parents` via
	website_route_rules — we only touch exact top-level routes here and never
	clobber an existing trail.
	"""
	request = getattr(frappe.local, "request", None)
	if not request:
		return

	route = (request.path or "").strip("/")
	label = _WEBSHOP_BREADCRUMB_PAGES.get(route)

	# Generic Frappe doctype portals render their LIST at `<route>/list` (e.g.
	# /issues → /issues/list, /orders → /orders/list), not at the bare route. The
	# exact-route map misses those, so the list view showed no breadcrumb. If the
	# path is `<known>/list`, resolve it to the same label. Detail pages
	# (`<route>/<name>`) and the "new" form (`<route>/new`) set their own parents
	# via website_route_rules, so we only special-case the `/list` suffix here and
	# never touch other sub-routes.
	if not label and route.endswith("/list"):
		label = _WEBSHOP_BREADCRUMB_PAGES.get(route[: -len("/list")])

	if not label:
		return

	# Frappe's standard portal list contexts (Sales Order → /orders, Sales
	# Invoice → /invoices, Shipment → /shipments, Issue → /issues) ship with
	# `no_breadcrumbs: True`, and breadcrumbs.html bails on that flag before it
	# ever looks at `parents`. This hook runs in post_process_context — after
	# the doctype's get_list_context — so clearing it here wins.
	context["no_breadcrumbs"] = False
	context["parents"] = [{"label": _("Home"), "route": "/webshop"}]
	context["title"] = _(label)


def is_customer():
	if frappe.session.user and frappe.session.user != "Guest":
		contact_name = frappe.get_value("Contact", {"email_id": frappe.session.user})
		if contact_name:
			contact = frappe.get_doc("Contact", contact_name)
			for link in contact.links:
				if link.link_doctype == "Customer":
					return True

		return False
