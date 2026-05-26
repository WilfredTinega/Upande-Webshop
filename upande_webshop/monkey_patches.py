from urllib.parse import urlencode

import frappe


_PATCHED = False


def apply():
	global _PATCHED
	if _PATCHED:
		return

	_patch_workspace_sidebar_none()
	_patch_desk_get_context()
	_patch_virtual_child_table_load()

	_PATCHED = True


def _patch_workspace_sidebar_none():
	from frappe.desk import desktop

	original = desktop.get_workspace_sidebar_items

	def safe_get_workspace_sidebar_items():
		result = original()
		pages = result.get("pages") or []
		result["pages"] = [p for p in pages if p is not None]
		return result

	desktop.get_workspace_sidebar_items = safe_get_workspace_sidebar_items


def _patch_desk_get_context():
	from frappe.www import desk as desk_module

	original_get_context = desk_module.get_context

	def safe_get_context(context):
		if frappe.session.user == "Guest" or _is_customer_only(frappe.session.user):
			frappe.local.response["type"] = "redirect"
			frappe.local.response["location"] = "/webshop"
			raise frappe.Redirect

		try:
			return original_get_context(context)
		except frappe.SessionBootFailed:
			user_type = getattr(getattr(frappe.session, "data", None), "user_type", None)
			if user_type == "Website User":
				path = getattr(getattr(frappe.local, "request", None), "path", "/app")
				frappe.local.response["type"] = "redirect"
				frappe.local.response["location"] = f"/login?{urlencode({'redirect-to': path})}"
				raise frappe.Redirect
			raise

	desk_module.get_context = safe_get_context


def _patch_virtual_child_table_load():
	from frappe.model import document as document_module

	original = document_module.Document._load_child_table_from_db

	def safe_load_child_table_from_db(self, fieldname, child_doctype):
		try:
			meta = frappe.get_meta(child_doctype)
			if getattr(meta, "is_virtual", False):
				return []
			if not frappe.db.has_column(child_doctype, "parent"):
				return []
		except Exception:
			pass
		return original(self, fieldname, child_doctype)

	document_module.Document._load_child_table_from_db = safe_load_child_table_from_db


def _is_customer_only(user):
	if user in ("Guest", "Administrator"):
		return False
	roles = set(frappe.get_roles(user))
	if "Customer" not in roles:
		return False
	desk_roles = roles - {"Customer", "Guest", "All", "Desk User"}
	return not desk_roles
