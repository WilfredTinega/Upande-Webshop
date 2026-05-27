import frappe

sitemap = 1


def get_context(context):
	context.body_class = "product-page"
	context.parents = [{"name": frappe._("Home"), "route": "/webshop-setting"}]

	current_user_email = frappe.session.user
	# expose both user id (email) and full name to the template
	context.user_id = current_user_email
	context.full_name = frappe.session.user_fullname or ''
	context.current_user_image = frappe.session.user_image or ""
	context.current_customer = None
	context.linked_customers = []

	if current_user_email and current_user_email != "Guest":
		try:
			user_doc = frappe.get_doc("User", current_user_email)
			context.full_name = user_doc.full_name or context.full_name or current_user_email
			context.current_user_image = user_doc.user_image or context.current_user_image
		except frappe.DoesNotExistError:
			pass

		portal_users = frappe.get_all(
			"Portal User",
			filters={"user": current_user_email},
			fields=["parent"]
		)

		customer_names = []
		for portal_user in portal_users:
			parent_customer = portal_user.get("parent")
			if parent_customer and parent_customer not in customer_names:
				customer_names.append(parent_customer)

		default_currency = frappe.db.get_default("currency") or ''
		for cust_name in customer_names:
			customer = frappe.get_doc("Customer", cust_name)
			# Fall back to the system default currency when the customer has none set,
			# so a currency is always shown.
			currency = (
				customer.default_currency
				or getattr(customer, "billing_currency", "")
				or default_currency
			)
			context.linked_customers.append({
				'name': customer.customer_name or customer.name,
				'currency': currency
			})

		if context.linked_customers:
			context.current_customer = context.linked_customers[0].get('name')

	context.no_cache = 1
	return context