// Copyright (c) 2026, Upande LTD and contributors
// For license information, please see license.txt

const PRIMARY_BUTTONS = [
	"sales_order",
	"create_batch",
	"create_supplyine",
	"order_fullfilment",
	"add_items",
	"sync_item_id",
	"add_stock",
	"move_stock",
	"refresh_stock",
	"fetch_warehouses",
];
const WARNING_BUTTONS = ["update_access_token"];

function style_button(frm, fieldname, cls) {
	const $btn = frm.fields_dict[fieldname] && frm.fields_dict[fieldname].$input;
	if (!$btn) return;
	$btn.removeClass("btn-default btn-primary btn-success btn-warning btn-danger");
	$btn.addClass(cls);
}

function start_inline_progress(frm, button_field, label) {
	const $btn_wrapper = frm.fields_dict[button_field] && frm.fields_dict[button_field].$wrapper;
	if (!$btn_wrapper) {
		return start_dashboard_progress(frm, label);
	}

	const bar_id = `floriday-progress-${button_field}`;
	let $bar = $btn_wrapper.next(`#${bar_id}`);
	if ($bar.length === 0) {
		$bar = $(`
			<div id="${bar_id}" class="floriday-progress" style="margin: 8px 0 16px 0; max-width: 600px;">
				<div class="floriday-progress-label" style="margin-bottom: 4px; font-size: var(--text-sm); color: var(--text-muted);"></div>
				<div class="progress" style="height: 8px;">
					<div class="progress-bar progress-bar-success" role="progressbar" style="width: 0%;"></div>
				</div>
			</div>
		`).insertAfter($btn_wrapper);
	}

	const prior = frm._floriday_progress && frm._floriday_progress[button_field];
	if (prior) {
		clearInterval(prior.tick);
		clearTimeout(prior.hide_timer);
	}

	const tracker = { tick: null, hide_timer: null, pct: 0 };
	frm._floriday_progress = frm._floriday_progress || {};
	frm._floriday_progress[button_field] = tracker;

	const render = (pct, status_text) => {
		$bar.find(".progress-bar").css("width", pct + "%");
		$bar.find(".floriday-progress-label").text(`${__(status_text)} ${pct}%`);
		$bar.show();
	};

	render(0, "Running…");
	tracker.tick = setInterval(() => {
		tracker.pct = tracker.pct + Math.max(1, Math.round((95 - tracker.pct) / 12));
		if (tracker.pct > 95) tracker.pct = 95;
		render(tracker.pct, "Running…");
	}, 400);

	return () => {
		clearInterval(tracker.tick);
		render(100, "Done");
		tracker.hide_timer = setTimeout(() => {
			$bar.fadeOut(200);
			if (frm._floriday_progress && frm._floriday_progress[button_field] === tracker) {
				frm._floriday_progress[button_field] = null;
			}
		}, 800);
	};
}

function start_dashboard_progress(frm, label) {
	if (frm.dashboard.hide_progress) frm.dashboard.hide_progress();
	let pct = 0;
	frm.dashboard.show_progress(__(label), 0, `${__("Running…")} 0%`);
	const tick = setInterval(() => {
		pct = pct + Math.max(1, Math.round((95 - pct) / 12));
		if (pct > 95) pct = 95;
		frm.dashboard.show_progress(__(label), pct, `${__("Running…")} ${pct}%`);
	}, 400);
	return () => {
		clearInterval(tick);
		frm.dashboard.show_progress(__(label), 100, `${__("Done")} 100%`);
		setTimeout(() => frm.dashboard.hide_progress && frm.dashboard.hide_progress(), 600);
	};
}

function run_doc_method(frm, button_field, method, label, format_result) {
	const stop_progress = start_inline_progress(frm, button_field, label);
	frm.call({
		method,
		doc: frm.doc,
		callback(r) {
			stop_progress();
			const m = r.message ?? {};
			const { message, indicator } = format_result(m);
			frappe.show_alert({ message, indicator }, 7);
		},
		error() {
			stop_progress();
		},
	});
}

function format_sales_order_result(m) {
	if (m.status === "error") {
		return { message: __("Sync failed: {0}", [m.message || "unknown error"]), indicator: "red" };
	}
	const s = m.summary || {};
	const processed = s.processed || 0;
	const errors = s.errors || 0;
	if (processed === 0 && errors === 0) {
		return { message: __("No new sales orders"), indicator: "blue" };
	}
	const parts = [];
	if (processed) parts.push(__("Created {0} sales order(s)", [processed]));
	if (errors) parts.push(__("{0} error(s)", [errors]));
	return { message: parts.join(", "), indicator: errors ? "orange" : "green" };
}

