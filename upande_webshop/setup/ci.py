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


def setup_test_site():
	"""Prepare a freshly installed CI site for `bench run-tests`.

	1. Guarantee the standard Warehouse Types exist FIRST. This is the concrete
	   thing the failing Company test record needs ("Could not find Warehouse
	   Type: Transit"), and it must not depend on the setup wizard succeeding.
	2. Best-effort run ERPNext's own test bootstrap (completes the setup wizard:
	   Company, fiscal year, accounts). If it fails we roll back and continue —
	   the Warehouse Types from step 1 already unblock the test records, so a
	   setup-wizard hiccup should not fail the whole CI run. Any traceback is
	   logged and printed for visibility.
	"""
	ensure_warehouse_types()

	try:
		from erpnext.setup.utils import before_tests

		before_tests()
	except Exception:
		frappe.db.rollback()
		print("setup_test_site: before_tests failed (continuing with warehouse types only):")
		print(frappe.get_traceback())
		frappe.log_error(title="upande_webshop setup_test_site", message=frappe.get_traceback())

	# Re-ensure in case a rollback above dropped anything.
	ensure_warehouse_types()
