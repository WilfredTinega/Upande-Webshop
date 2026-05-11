# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class VarietyPackRate(Document):
	def validate(self):
		self.validate_template_item()
		self.validate_unique_box_length_combinations()
		self.clear_caches()

	def validate_template_item(self):
		"""Ensure the linked Item is a template (has_variants=1) or at least exists."""
		if not self.variety:
			return
		has_variants = frappe.db.get_value("Item", self.variety, "has_variants")
		if has_variants is None:
			frappe.throw(_("Item {0} does not exist").format(self.variety))
		# Allow non-template items too (some varieties may not use template/variant structure)

	def validate_unique_box_length_combinations(self):
		"""Each (box_type, length_cm) pair must be unique in the table."""
		seen = set()
		for row in self.pack_rates:
			key = (row.box_type, row.length_cm)
			if key in seen:
				frappe.throw(
					_("Duplicate row: Box Type '{0}' with Length {1}cm appears more than once").format(
						row.box_type, row.length_cm
					)
				)
			seen.add(key)
			if row.stems_per_box <= 0:
				frappe.throw(
					_("Stems per Box must be greater than zero (Box: {0}, Length: {1}cm)").format(
						row.box_type, row.length_cm
					)
				)

	def clear_caches(self):
		"""Invalidate any cached pack rate lookups for this variety."""
		frappe.cache().delete_key("pack_rate_cache")

	def on_trash(self):
		frappe.cache().delete_key("pack_rate_cache")