function format_create_batch_result(m) {
	if (Array.isArray(m)) {
		const success = m.filter((r) => r.status === "success").length;
		const failed = m.filter((r) => r.status === "failed" || r.status === "error").length;
		const no_map = m.filter((r) => r.status === "no_mapping").length;
		if (success === 0 && failed === 0 && no_map === 0) {
			return { message: __("No batches to create"), indicator: "blue" };
		}
		const parts = [];
		if (success) parts.push(__("Created {0} batch(es)", [success]));
		if (failed) parts.push(__("{0} failed", [failed]));
		if (no_map) parts.push(__("{0} unmapped", [no_map]));
		return { message: parts.join(", "), indicator: failed ? "orange" : "green" };
	}
	if (m && m.message) {
		return { message: m.message, indicator: "blue" };
	}
	return { message: __("Done"), indicator: "green" };
}

function format_supplyline_result(m) {
	if (m.status === "error") {
		return { message: __("Failed: {0}", [m.message || "unknown error"]), indicator: "red" };
	}
	if (m.status === "failed") {
		return { message: m.message || __("No supply lines created"), indicator: "orange" };
	}
	const created = m.total_processed || 0;
	const available = m.available_batches || 0;
	if (created === 0) {
		return { message: __("No batches with stock for today"), indicator: "blue" };
	}
	return {
		message: __("Created {0} supply line(s) from {1} batch(es)", [created, available]),
		indicator: "green",
	};
}

function format_order_fullfilment_result(m) {
	if (m.status === "error") {
		return { message: __("Failed: {0}", [m.message || "unknown error"]), indicator: "red" };
	}
	if (m.message) {
		return { message: m.message, indicator: m.status === "success" ? "green" : "blue" };
	}
	return { message: __("Done"), indicator: "green" };
}

// Marking the form clean after we populate the read-only Stock view tables.
// add_child / clear_table dirty the form; the tables are derived from SLE on
// every open so we don't actually need them persisted — keep the form clean.
function _mark_form_clean(frm) {
	frm.doc.__unsaved = 0;
	(frm.doc.stock_items || []).forEach((r) => { r.__unsaved = 0; });
	(frm.doc.table_wtkz || []).forEach((r) => { r.__unsaved = 0; });
	if (typeof frm.refresh_header === "function") frm.refresh_header();
	if (frm.toolbar && typeof frm.toolbar.refresh === "function") frm.toolbar.refresh();
}

function load_system_stock_table(frm) {
	frappe.call({
		method: "upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.get_system_floriday_stock",
		callback(r) {
			const rows = r.message || [];
			frm.clear_table("table_wtkz");
			rows.forEach((row) => {
				const child = frm.add_child("table_wtkz");
				Object.assign(child, row);
			});
			frm.refresh_field("table_wtkz");
			_mark_form_clean(frm);
		},
	});
}

function load_stock_table(frm, { silent } = {}) {
	const stop_progress = silent ? () => {} : start_inline_progress(frm, "refresh_stock", "Loading stock");
	frappe.call({
		method: "upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.get_floriday_stock",
		args: {},
		callback(r) {
			stop_progress();
			const rows = r.message || [];
			frm.clear_table("stock_items");
			rows.forEach((row) => {
				const child = frm.add_child("stock_items");
				Object.assign(child, row);
			});
			frm.refresh_field("stock_items");
			_mark_form_clean(frm);
			if (!silent) {
				frappe.show_alert({
					message: __("Loaded {0} stock row(s)", [rows.length]),
					indicator: rows.length ? "green" : "blue",
				});
			}
		},
		error() {
			stop_progress();
		},
	});
}

