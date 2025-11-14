import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from erpnext.stock.doctype.item.item import Item

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, random_string
from frappe.website.doctype.website_slideshow.website_slideshow import get_slideshow
from frappe.website.website_generator import WebsiteGenerator

from upande_webshop.upande_webshop.doctype.item_review.item_review import get_item_reviews
from upande_webshop.upande_webshop.redisearch_utils import (
    delete_item_from_index,
    insert_item_to_index,
    update_index_for_item,
)
from upande_webshop.upande_webshop.shopping_cart.cart import _set_price_list
from upande_webshop.upande_webshop.doctype.override_doctype.item_group import (
    get_parent_item_groups,
    invalidate_cache_for,
)
from erpnext.stock.doctype.item.item import Item
from erpnext.utilities.product import get_price
from upande_webshop.upande_webshop.shopping_cart.cart import get_party
from upande_webshop.upande_webshop.variant_selector.item_variants_cache import (
    ItemVariantsCacheManager,
)
class WebsiteItem(WebsiteGenerator):
    website = frappe._dict(
        page_title_field="web_item_name",
        condition_field="published",
        template="templates/generators/item/item.html",
        no_cache=1,
    )

    def autoname(self):
        from frappe.model.naming import get_default_naming_series, make_autoname
        naming_series = get_default_naming_series("Website Item")
        if not self.name and naming_series:
            self.name = make_autoname(naming_series, doc=self)

    def onload(self):
        super().onload()  # <--- updated

    def validate(self):
        super().validate()  # <--- updated

        if not self.item_code:
            frappe.throw(_("Item Code is required"), title=_("Mandatory"))

        self.validate_duplicate_website_item()
        self.validate_website_image()
        self.make_thumbnail()
        self.publish_unpublish_desk_item(publish=True)

        if not self.get("__islocal"):
            wig = frappe.qb.DocType("Website Item Group")
            query = (
                frappe.qb.from_(wig)
                .select(wig.item_group)
                .where(
                    (wig.parentfield == "website_item_groups")
                    & (wig.parenttype == "Website Item")
                    & (wig.parent == self.name)
                )
            )
            result = query.run(as_list=True)

            self.old_website_item_groups = [x[0] for x in result]

    def on_trash(self):
        super().on_trash()  # <--- updated
        delete_item_from_index(self)
        self.publish_unpublish_desk_item(publish=False)

def invalidate_item_variants_cache_for_website(doc):
	"""
	Rebuild ItemVariantsCacheManager via Item or Website Item

	Args:
		doc (Item): item of which cache should be cleared
	"""
	item_code = None
	is_web_item = doc.get("published_in_website") or doc.get("published")

	if doc.has_variants and is_web_item:
		item_code = doc.item_code
	elif doc.variant_of and frappe.db.get_value(
		"Item", doc.variant_of, "published_in_website"
	):
		item_code = doc.variant_of

	if not item_code:
		return

	item_cache = ItemVariantsCacheManager(item_code)
	item_cache.rebuild_cache()


def invalidate_cache_for_web_item(doc):
	"""
	Invalidate Website Item Group cache and rebuild ItemVariantsCacheManager
	Args:
		doc (Item): document against which cache should be cleared
	"""
	invalidate_cache_for(doc, doc.item_group)

	website_item_groups = list(
		set(
			(doc.get("old_website_item_groups") or [])
			+ [
				d.item_group
				for d in doc.get({"doctype": "Website Item Group"})
				if d.item_group
			]
		)
	)

	for item_group in website_item_groups:
		invalidate_cache_for(doc, item_group)

	# Update Search Cache
	update_index_for_item(doc)

	invalidate_item_variants_cache_for_website(doc)


def on_doctype_update():
	# since route is a Text column, it needs a length for indexing
	frappe.db.add_index("Website Item", ["route(500)"])


def check_if_user_is_customer(user=None):
	from frappe.contacts.doctype.contact.contact import get_contact_name

	if not user:
		user = frappe.session.user

	contact_name = get_contact_name(user)
	customer = None

	if contact_name:
		contact = frappe.get_doc("Contact", contact_name)
		for link in contact.links:
			if link.link_doctype == "Customer":
				customer = link.link_name
				break

	return True if customer else False


@frappe.whitelist()
def make_website_item(doc, save=True):
	"""
	Make Website Item from Item. Used via Form UI or patch.
	"""
	if not doc:
		return

	if isinstance(doc, str):
		doc = json.loads(doc)

	if frappe.db.exists("Website Item", {"item_code": doc.get("item_code")}):
		message = _("Website Item already exists against {0}").format(
			frappe.bold(doc.get("item_code"))
		)
		frappe.throw(message, title=_("Already Published"))

	website_item = frappe.new_doc("Website Item")
	website_item.web_item_name = doc.get("item_name")

	fields_to_map = [
		"item_code",
		"item_name",
		"item_group",
		"stock_uom",
		"brand",
		"has_variants",
		"variant_of",
		"description",
	]
	for field in fields_to_map:
		website_item.update({field: doc.get(field)})

	# Needed for publishing/mapping via Form UI only
	if not frappe.flags.in_migrate and (
		doc.get("image") and not website_item.website_image
	):
		website_item.website_image = doc.get("image")

	if not save:
		return website_item

	website_item.save()

	# Add to search cache
	insert_item_to_index(website_item)

	return [website_item.name, website_item.web_item_name]

@frappe.whitelist()
def has_website_permission_for_website_item(doc, ptype, user, verbose=False):
	# Check item group permissions for website

	if user == "Administrator":
		return True

	if frappe.has_permission("Website Item", ptype=ptype, doc=doc, user=user):
		return True

	if not frappe.db.get_single_value("Webshop Settings", "login_required_to_view_products"):
		return True

	return False

@frappe.whitelist()
def has_website_permission_for_item_group(doc, ptype, user, verbose=False):
	# Check item group permissions for website
	if user == "Administrator":
		return True

	if frappe.has_permission("Item Group", ptype=ptype, doc=doc, user=user):
		return True

	if not frappe.db.get_single_value("Webshop Settings", "login_required_to_view_products"):
		return True

	return False
