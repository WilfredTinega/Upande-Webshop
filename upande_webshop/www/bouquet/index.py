import frappe
from frappe import _

from upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings import (
	apply_webshop_setup_guard,
)

sitemap = 1


def get_context(context):
	"""Bouquets storefront listing.

	Bouquets are built from Webshop Settings → Bouquet Recipes. Each unique
	`bouquet` value in that table is a bouquet (it points to a Website Item,
	which carries the bouquet's name/image/route). The recipe rows (item_group,
	stem_length, quantity) define what stems go into it; they're rendered on
	the per-bouquet detail page, not here.

	When 'Enable Bouquets Page' is off, redirects to /webshop.
	"""
	if apply_webshop_setup_guard(context):
		return

	settings = frappe.get_cached_doc("Webshop Settings")

	if not settings.get("show_bouquets_page"):
		frappe.local.flags.redirect_location = "/webshop"
		raise frappe.Redirect

	context.body_class = "product-page"
	context.parents = [{"name": _("Home"), "route": "/webshop"}]
	context.title = _("Bouquets")
	context.no_cache = 1

	context.bouquets = _get_bouquet_summaries()

	if settings.slideshow:
		context.slideshow = _get_slideshow(settings.slideshow)


def _get_bouquet_summaries():
	"""Return one entry per distinct bouquet Website Item, with its display
	fields and ingredient count."""
	rows = frappe.db.sql(
		"""
		SELECT
			bri.bouquet AS item_code,
			wi.web_item_name,
			wi.website_image,
			wi.route,
			wi.short_description,
			COUNT(*) AS ingredient_count,
			SUM(bri.quantity) AS total_stems
		FROM `tabBouquet Recipe Item` bri
		INNER JOIN `tabWebsite Item` wi ON wi.name = bri.bouquet
		WHERE IFNULL(wi.published, 0) = 1
		GROUP BY bri.bouquet
		ORDER BY wi.web_item_name ASC
		""",
		as_dict=True,
	)
	for r in rows:
		r["bouquet_route"] = f"/bouquet/{r.route.strip('/')}" if r.route else f"/bouquet/{r.item_code}"
	return rows


def _get_slideshow(slideshow):
	values = {"show_indicators": 1, "show_controls": 1, "rounded": 1, "slider_name": "Bouquets"}
	slideshow = frappe.get_cached_doc("Website Slideshow", slideshow)
	slides = slideshow.get({"doctype": "Website Slideshow Item"})
	for index, slide in enumerate(slides, start=1):
		values[f"slide_{index}_image"] = slide.image
		values[f"slide_{index}_title"] = slide.heading
		values[f"slide_{index}_subtitle"] = slide.description
		values[f"slide_{index}_theme"] = slide.get("theme") or "Light"
		values[f"slide_{index}_content_align"] = slide.get("content_align") or "Centre"
		values[f"slide_{index}_primary_action"] = slide.url
	return values
