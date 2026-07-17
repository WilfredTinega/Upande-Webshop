"""Pending-cart stash for guests.

When a guest clicks Add to Cart, the client posts the cart entries here. We
stash them in cache keyed by an opaque token (also written as an HTTP-only
cookie). After login, replay_for_user() reads the token, replays each entry
through the normal update_cart path, and clears the stash. The login redirect
hook then sends the user to /cart instead of /webshop.
"""

import json
import secrets

import frappe
from frappe import _


COOKIE_NAME = "webshop_pending_cart"
CACHE_KEY = "webshop_pending_cart"
TTL_SECONDS = 60 * 30  # 30 min — long enough for a user to find their login details


@frappe.whitelist(allow_guest=True, methods=["POST"])
def stash(entries):
	"""Save guest cart entries to cache, set the lookup cookie, return ok.

	entries: list of dicts shaped like update_cart kwargs (item_code, qty, uom,
	additional_notes, custom_length, custom_box_type).
	"""
	if isinstance(entries, str):
		entries = json.loads(entries)

	if not isinstance(entries, list) or not entries:
		frappe.throw(_("No cart entries to save"))

	cleaned = []
	for raw in entries:
		if not isinstance(raw, dict):
			continue
		item_code = raw.get("item_code")
		qty = raw.get("qty")
		if not item_code or not qty:
			continue
		cleaned.append({
			"item_code": str(item_code),
			"qty": float(qty),
			"uom": raw.get("uom") or None,
			"additional_notes": raw.get("additional_notes") or None,
			"custom_length": raw.get("custom_length") or None,
			"custom_box_type": raw.get("custom_box_type") or None,
		})

	if not cleaned:
		frappe.throw(_("No valid cart entries to save"))

	token = secrets.token_urlsafe(24)
	frappe.cache.set_value(f"{CACHE_KEY}:{token}", cleaned, expires_in_sec=TTL_SECONDS)
	frappe.local.cookie_manager.set_cookie(COOKIE_NAME, token, max_age=TTL_SECONDS, httponly=True)
	return {"ok": True}


def _read_token():
	try:
		return (frappe.request.cookies or {}).get(COOKIE_NAME) if frappe.request else None
	except Exception:
		return None


def replay_for_user(login_manager=None):
	"""on_session_creation hook — if a pending-cart cookie is present, replay it
	into the freshly logged-in user's cart and flag the response for /cart redirect.
	"""
	token = _read_token()
	if not token:
		return
	_replay_token(token)


def _replay_token(token):
	cache_key = f"{CACHE_KEY}:{token}"
	entries = frappe.cache.get_value(cache_key)
	# One-shot: clear immediately so a failed replay doesn't loop on next login.
	frappe.cache.delete_value(cache_key)
	try:
		frappe.local.cookie_manager.delete_cookie(COOKIE_NAME)
	except Exception:
		pass

	if not entries:
		return

	# Only Customer / Website User flows should replay a webshop cart.
	user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
	if user_type != "Website User":
		return

	from upande_webshop.upande_webshop.shopping_cart.cart import update_cart

	for entry in entries:
		try:
			update_cart(
				item_code=entry.get("item_code"),
				qty=entry.get("qty"),
				additional_notes=entry.get("additional_notes"),
				uom=entry.get("uom"),
				custom_length=entry.get("custom_length"),
				custom_box_type=entry.get("custom_box_type"),
			)
		except Exception:
			frappe.log_error(title="Pending cart replay failed")

	# Tell redirect_customer_after_login to land us on /cart instead of /webshop.
	frappe.local.flags.pending_cart_replayed = True
