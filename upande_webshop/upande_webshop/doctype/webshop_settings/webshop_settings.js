// Copyright (c) 2026, Upande LTD and contributors
// For license information, please see license.txt

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

		frappe.breadcrumbs.add({
			module: "Upande Webshop",
			workspace: "Upande Webshop",
			doctype: "Webshop Settings",
		});
	},
	refresh: function(frm) {
		if (!frm._upande_warehouse_listener) {
			frappe.realtime.on("upande_webshop_warehouse_synced", (data) => {
				frappe.show_alert({
					message: data.message,
					indicator: data.indicator || "green",
				}, 6);
			});
			frm._upande_warehouse_listener = true;
		}

		if (!frm._upande_prices_progress_listener) {
			frappe.realtime.on("webshop_prices_sync_progress", (data) => {
				const pct = Math.max(1, Math.min(100, Number(data && data.progress) || 0));
				const msg = (data && data.message) || __("Syncing...");
				const $bar = frm._upande_inline_progress_bar;
				const $msg = frm._upande_inline_progress_msg;
				if ($bar && $bar.length) {
					$bar.css("width", `${pct}%`).attr("aria-valuenow", pct).text(`${pct}%`);
				}
				if ($msg && $msg.length) {
					$msg.text(msg);
				}
				if (pct >= 100 && frm._upande_active_progress_dialog) {
					setTimeout(() => {
						if (frm._upande_active_progress_dialog) {
							frm._upande_active_progress_dialog.set_primary_action(
								__("Close"),
								() => frm._upande_active_progress_dialog.hide()
							);
						}
					}, 800);
				}
			});
			frm._upande_prices_progress_listener = true;
		}

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

		populate_warehouse_qty(frm);

		frm.add_custom_button(__("Repost Bin (all Website Items)"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Repost Bin from Stock Ledger"),
				fields: [
					{
						fieldtype: "HTML",
						options: `
							<div class="text-muted small">
								<p>${__("Submits one Repost Item Valuation per Website Item × configured Webshop warehouse. ERPNext's hourly repost cron will then rebuild <b>Bin.actual_qty</b> from the Stock Ledger.")}</p>
								<p><b>${__("This is expensive")}</b> — ${__("reposting walks every SLE for each item/warehouse pair. Run it during off-hours and only when storefront stock visibly disagrees with the Stock Ledger.")}</p>
								<p>${__("Pairs already Queued / In Progress will be skipped.")}</p>
							</div>
						`,
					},
				],
				primary_action_label: __("Start Repost"),
				primary_action: () => {
					d.hide();
					frappe.show_progress(__("Webshop Prices Sync"), 1, 100, __("Queueing reposts..."));
					frappe.call({
						method: "upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices.enqueue_repost_for_website_items",
						args: { run_async: 1 },
						callback: (r) => {
							const result = (r && r.message) || {};
							if (!result.enqueued) {
								frappe.hide_progress();
								frappe.show_alert({
									message: __("Could not start repost."),
									indicator: "red",
								}, 8);
								return;
							}
							frappe.show_alert({
								message: __("Repost queue-up started in background. Watch the progress bar."),
								indicator: "blue",
							}, 6);
						},
						error: () => {
							frappe.hide_progress();
						},
					});
				},
			});
			d.show();
		}, __("Actions"));

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
	publish_items: function(frm) {
		frappe.set_route("bulk-publish-items");
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
	sync_floriday_items: function(frm) {
		const d = new frappe.ui.Dialog({
			title: __("Sync Floriday Items"),
			fields: [
				{
					fieldtype: "Link",
					fieldname: "price_list",
					label: __("Item Price List"),
					options: "Price List",
					default: frm.doc.price_list || "USD Price List",
					reqd: 1,
					get_query: () => ({ filters: { selling: 1, enabled: 1 } }),
				},
				{
					fieldtype: "HTML",
					options: `<p class="text-muted small">${__(
						"Creates/updates a Floriday Items doc for every rose/herb item and refreshes stem length prices from the selected Price List. Also matches Floriday trade item IDs."
					)}</p>`,
				},
			],
			primary_action_label: __("Sync"),
			primary_action: ({ price_list }) => {
				d.hide();
				frappe.call({
					method: "upande_webshop.upande_webshop.doctype.floriday_items.floriday_items.sync_floriday_items",
					args: { force: 1, price_list },
					freeze: true,
					freeze_message: __("Syncing Floriday items..."),
					callback: (r) => {
						const result = (r && r.message) || {};
						if (result.skipped) {
							frappe.show_alert({
								message: __("Sync skipped: {0}", [result.reason || ""]),
								indicator: "orange",
							}, 8);
							return;
						}
						frappe.show_alert({
							message: __(
								"Processed {0} item(s) — created {1}, price refreshes {2}, trade IDs matched {3}/{4}.",
								[
									result.items_processed || 0,
									result.floriday_docs_created || 0,
									result.price_refreshes || 0,
									result.rows_matched || 0,
									result.total_rows || 0,
								]
							),
							indicator: "green",
						}, 10);
					},
				});
			},
		});
		d.show();
	},
	sync_prices: function(frm) {
		open_sync_dialog(frm, {
			source: "item_price",
			title: __("Sync Webshop Item Prices"),
			intro: __(
				"Refreshes per-length Item Prices for every Website Item from the configured Price List. Runs in the background."
			),
		});
	}
});

