"""CI / test-environment setup helpers.

These are invoked explicitly from .github/helper/install.sh via `bench execute`
so the CI test site has the ERPNext fixtures that `bench run-tests` depends on.
They are intentionally NOT wired into after_install / after_migrate, so nothing
here runs on a normal production install.
"""

import frappe

# ERPNext seeds these Warehouse Types only through the setup wizard
# (erpnext/setup/setup_wizard/operations/install_fixtures.py). On a site where
# the wizard never ran (CI, or a bare install-app), creating a Company fails
# because its default "Goods In Transit" warehouse links Warehouse Type
# "Transit" (erpnext/setup/doctype/company/company.py). Test records that build a
# Company then blow up with "Could not find Warehouse Type: Transit".
STANDARD_WAREHOUSE_TYPES = ("Transit",)


def ensure_warehouse_types():
	"""Create the standard ERPNext Warehouse Types if missing. Idempotent and
	non-destructive: on a real ERPNext site these already exist, so it is a
	no-op. Returns the list of types it had to create."""
	created = []
	for wt in STANDARD_WAREHOUSE_TYPES:
		if not frappe.db.exists("Warehouse Type", wt):
			frappe.get_doc({"doctype": "Warehouse Type", "name": wt}).insert(
				ignore_permissions=True, ignore_if_duplicate=True
			)
			created.append(wt)
	frappe.db.commit()
	print(f"ensure_warehouse_types: created={created}, all={frappe.get_all('Warehouse Type', pluck='name')}")
	return created


# Webshop ships DocTypes that Link to DocTypes owned by sibling Upande apps that
# are NOT installed in CI (and are not declared required_apps). Frappe's test
# runner builds a test record for EVERY link-field dependency, so running a test
# whose dependency closure reaches one of these would call
# make_test_records(<missing doctype>) and crash with DoesNotExistError.
#
# Confirmed reachable from the tested DocTypes' link closure:
#   Webshop Settings -> Bouquet Recipe Item.stem_length -> "Stem Length"
#                       (owned by the private upande_harvest app)
# A minimal custom stub lets that dependency resolve without cloning a private
# repo. CI-only; never runs in production.
STUB_DOCTYPES = ("Stem Length",)


def ensure_stub_doctypes():
	"""Create minimal custom stub DocTypes for external link targets that tested
	webshop DocTypes depend on but that aren't installed in CI. Idempotent."""
	created = []
	for name in STUB_DOCTYPES:
		if frappe.db.exists("DocType", name):
			continue
		frappe.get_doc({
			"doctype": "DocType",
			"name": name,
			"module": "Upande Webshop",
			"custom": 1,
			"autoname": "hash",
			"fields": [{"label": "Title", "fieldname": "title", "fieldtype": "Data"}],
			"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
		}).insert(ignore_permissions=True)
		created.append(name)
	frappe.db.commit()
	print(f"ensure_stub_doctypes: created={created}")
	return created


def setup_test_site():
	"""Prepare a freshly installed CI site for `bench run-tests`.

	1. Guarantee the standard Warehouse Types exist FIRST. This is the concrete
	   thing the failing Company test record needs ("Could not find Warehouse
	   Type: Transit"), and it must not depend on the setup wizard succeeding.
	2. Stub external link-target DocTypes (e.g. "Stem Length") so the test
	   runner can build the link-dependency test records for webshop DocTypes.
	3. Run ERPNext's own test bootstrap (completes the setup wizard: Company,
	   fiscal year, accounts, selling defaults, roles, Item Attributes). This is
	   MANDATORY — if it fails we let it raise so this CI step fails loudly with
	   the traceback, rather than swallowing it and letting a dozen confusing
	   downstream test errors surface instead.
	"""
	ensure_warehouse_types()
	ensure_stub_doctypes()

	# MANDATORY: ERPNext's test bootstrap creates the selling defaults, enables
	# roles, and seeds fixtures (customer groups, price lists, Item Attributes)
	# that the inherited webshop tests rely on. If it fails, fail THIS step
	# loudly with the traceback — a swallowed failure here just resurfaces as a
	# dozen confusing downstream test errors (wrong customer group, permission
	# errors, "not a template item").
	from erpnext.setup.utils import before_tests

	print("setup_test_site: running erpnext before_tests ...")
	before_tests()
	print("setup_test_site: before_tests done")

	# before_tests can reset state; re-ensure our CI fixtures survive.
	ensure_warehouse_types()
	ensure_stub_doctypes()