function open_bulk_stock_dialog(frm, direction, prefill_row) {
	if (!frm.doc.warehouse) {
		frappe.show_alert({
			message: __("Set the Warehouse on the Floriday Setting tab first"),
			indicator: "orange",
		});
		return;
	}

	const is_add = direction === "in";
	const title = is_add
		? __("Add Stock to {0}", [frm.doc.warehouse])
		: __("Move Stock from {0}", [frm.doc.warehouse]);
	const method = is_add
		? "upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.create_stock_transfer"
		: "upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.create_stock_move";

	// For Move dialog: only allow Items currently in any Available-for-Sale warehouse.
	const setup_dialog = (allowed_codes_for_move, floriday_company) => {
		// Dynamic Item filter: query Bin live for items with stock in this row's
		// chosen Source Warehouse. Falls back to the bulk-loaded allowed list
		// if the row hasn't picked a source yet.
		const item_get_query = (doc, cdt, cdn) => {
			const row = cdt && cdn ? locals[cdt][cdn] : null;
			const s_wh = row && row.source_warehouse;
			if (s_wh) {
				return {
					query:
						"upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.item_query_with_stock",
					filters: { warehouse: s_wh },
				};
			}
			if (!is_add) {
				return {
					filters: [
						["Item", "name", "in", allowed_codes_for_move || []],
					],
				};
			}
			return {};
		};

		const warehouse_get_query = () => {
			const filters = [
				["Warehouse", "warehouse_name", "like", "%Available for Sale%"],
			];
			if (floriday_company) {
				filters.push(["Warehouse", "company", "=", floriday_company]);
			}
			return { filters };
		};

		const grid_fields = [
			{
				fieldname: "item_code",
				fieldtype: "Link",
				label: __("Item"),
				options: "Item",
				in_list_view: 1,
				columns: 3,
				reqd: 1,
				get_query: item_get_query,
			},
			{
				fieldname: "stem_length",
				fieldtype: "Link",
				label: __("Stem Length"),
				options: "Stem Length",
				in_list_view: 1,
				columns: 2,
				reqd: 1,
			},
			{
				fieldname: "source_warehouse",
				fieldtype: "Link",
				label: __("Source"),
				in_list_view: 1,
				columns: 2,
				options: "Warehouse",
				reqd: 1,
				get_query: warehouse_get_query,
				default: is_add ? "" : frm.doc.warehouse,
			},
			{
				fieldname: "target_warehouse",
				fieldtype: "Link",
				label: __("Target"),
				in_list_view: 1,
				columns: 2,
				options: "Warehouse",
				reqd: 1,
				get_query: warehouse_get_query,
				default: is_add ? frm.doc.warehouse : "",
			},
			{
				fieldname: "qty",
				fieldtype: "Float",
				label: __("Qty"),
				in_list_view: 1,
				columns: 2,
				reqd: 1,
			},
		];

		const initial_data = prefill_row
			? [{
				item_code: prefill_row.item_code,
				stem_length: prefill_row.stem_length,
				trade_item_id: prefill_row.trade_item_id,
				uom: prefill_row.uom,
				qty: prefill_row.qty || 0,
				// For Add (in): the row's warehouse is where the existing stock sits → source.
				// For Move (out): the row's warehouse is where stock currently is → source.
				source_warehouse: is_add ? prefill_row.warehouse : prefill_row.warehouse,
				target_warehouse: is_add ? frm.doc.warehouse : "",
			}]
			: [];

		const dialog = new frappe.ui.Dialog({
			title,
			size: "extra-large",
			fields: [
				{
					fieldname: "items",
					fieldtype: "Table",
					label: __("Items"),
					cannot_add_rows: false,
					in_place_edit: false,
					data: initial_data,
					fields: grid_fields,
				},
			],
			primary_action_label: is_add ? __("Submit Transfer") : __("Submit Move"),
			primary_action(values) {
				const rows = values.items || [];
				const incomplete = rows.find(
					(it) =>
						it.item_code &&
						(!it.stem_length || !it.qty || it.qty <= 0 || !it.source_warehouse || !it.target_warehouse)
				);
				if (incomplete) {
					frappe.show_alert({
						message: __("Each row needs Item, Stem Length, Source, Target and Qty"),
						indicator: "orange",
					});
					return;
				}
				const items = rows
					.filter((it) => it.item_code && it.stem_length && it.qty > 0 && it.source_warehouse && it.target_warehouse)
					.map((it) => ({
						item_code: it.item_code,
						stem_length: it.stem_length,
						qty: it.qty,
						source_warehouse: it.source_warehouse,
						target_warehouse: it.target_warehouse,
					}));
				if (!items.length) {
					frappe.show_alert({ message: __("Add at least one row"), indicator: "orange" });
					return;
				}
				dialog.disable_primary_action();
				frappe.call({
					method,
					args: { items: JSON.stringify(items) },
					callback(r) {
						dialog.enable_primary_action();
						if (r.message && r.message.name) {
							frappe.show_alert(
								{
									message: __("Stock Entry {0} created", [r.message.name]),
									indicator: "green",
								},
								7
							);
							dialog.hide();
							load_stock_table(frm, { silent: true });
							load_system_stock_table(frm);
						}
					},
					error() {
						dialog.enable_primary_action();
					},
				});
			},
		});

		const items_grid = dialog.fields_dict.items.grid;

		// When the user picks an Item, auto-fill stem_length if there's a single
		// Floriday mapping for it. The Link field's typeahead handles the rest.
		dialog.fields_dict.items.df.events = {
			item_code(frm_inner, cdt, cdn) {
				const row = locals[cdt][cdn];
				if (!row.item_code) {
					row.stem_length = "";
					items_grid.refresh();
					return;
				}
				frappe.call({
					method:
						"upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.get_item_floriday_meta",
					args: { item_code: row.item_code },
					callback(r) {
						const meta = r.message || {};
						if (meta.stem_length) {
							row.stem_length = meta.stem_length;
							items_grid.refresh();
						}
					},
				});
			},
		};

		dialog.show();
	};

	frappe.call({
		method:
			"upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.get_floriday_company",
		callback(rc) {
			const floriday_company = rc.message || null;
			if (is_add) {
				setup_dialog(null, floriday_company);
			} else {
				// Move: load items currently in the Floriday warehouse first
				frappe.call({
					method:
						"upande_webshop.upande_webshop.doctype.floriday_settings.floriday_settings.get_warehouse_stock_items",
					args: { warehouse: frm.doc.warehouse },
					callback(r) {
						const rows = r.message || [];
						if (!rows.length) {
							frappe.show_alert({
								message: __("No stock to move from {0}", [frm.doc.warehouse]),
								indicator: "orange",
							});
							return;
						}
						const allowed = rows.map((x) => x.item_code);
						setup_dialog(allowed, floriday_company);
					},
				});
			}
		},
	});
}

