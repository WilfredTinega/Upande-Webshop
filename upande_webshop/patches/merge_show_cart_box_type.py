import frappe


def execute():
	"""Consolidate the two box-type display flags into a single `show_box_type`.

	`show_cart_box_type` (the field the cart historically read) is being removed
	in favour of `show_box_type` as the one canonical control. Copy the live value
	across before model sync drops the old field, so a site that had the cart box
	type turned on keeps showing it, then delete the orphan Singles row. Runs
	pre_model_sync because the source value disappears once the field is gone.
	"""
	if not frappe.db.exists("DocType", "Webshop Settings"):
		return

	# Webshop Settings is a Single — its values live in `tabSingles`, not a table
	# column. Read the legacy flag straight from there; if it was never stored
	# (fresh install) there's nothing to migrate.
	row = frappe.db.sql(
		"""SELECT value FROM `tabSingles`
		WHERE doctype = 'Webshop Settings' AND field = 'show_cart_box_type'""",
	)
	if not row:
		return

	old_value = row[0][0]
	frappe.db.set_single_value("Webshop Settings", "show_box_type", frappe.utils.cint(old_value))

	# Drop the orphan row — model sync only removes table columns, not Singles rows.
	frappe.db.sql(
		"""DELETE FROM `tabSingles`
		WHERE doctype = 'Webshop Settings' AND field = 'show_cart_box_type'""",
	)
