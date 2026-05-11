frappe.ui.form.on("Webshop Item Prices", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Fetch Stem Length Prices"), () => {
			frm.call("fetch_stem_length_prices").then((r) => {
				const rows = r && r.message;
				frappe.show_alert({
					message: __("Refreshed {0} stem length rows", [rows || 0]),
					indicator: rows ? "green" : "orange",
				});
				frm.reload_doc();
			});
		}, __("Actions"));
	},
});