function open_single_row_dialog(frm, direction, row) {
	if (!row || !row.item_code) {
		frappe.show_alert({ message: __("Pick a row first"), indicator: "orange" });
		return;
	}
	open_bulk_stock_dialog(frm, direction, row);
}

function setup_stock_items_grid_buttons(frm) {
	const grid = frm.fields_dict.stock_items && frm.fields_dict.stock_items.grid;
	if (!grid || grid._floriday_buttons_added) return;
	grid._floriday_buttons_added = true;

	grid.add_custom_button(__("Add"), () => {
		const selected = grid.get_selected_children();
		const row = selected.length ? selected[0] : null;
		if (!row) {
			frappe.show_alert({ message: __("Tick a row to add stock for that item"), indicator: "orange" });
			return;
		}
		open_single_row_dialog(frm, "in", row);
	});

	grid.add_custom_button(__("Move"), () => {
		const selected = grid.get_selected_children();
		const row = selected.length ? selected[0] : null;
		if (!row) {
			frappe.show_alert({ message: __("Tick a row to move stock for that item"), indicator: "orange" });
			return;
		}
		open_single_row_dialog(frm, "out", row);
	});
}

frappe.ui.form.on("Floriday Settings", {
	refresh(frm) {
		PRIMARY_BUTTONS.forEach((fn) => style_button(frm, fn, "btn-primary"));
		WARNING_BUTTONS.forEach((fn) => style_button(frm, fn, "btn-warning"));
		setup_stock_items_grid_buttons(frm);
		// Always reload from SLE on open — saved rows can go stale.
		load_stock_table(frm, { silent: true });
		load_system_stock_table(frm);
		// Auto-render the custom-field status panel so the tab is never blank.
		check_custom_fields(frm, { silent: true });
	},

	check_custom_fields(frm) {
		check_custom_fields(frm, { silent: false });
	},

	create_missing_custom_fields(frm) {
		create_missing_custom_fields(frm);
	},

	add_stock(frm) {
		open_bulk_stock_dialog(frm, "in");
	},

	move_stock(frm) {
		open_bulk_stock_dialog(frm, "out");
	},

	refresh_stock(frm) {
		load_stock_table(frm, { silent: false });
		load_system_stock_table(frm);
	},

	warehouse(frm) {
		if (frm.doc.warehouse) {
			load_stock_table(frm, { silent: true });
			load_system_stock_table(frm);
		}
	},

	fetch_warehouses(frm) {
		const stop_progress = start_inline_progress(frm, "fetch_warehouses", "Fetching warehouses");
		frm.call({
			method: "fetch_warehouses",
			doc: frm.doc,
			callback(r) {
				stop_progress();
				const m = r.message || {};
				if (m.status === "success") {
					frappe.show_alert({
						message: __("Loaded {0} warehouse(s)", [m.count || 0]),
						indicator: (m.count || 0) ? "green" : "blue",
					}, 7);
					frm.reload_doc();
				}
			},
			error() {
				stop_progress();
			},
		});
	},

	update_access_token(frm) {
		const stop_progress = start_inline_progress(frm, "update_access_token", "Refreshing access token");
		frm.call({
			method: "update_access_token",
			doc: frm.doc,
			callback(r) {
				stop_progress();
				if (r.message && r.message.status === "success") {
					frappe.show_alert({
						message: __("Access token updated"),
						indicator: "green",
					});
					frm.reload_doc();
				}
			},
			error() {
				stop_progress();
			},
		});
	},

	sales_order(frm) {
		run_doc_method(frm, "sales_order", "sales_order", "Sales Order Sync", format_sales_order_result);
	},

	create_batch(frm) {
		run_doc_method(frm, "create_batch", "create_batch", "Create Batches", format_create_batch_result);
	},

	create_supplyine(frm) {
		run_doc_method(frm, "create_supplyine", "create_supplyine", "Create Supply Lines", format_supplyline_result);
	},

	order_fullfilment(frm) {
		run_doc_method(frm, "order_fullfilment", "order_fullfilment", "Order Fullfilment", format_order_fullfilment_result);
	},

	add_items(frm) {
		const stop_progress = start_inline_progress(frm, "add_items", "Adding system items");
		frappe.call({
			method: "upande_webshop.upande_webshop.doctype.floriday_items.floriday_items.sync_system_items",
			args: { force: 1 },
			callback(r) {
				stop_progress();
				const m = r.message;
				if (!m) return;
				if (m.skipped) {
					frappe.show_alert({ message: m.reason, indicator: "orange" });
					return;
				}
				const summary = `${m.floriday_docs_created || 0} created, ${m.price_refreshes || 0} prices refreshed${m.skipped ? `, ${m.skipped} errors` : ""}`;
				frappe.show_alert({ message: summary, indicator: "green" }, 7);
			},
			error() {
				stop_progress();
			},
		});
	},

	sync_item_id(frm) {
		const stop_progress = start_inline_progress(frm, "sync_item_id", "Syncing trade item IDs");
		frappe.call({
			method: "upande_webshop.upande_webshop.doctype.floriday_items.floriday_items.update_trade_item_ids",
			args: { force: 1 },
			callback(r) {
				stop_progress();
				const m = r.message;
				if (!m) return;
				if (m.skipped) {
					frappe.show_alert({ message: m.reason, indicator: "orange" });
					return;
				}
				if (m.error) {
					frappe.show_alert(
						{ message: __("Sync failed: {0}", [String(m.error).slice(0, 200)]), indicator: "red" },
						10
					);
					return;
				}
				const matched = m.rows_matched || 0;
				const total = m.total_rows || 0;
				const unmatched = m.unmatched || [];
				const parts = [__("Matched {0} of {1} rows", [matched, total])];
				if (unmatched.length) {
					const preview = unmatched
						.slice(0, 5)
						.map((u) => `${u.item_code} (${u.stem_length})`)
						.join(", ");
					const more = unmatched.length > 5 ? ` +${unmatched.length - 5} more` : "";
					parts.push(__("Unmapped: {0}{1}", [preview, more]));
				}
				frappe.show_alert(
					{
						message: parts.join(" — "),
						indicator: unmatched.length ? "orange" : "green",
					},
					unmatched.length ? 12 : 7
				);
			},
			error() {
				stop_progress();
			},
		});
	},
});

