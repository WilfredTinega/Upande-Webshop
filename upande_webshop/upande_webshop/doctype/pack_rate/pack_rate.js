// Copyright (c) 2026, Upande LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Pack Rate", {
	variety(frm) {
		if (frm.doc.variety) {
			frm.set_value("variety", frm.doc.variety.toLowerCase().trim());
		}
	},
});
