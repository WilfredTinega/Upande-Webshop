# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ItemGroupPackRate(Document):
	def validate(self):
		seen = set()
		for row in self.pack_rates:
			key = (row.box_type, row.length_cm)
			if key in seen:
				frappe.throw(
					_("Duplicate: Box Type '{0}' with Length {1}cm appears more than once").format(
						row.box_type, row.length_cm
					)
				)
			seen.add(key)
			if row.stems_per_box <= 0:
				frappe.throw(_("Stems per Box must be greater than zero"))
		frappe.cache().delete_key("pack_rate_cache")

	def on_trash(self):
		frappe.cache().delete_key("pack_rate_cache")