// ── Custom-field health check ────────────────────────────────────────────
const CUSTOM_FIELDS_API =
	"upande_webshop.upande_webshop.doctype.floriday_settings.floriday_custom_fields";

// Cache of the last check result so the Create button knows what to send.
let _floriday_field_status = [];

function render_custom_fields_panel(frm, rows) {
	const wrapper = frm.get_field("custom_fields_status_html");
	if (!wrapper || !wrapper.$wrapper) return;

	if (!rows || !rows.length) {
		wrapper.$wrapper.html(
			`<p class="text-muted">${__("No fields to check.")}</p>`
		);
		return;
	}

	const present = rows.filter((r) => r.present).length;
	const missing = rows.filter((r) => !r.present && !r.doctype_missing).length;
	const dt_missing = rows.filter((r) => r.doctype_missing).length;

	const head = `<div style="margin-bottom:8px;">
		<span class="indicator-pill green">${__("Present")}: ${present}</span>
		<span class="indicator-pill orange">${__("Missing")}: ${missing}</span>
		${dt_missing ? `<span class="indicator-pill red">${__("DocType absent")}: ${dt_missing}</span>` : ""}
	</div>`;

	const body = rows
		.map((r) => {
			let badge, color, disabled;
			if (r.doctype_missing) {
				badge = __("DocType absent");
				color = "red";
				disabled = "disabled";
			} else if (r.present) {
				badge = __("Present");
				color = "green";
				disabled = "disabled";
			} else {
				badge = r.optional ? __("Missing (optional)") : __("Missing");
				color = "orange";
				disabled = "";
			}
			const checked = !r.present && !r.doctype_missing && !r.optional ? "checked" : "";
			return `<tr>
				<td style="width:32px;text-align:center;">
					<input type="checkbox" class="floriday-cf-check"
						data-id="${frappe.utils.escape_html(r.id)}" ${checked} ${disabled}>
				</td>
				<td>${frappe.utils.escape_html(r.dt)}</td>
				<td><code>${frappe.utils.escape_html(r.fieldname)}</code></td>
				<td>${frappe.utils.escape_html(r.fieldtype || "")}</td>
				<td><span class="indicator-pill ${color}">${badge}</span></td>
			</tr>`;
		})
		.join("");

	wrapper.$wrapper.html(`${head}
		<table class="table table-bordered" style="font-size:12px;">
			<thead><tr>
				<th></th><th>${__("DocType")}</th><th>${__("Field")}</th>
				<th>${__("Type")}</th><th>${__("Status")}</th>
			</tr></thead>
			<tbody>${body}</tbody>
		</table>`);
}

