frappe.ui.form.on("Webshop Settings", {
	onload: function(frm) {
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

		frm.add_custom_button(__("Backfill Per-Length Prices"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Backfill Per-Length Item Prices"),
				fields: [
					{
						fieldtype: "HTML",
						options: `
							<div class="text-muted small">
								<p>${__("Seeds one <b>Item Price</b> row per master Stem Length for every enabled <b>non-variant</b> rose / David Austin item. Variants are skipped — they encode length in the item code.")}</p>
								<p>${__("Run this once after first install/migration. Ongoing items are maintained automatically when saved, so re-running only fills gaps — it is safe (idempotent) and creates no duplicates.")}</p>
							</div>
						`,
					},
				],
				primary_action_label: __("Start Backfill"),
				primary_action: () => {
					d.hide();
					frappe.show_progress(__("Webshop Prices Sync"), 1, 100, __("Backfilling per-length prices..."));
					frappe.call({
						method: "upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices.enqueue_backfill_per_length_prices",
						args: { run_async: 1 },
						callback: (r) => {
							const result = (r && r.message) || {};
							if (!result.enqueued) {
								frappe.hide_progress();
								frappe.show_alert({
									message: __("Could not start backfill."),
									indicator: "red",
								}, 8);
								return;
							}
							frappe.show_alert({
								message: __("Backfill started in background. Watch the progress bar."),
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
	open_bulk_publish_page: function(frm) {
		open_bulk_publish_dialog(frm);
	},
	open_setup_check: function(frm) {
		toggle_setup_check(frm);
	},
	enabled: function(frm) {
		if (frm.doc.enabled === 1) {
			frm.set_value('enable_variants', 1);
		}
		else {
			frm.set_value('company', '');
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
					default: "USD Price List",
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
			show_price_list: true,
			title: __("Sync Webshop Item Prices"),
			intro: __(
				"Refreshes per-length Item Prices for every Website Item. Pick a Price List to sync non-variant prices from; any length it lacks falls back to the configured Price List. Runs in the background."
			),
		});
	}
});

function toggle_setup_check(frm) {
	const field = frm.get_field("setup_check");
	if (!field) return;

	// Toggle: if currently shown, hide and clear.
	if (frm._setup_check_shown) {
		field.$wrapper.empty();
		frm._setup_check_shown = false;
		return;
	}

	frm._setup_check_shown = true;
	field.$wrapper.html(
		`<div class="text-muted small">${__("Checking required custom fields...")}</div>`
	);
	frappe.call({
		method: "upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings.get_setup_check_html",
		callback: (r) => {
			if (!frm._setup_check_shown) return; // toggled off while loading
			const msg = (r && r.message) || {};
			field.$wrapper.html(msg.html || "");
		},
		error: () => {
			field.$wrapper.html(
				`<div class="text-muted small">${__("Could not run setup check.")}</div>`
			);
		},
	});
}

const BULK_PUBLISH_METHOD =
	"upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings";

// ERPNext-provided default groups — hidden from the Item Group filter so users
// only pick real product groups.
const DEFAULT_ITEM_GROUPS = [
	"All Item Groups",
	"Products",
	"Raw Material",
	"Services",
	"Sub Assemblies",
	"Consumable",
	"Chemicals",
];

function open_bulk_publish_dialog(frm) {
	const state = {
		start: 0,
		page_length: 50,
		total: 0,
		items: [],
		selected: new Set(),
		in_progress: false,
		poll_timer: null,
		progress_dialog: null,
	};

	const d = new frappe.ui.Dialog({
		title: __("Bulk Publish Items"),
		size: "extra-large",
		fields: [
			{
				fieldtype: "Link",
				fieldname: "item_group",
				label: __("Item Group"),
				options: "Item Group",
				get_query: () => ({ filters: { name: ["not in", DEFAULT_ITEM_GROUPS] } }),
				change: () => reset_and_refresh(),
			},
			{ fieldtype: "Column Break" },
			{ fieldtype: "Check", fieldname: "show_templates", label: __("Show variant template"), default: 0, change: () => reset_and_refresh() },
			{ fieldtype: "Check", fieldname: "hide_published", label: __("Published"), default: 1, change: () => reset_and_refresh() },
			{ fieldtype: "Section Break" },
			{
				fieldtype: "HTML",
				fieldname: "grid_html",
				options: `
					<div class="bulk-publish-summary text-muted" style="margin: 0 0 8px;"></div>
					<div class="bulk-publish-table-wrap" style="max-height: 50vh; overflow: auto;">
						<table class="table table-bordered table-hover bulk-publish-table" style="background: var(--card-bg); margin-bottom: 0; width: 100%; table-layout: auto;">
							<thead style="position: sticky; top: 0; background: var(--card-bg); z-index: 1;">
								<tr>
									<th style="width: 36px; white-space: nowrap;"><input type="checkbox" class="select-all-checkbox" /></th>
									<th style="white-space: nowrap;">${__("Item Code")}</th>
									<th>${__("Item Name")}</th>
									<th style="white-space: nowrap;">${__("Item Group")}</th>
									<th style="width: 1%; white-space: nowrap;">${__("Status")}</th>
								</tr>
							</thead>
							<tbody class="bulk-publish-rows"></tbody>
						</table>
					</div>
					<div class="bulk-publish-pagination" style="display:flex; gap:8px; align-items:center; margin-top: 10px;">
						<button class="btn btn-default btn-sm prev-btn">${__("Previous")}</button>
						<button class="btn btn-default btn-sm next-btn">${__("Next")}</button>
						<span class="page-info text-muted"></span>
					</div>
				`,
			},
		],
		primary_action_label: __("Publish Selected"),
		primary_action: () => publish_selected(),
	});

	const $wrap = d.get_field("grid_html").$wrapper;
	const $summary = $wrap.find(".bulk-publish-summary");
	const $rows = $wrap.find(".bulk-publish-rows");
	const $selectAll = $wrap.find(".select-all-checkbox");
	const $prev = $wrap.find(".prev-btn");
	const $next = $wrap.find(".next-btn");
	const $pageInfo = $wrap.find(".page-info");

	const get_filters = () => ({
		item_group: d.get_value("item_group") || null,
		hide_published: d.get_value("hide_published") ? 1 : 0,
		show_templates: d.get_value("show_templates") ? 1 : 0,
	});

	const reset_and_refresh = () => {
		state.start = 0;
		state.selected.clear();
		refresh();
	};

	const update_primary = () => {
		const enabled = state.selected.size > 0 && !state.in_progress;
		d.get_primary_btn().prop("disabled", !enabled);
		$summary.text(__("{0} item(s) selected", [state.selected.size]));
	};

	const render_rows = () => {
		$rows.empty();
		if (!state.items.length) {
			$rows.append(`
				<tr><td colspan="5" class="text-muted text-center" style="padding: 20px;">
					${__("No items match the current filters.")}
				</td></tr>
			`);
			$selectAll.prop("checked", false).prop("disabled", true);
			return;
		}
		$selectAll.prop("disabled", false);

		for (const item of state.items) {
			const checked = state.selected.has(item.item_code) ? "checked" : "";
			const disabled = item.already_published ? "disabled" : "";
			const status = item.already_published
				? `<span class="indicator-pill green">${__("Published")}</span>`
				: `<span class="indicator-pill gray">${__("Not Published")}</span>`;
			$rows.append(`
				<tr>
					<td style="white-space: nowrap;"><input type="checkbox" class="row-checkbox" data-item-code="${frappe.utils.escape_html(item.item_code)}" ${checked} ${disabled} /></td>
					<td style="white-space: nowrap;">${frappe.utils.escape_html(item.item_code)}</td>
					<td style="word-break: break-word;">${frappe.utils.escape_html(item.item_name || "")}</td>
					<td style="white-space: nowrap;">${frappe.utils.escape_html(item.item_group || "")}</td>
					<td style="white-space: nowrap;">${status}</td>
				</tr>
			`);
		}

		$selectAll.prop(
			"checked",
			state.items.filter((i) => !i.already_published).every((i) => state.selected.has(i.item_code)) &&
				state.items.some((i) => !i.already_published)
		);
	};

	const render_pagination = () => {
		const from = state.total === 0 ? 0 : state.start + 1;
		const to = Math.min(state.start + state.page_length, state.total);
		$pageInfo.text(__("Showing {0}-{1} of {2}", [from, to, state.total]));
		$prev.prop("disabled", state.start <= 0);
		$next.prop("disabled", to >= state.total);
	};

	const refresh = async () => {
		const args = Object.assign({ start: state.start, page_length: state.page_length }, get_filters());
		const r = await frappe.call({ method: `${BULK_PUBLISH_METHOD}.get_items`, args });
		state.items = (r.message && r.message.items) || [];
		state.total = (r.message && r.message.total) || 0;
		render_rows();
		render_pagination();
		update_primary();
	};

	$selectAll.on("change", (e) => {
		const checked = $(e.target).is(":checked");
		for (const item of state.items) {
			if (item.already_published) continue;
			if (checked) state.selected.add(item.item_code);
			else state.selected.delete(item.item_code);
		}
		$rows.find(".row-checkbox:not(:disabled)").prop("checked", checked);
		update_primary();
	});

	$rows.on("change", ".row-checkbox", (e) => {
		const $cb = $(e.target);
		const code = $cb.data("item-code");
		if ($cb.is(":checked")) state.selected.add(code);
		else state.selected.delete(code);
		update_primary();
	});

	$prev.on("click", () => {
		if (state.start <= 0) return;
		state.start = Math.max(0, state.start - state.page_length);
		refresh();
	});

	$next.on("click", () => {
		if (state.start + state.page_length >= state.total) return;
		state.start += state.page_length;
		refresh();
	});

	const stop_polling = () => {
		if (state.poll_timer) {
			clearInterval(state.poll_timer);
			state.poll_timer = null;
		}
	};

	const finish_progress = ({ succeeded, skipped, failed, errors }) => {
		state.in_progress = false;
		stop_polling();
		if (state.progress_dialog) {
			const $bar = state.progress_dialog.$body.find(".bulk-publish-progress-bar");
			const $msg = state.progress_dialog.$body.find(".bulk-publish-progress-msg");
			$bar.css("width", "100%").attr("aria-valuenow", 100).text("100%");
			$msg.text(__("Done. Published: {0}, Skipped: {1}, Failed: {2}", [succeeded || 0, skipped || 0, failed || 0]));
			state.progress_dialog.set_primary_action(__("Close"), () => {
				state.progress_dialog.hide();
				state.progress_dialog = null;
				state.selected.clear();
				reset_and_refresh();
			});
		}
		if (errors && errors.length) {
			frappe.msgprint({
				title: __("Some items failed"),
				message: errors.map(frappe.utils.escape_html).join("<br>"),
				indicator: "orange",
			});
		}
	};

	const set_progress = (pct, message) => {
		if (!state.progress_dialog) return;
		const $bar = state.progress_dialog.$body.find(".bulk-publish-progress-bar");
		const $msg = state.progress_dialog.$body.find(".bulk-publish-progress-msg");
		$bar.css("width", `${pct}%`).attr("aria-valuenow", pct).text(`${pct}%`);
		if (message) $msg.text(message);
	};

	let last_event_at = Date.now();
	const on_progress = (data) => {
		if (!state.progress_dialog) return;
		last_event_at = Date.now();
		const pct = Math.max(1, Math.min(100, Number(data.progress) || 0));
		set_progress(pct, data.message || "");
	};
	const on_done = (data) => {
		if (!state.progress_dialog) return;
		last_event_at = Date.now();
		finish_progress(data);
	};
	frappe.realtime.off("webshop_bulk_publish_progress", on_progress);
	frappe.realtime.off("webshop_bulk_publish_done", on_done);
	frappe.realtime.on("webshop_bulk_publish_progress", on_progress);
	frappe.realtime.on("webshop_bulk_publish_done", on_done);

	d.$wrapper.on("hidden.bs.modal", () => {
		frappe.realtime.off("webshop_bulk_publish_progress", on_progress);
		frappe.realtime.off("webshop_bulk_publish_done", on_done);
		stop_polling();
	});

	const run_publish = async (codes) => {
		state.in_progress = true;
		update_primary();

		state.progress_dialog = new frappe.ui.Dialog({ title: __("Publishing Items"), no_cancel: true });
		state.progress_dialog.$body.html(`
			<div class="bulk-publish-progress-msg text-muted" style="margin-bottom: 10px;">${__("Starting...")}</div>
			<div class="progress" style="height: 20px;">
				<div class="progress-bar bulk-publish-progress-bar" role="progressbar"
					aria-valuenow="1" aria-valuemin="0" aria-valuemax="100" style="width: 1%;">1%</div>
			</div>
		`);
		state.progress_dialog.show();
		last_event_at = Date.now();

		try {
			await frappe.call({ method: `${BULK_PUBLISH_METHOD}.publish_items`, args: { item_codes: codes } });
			// Realtime-independent fallback: poll published count.
			const started_at = Date.now();
			state.poll_timer = setInterval(async () => {
				if (!state.progress_dialog) return stop_polling();
				try {
					const r = await frappe.call({
						method: `${BULK_PUBLISH_METHOD}.get_publish_status`,
						args: { item_codes: codes },
					});
					const total = (r.message && r.message.total) || codes.length || 1;
					const published = (r.message && r.message.published) || 0;
					const pct = Math.max(1, Math.min(99, Math.round((published / total) * 100)));
					const $bar = state.progress_dialog.$body.find(".bulk-publish-progress-bar");
					const current = parseInt($bar.attr("aria-valuenow"), 10) || 0;
					if (pct > current) set_progress(pct, __("Publishing {0} of {1}...", [published, total]));
					const idle_ms = Date.now() - (last_event_at || started_at);
					if (published >= total && idle_ms > 5000) {
						finish_progress({ succeeded: published, skipped: 0, failed: Math.max(0, total - published), errors: [] });
					}
				} catch (e) {
					// transient errors are fine — keep polling
				}
			}, 4000);
		} catch (e) {
			state.in_progress = false;
			stop_polling();
			update_primary();
			if (state.progress_dialog) {
				state.progress_dialog.hide();
				state.progress_dialog = null;
			}
		}
	};

	const publish_selected = () => {
		if (!state.selected.size) return;
		const codes = Array.from(state.selected);
		frappe.confirm(__("Publish {0} item(s) on the webshop?", [codes.length]), () => run_publish(codes));
	};

	d.show();
	update_primary();
	refresh();
}

function open_sync_dialog(frm, { source, title, intro, show_price_list }) {
	const d = new frappe.ui.Dialog({
		title,
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "intro_html",
				options: `<p class="text-muted small">${intro}</p>`,
			},
			...(show_price_list
				? [
						{
							fieldtype: "Link",
							fieldname: "price_list",
							label: __("Sync prices from (Price List)"),
							options: "Price List",
							// Selling price lists only — buying lists aren't storefront rates.
							get_query: () => ({ filters: { selling: 1, enabled: 1 } }),
							description: __(
								"Leave blank to use the configured Price List. Applies to non-variant items; missing lengths fall back to the configured list."
							),
						},
				  ]
				: []),
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

			const price_list = show_price_list ? d.get_value("price_list") : null;

			frappe.call({
				method: "upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices.sync_prices",
				args: { run_async: 1, source, price_list: price_list || undefined },
				callback: (r) => {
					const result = (r && r.message) || {};
					if (!result.enqueued) {
						d.enable_primary_action();
						frm._upande_inline_progress_msg.text(__("Could not start sync."));
						return;
					}
					const src = result.source || source;
					const pl = result.price_list || price_list;
					frm._upande_inline_progress_msg.text(
						pl
							? __("Sync running in background (source: {0}, price list: {1}).", [src, pl])
							: __("Sync running in background (source: {0}).", [src])
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
