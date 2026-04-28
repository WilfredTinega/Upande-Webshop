# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PackRate(Document):
	def validate(self):
		self.normalize_variety()
		self.validate_positive_values()
		self.validate_unique_combination()

	def normalize_variety(self):
		if self.variety:
			self.variety = self.variety.strip().lower()

	def validate_positive_values(self):
		if self.length_cm is not None and self.length_cm <= 0:
			frappe.throw(_("Length (cm) must be greater than 0."))
		if self.stems_per_box is not None and self.stems_per_box <= 0:
			frappe.throw(_("Stems per Box must be greater than 0."))

	def validate_unique_combination(self):
		existing = frappe.db.exists(
			"Pack Rate",
			{
				"variety": self.variety,
				"box_group": self.box_group,
				"length_cm": self.length_cm,
				"name": ["!=", self.name or ""],
			},
		)
		if existing:
			frappe.throw(
				_("A Pack Rate already exists for {0} / {1} / {2} cm: {3}").format(
					self.variety, self.box_group, self.length_cm, existing
				)
			)
