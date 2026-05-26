# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BoxType(Document):
	def on_update(self):
		frappe.cache().delete_key("pack_rate_cache")

	def on_trash(self):
		frappe.cache().delete_key("pack_rate_cache")
