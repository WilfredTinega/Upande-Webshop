# Copyright (c) 2026, Upande LTD and contributors
# See license.txt

# import frappe
try:
	# Frappe develop (v17+) test framework
	from frappe.tests import IntegrationTestCase
except ImportError:
	# Frappe v15/v16 predecessor, API-compatible for these tests
	from frappe.tests.utils import FrappeTestCase as IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestWishlist(IntegrationTestCase):
	"""
	Integration tests for Wishlist.
	Use this class for testing interactions between multiple components.
	"""

	pass
