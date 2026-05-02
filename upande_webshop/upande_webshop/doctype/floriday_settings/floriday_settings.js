// Copyright (c) 2026, Upande LTD and contributors
// For license information, please see license.txt

const PRIMARY_BUTTONS = [
	"sales_order",
	"create_batch",
	"create_supplyine",
	"order_fullfilment",
	"add_items",
	"sync_item_id",
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

frappe.ui.form.on("Floriday Settings", {
	refresh(frm) {
		PRIMARY_BUTTONS.forEach((fn) => style_button(frm, fn, "btn-primary"));
		WARNING_BUTTONS.forEach((fn) => style_button(frm, fn, "btn-warning"));
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