function check_custom_fields(frm, { silent } = {}) {
	frappe.call({
		method: `${CUSTOM_FIELDS_API}.check_floriday_custom_fields`,
		callback(r) {
			_floriday_field_status = r.message || [];
			render_custom_fields_panel(frm, _floriday_field_status);
			if (!silent) {
				const missing = _floriday_field_status.filter(
					(x) => !x.present && !x.doctype_missing
				).length;
				frappe.show_alert(
					{
						message: missing
							? __("{0} custom field(s) missing", [missing])
							: __("All Floriday custom fields are present"),
						indicator: missing ? "orange" : "green",
					},
					6
				);
			}
		},
	});
}

function create_missing_custom_fields(frm) {
	// Gather ticked, enabled checkboxes from the rendered panel.
	const wrapper = frm.get_field("custom_fields_status_html");
	const ids = [];
	if (wrapper && wrapper.$wrapper) {
		wrapper.$wrapper.find(".floriday-cf-check:checked:not(:disabled)").each(function () {
			ids.push($(this).data("id"));
		});
	}

	if (!ids.length) {
		frappe.msgprint(__("Select at least one missing field to create."));
		return;
	}

	frappe.confirm(
		__("Create {0} custom field(s) on this site?", [ids.length]),
		() => {
			frappe.call({
				method: `${CUSTOM_FIELDS_API}.create_missing_floriday_custom_fields`,
				args: { field_ids: JSON.stringify(ids) },
				freeze: true,
				freeze_message: __("Creating custom fields…"),
				callback(r) {
					const m = (r.message && r.message.summary) || {};
					frappe.show_alert(
						{
							message: __("Created {0}, skipped {1}, errors {2}", [
								m.created || 0,
								m.skipped || 0,
								m.errors || 0,
							]),
							indicator: m.errors ? "red" : "green",
						},
						8
					);
					if (r.message && r.message.errors && r.message.errors.length) {
						frappe.msgprint({
							title: __("Field creation errors"),
							message: r.message.errors
								.map((e) => `<code>${frappe.utils.escape_html(e.id)}</code>: ${frappe.utils.escape_html(e.error)}`)
								.join("<br>"),
							indicator: "red",
						});
					}
					// Re-run the check so the panel reflects the new state.
					check_custom_fields(frm, { silent: true });
				},
			});
		}
	);
}