function populate_warehouse_qty(frm) {
	// Live total qty per configured warehouse, summed from Bin. Read-only display
	// only — nothing is persisted back. Skipped if the table is empty.
	const rows = (frm.doc.warehouses || []).filter(r => r.warehouse);
	if (!rows.length) return;

	frappe.call({
		method: "upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings.get_warehouse_totals",
		args: { warehouses: rows.map(r => r.warehouse) },
		callback: (r) => {
			const totals = (r && r.message) || {};
			(frm.doc.warehouses || []).forEach(row => {
				if (row.warehouse && totals[row.warehouse] !== undefined) {
					row.qty = totals[row.warehouse];
				}
			});
			// Re-render the grid so read-only static cells reflect updated row data.
			// frm.refresh_field("warehouses") alone does not redraw already-rendered cells.
			const grid = frm.fields_dict.warehouses.grid;
			grid.grid_rows && grid.grid_rows.forEach(gr => gr.refresh());
			grid.refresh();
		}
	});
}

function open_sync_dialog(frm, { source, title, intro }) {
	const d = new frappe.ui.Dialog({
		title,
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro_html",
				options: `<p class="text-muted small">${intro}</p>`,
			},
			{
				fieldtype: "Section Break",
				fieldname: "progress_section",
				label: __("Progress"),
				hidden: 1,
			},
			{
				fieldtype: "HTML",
				fieldname: "progress_html",
				options: `
					<div class="upande-inline-progress" style="padding: 4px 0;">
						<div class="progress" style="height: 18px; margin-bottom: 6px;">
							<div class="progress-bar progress-bar-striped active"
								role="progressbar" aria-valuemin="0" aria-valuemax="100"
								aria-valuenow="0" style="width: 0%; transition: width 0.4s ease;">
								0%
							</div>
						</div>
						<div class="text-muted small upande-progress-msg">
							${__("Queueing...")}
						</div>
					</div>
				`,
			},
		],
		primary_action_label: __("Start Sync"),
		primary_action: () => {
			d.set_df_property("progress_section", "hidden", 0);
			d.disable_primary_action();
			d.set_primary_action(__("Syncing..."), () => {});

			const $progress_field = d.get_field("progress_html").$wrapper;
			frm._upande_inline_progress_bar = $progress_field.find(".progress-bar");
			frm._upande_inline_progress_msg = $progress_field.find(".upande-progress-msg");
			frm._upande_active_progress_dialog = d;

			frm._upande_inline_progress_bar
				.css("width", "1%")
				.attr("aria-valuenow", 1)
				.text("1%");
			frm._upande_inline_progress_msg.text(__("Queueing..."));

			const cleanup = () => {
				frm._upande_inline_progress_bar = null;
				frm._upande_inline_progress_msg = null;
				frm._upande_active_progress_dialog = null;
			};
			d.$wrapper.on("hidden.bs.modal", cleanup);

			frappe.call({
				method: "upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices.sync_prices",
				args: { run_async: 1, source },
				callback: (r) => {
					const result = (r && r.message) || {};
					if (!result.enqueued) {
						d.enable_primary_action();
						frm._upande_inline_progress_msg.text(__("Could not start sync."));
						return;
					}
					frm._upande_inline_progress_msg.text(
						__("Sync running in background (source: {0}).", [result.source || source])
					);
				},
				error: () => {
					d.enable_primary_action();
					if (frm._upande_inline_progress_msg) {
						frm._upande_inline_progress_msg.text(__("Sync failed to start."));
					}
				},
			});
		},
	});
	d.show();
}
