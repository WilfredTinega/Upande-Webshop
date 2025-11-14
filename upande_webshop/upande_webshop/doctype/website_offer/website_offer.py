# Copyright (c) 2025, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WebsiteOffer(Document):
	pass


@frappe.whitelist(allow_guest=True)
def get_offer_details(offer_id):
	return frappe.db.get_value("Website Offer", {"name": offer_id}, ["offer_details"])
