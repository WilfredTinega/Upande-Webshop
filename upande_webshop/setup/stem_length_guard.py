import os
import shutil

import frappe

DOCTYPE_NAME = "Stem Length"
DOCTYPE_SLUG = "stem_length"
OWN_MODULE = "Upande Webshop"
SKIP_PREFIX = "_skipped_"

_DOCTYPE_FOLDER = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
	"upande_webshop",
	"doctype",
)


def _active_path() -> str:
	return os.path.join(_DOCTYPE_FOLDER, DOCTYPE_SLUG)


def _skipped_path() -> str:
	return os.path.join(_DOCTYPE_FOLDER, SKIP_PREFIX + DOCTYPE_SLUG)


def _doctype_owned_elsewhere() -> bool:
	"""Return True if `Stem Length` already exists on the site and another app owns it."""
	if not frappe.db.exists("DocType", DOCTYPE_NAME):
		return False
	module = frappe.db.get_value("DocType", DOCTYPE_NAME, "module")
	return bool(module) and module != OWN_MODULE


def _hide_local_folder():
	active = _active_path()
	skipped = _skipped_path()
	if os.path.isdir(active) and not os.path.isdir(skipped):
		shutil.move(active, skipped)
		print(
			f"[upande_webshop] Skipping sync of '{DOCTYPE_NAME}' — already installed by another app."
		)


def _restore_local_folder():
	active = _active_path()
	skipped = _skipped_path()
	if os.path.isdir(skipped) and not os.path.isdir(active):
		shutil.move(skipped, active)


def guard():
	"""Run before install/migrate.

	If another app already owns the `Stem Length` doctype on this site, move the
	on-disk folder out of the way so Frappe's sync_for() ignores it. Otherwise,
	restore the folder if it was previously hidden.
	"""
	try:
		if _doctype_owned_elsewhere():
			_hide_local_folder()
		else:
			_restore_local_folder()
	except Exception as e:
		print(f"[upande_webshop] stem_length_guard error: {e}")
