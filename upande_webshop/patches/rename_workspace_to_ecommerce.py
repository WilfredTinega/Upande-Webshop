import frappe


def execute():
	"""Rename the admin Workspace "Upande Webshop" -> "Ecommerce" on existing sites.

	The workspace's name/title/label and its Desk route (slug of the name) all flip
	to "Ecommerce" / /app/ecommerce. We do this in pre_model_sync so the rename runs
	BEFORE the migrate's orphan-Workspace sweep: that sweep matches DB records against
	the on-disk JSON by name, and since the JSON now ships as "Ecommerce" it would
	otherwise delete the still-"Upande Webshop" record as an orphan and re-create a
	fresh one. Renaming first keeps the existing row (and any user tweaks) and lets
	the subsequent JSON sync simply update it in place. Idempotent / safe to re-run.
	"""
	legacy = "Upande Webshop"
	new = "Ecommerce"

	# Nothing to do if already renamed, or if the new name somehow collides.
	if not frappe.db.exists("Workspace", legacy):
		return
	if frappe.db.exists("Workspace", new):
		# Both present (e.g. a half-finished migrate): drop the stale legacy row so
		# only "Ecommerce" remains, matching a clean install.
		frappe.delete_doc("Workspace", legacy, force=True, ignore_permissions=True)
	else:
		# frappe.rename_doc (the public wrapper) takes no ignore_permissions kwarg;
		# force=True already skips the permission check in the underlying rename.
		frappe.rename_doc(
			"Workspace", legacy, new,
			force=True,
		)
		# name == title == label for a Workspace; keep them in step (rename_doc
		# updates name only). The JSON sync would also do this, but set it now so
		# the record is self-consistent regardless of sync timing.
		frappe.db.set_value(
			"Workspace", new,
			{"title": new, "label": new},
			update_modified=False,
		)

	# Drop the auto-generated launcher Desktop Icon that mirrored the old workspace
	# name and linked to the now-dead /app/upande-webshop route. The canonical
	# "Webshop" icon (-> /app/ecommerce) is upserted by ensure_desktop_icon() in
	# after_migrate.
	if frappe.db.exists("Desktop Icon", legacy):
		frappe.delete_doc("Desktop Icon", legacy, force=True, ignore_permissions=True)
