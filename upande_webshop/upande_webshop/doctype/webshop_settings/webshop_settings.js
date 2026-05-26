frappe.ui.form.on("Webshop Settings", {
	onload: function(frm) {
		if(frm.doc.__onload && frm.doc.__onload.quotation_series) {
			frm.fields_dict.quotation_series.df.options = frm.doc.__onload.quotation_series;
			frm.refresh_field("quotation_series");
		}

		frm.set_query('payment_gateway_account', function() {
			return { 'filters': {
				'payment_channel': ['in', ["Email", "Phone"]]
			 } };
		});
	},
	refresh: function(frm) {
		if (frm.doc.enabled) {
			frm.get_field('store_page_docs').$wrapper.removeClass('hide-control').html(
				`<div>${__("Follow these steps to create a landing page for your store")}:
					<a href="https://docs.erpnext.com/docs/user/manual/en/website/store-landing-page"
						style="color: var(--gray-600)">
						docs/store-landing-page
					</a>
				</div>`
			);
		}

		frm.get_field("sync_prices").$input
			?.removeClass("btn-default")
			.addClass("btn-primary");

		frappe.model.with_doctype("Website Item", () => {
			const web_item_meta = frappe.get_meta('Website Item');

			const valid_fields = web_item_meta.fields.filter(df =>
				["Link", "Table MultiSelect"].includes(df.fieldtype) && !df.hidden
			).map(df =>
				({ label: df.label, value: df.fieldname })
			);

			frm.get_field("filter_fields").grid.update_docfield_property(
				'fieldname', 'options', valid_fields
			);
		});
	},
	enabled: function(frm) {
		if (frm.doc.enabled === 1) {
			frm.set_value('enable_variants', 1);
		}
		else {
			frm.set_value('company', '');
			frm.set_value('price_list', '');
			frm.set_value('default_customer_group', '');
			frm.set_value('quotation_series', '');
		}
	},
	sync_prices: function(frm) {
		frappe.confirm(
			__("Refresh stem length prices for every rose item from <b>USD Price List</b>?"),
			() => {
				// Subscribe to progress updates from the background job
				const event = "webshop_prices_sync_progress";
				const handler = (data) => {
					if (!data) return;
					const progress = Math.max(0, Math.min(100, Number(data.progress) || 0));
					const message = data.message || __("Syncing...");
					frappe.show_progress(__("Webshop Prices Sync"), progress, 100, message);
					if (progress >= 100) {
						setTimeout(() => {
							frappe.hide_progress();
							frappe.show_alert({ message: message, indicator: "green" }, 6);
						}, 800);
						frappe.realtime.off(event, handler);
					}
				};
				frappe.realtime.on(event, handler);

				frappe.call({
					method: "upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices.sync_prices",
					callback: (r) => {
						if (r && r.message && r.message.enqueued) {
							frappe.show_progress(__("Webshop Prices Sync"), 0, 100, __("Queued..."));
							frappe.show_alert(
								{ message: __("Sync running in the background. Progress will update here."), indicator: "blue" },
								5,
							);
						}
					},
				});
			}
		);
	}
});
