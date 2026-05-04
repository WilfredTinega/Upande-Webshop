// Copyright (c) 2026, Upande LTD and contributors
// For license information, please see license.txt

const METHOD_BASE = "upande_webshop.upande_webshop.doctype.biflorica_setting.biflorica_setting";

const PRIMARY_BUTTONS = [
	"post_offers",
	"get_offers",
	"refresh_stock",
	"get_deals",
	"get_predeals",
	"approve_deal",
];
const WARNING_BUTTONS = ["update_access_token"];

function inject_button_styles() {
	if (document.getElementById("biflorica-button-styles")) return;
	const css = `
		.biflorica-btn {
			transition: transform 120ms ease, box-shadow 160ms ease, filter 160ms ease;
			border-radius: 6px;
		}
		.biflorica-btn:hover {
			transform: translateY(-1px);
			box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
			filter: brightness(1.05);
		}
		.biflorica-btn:active {
			transform: translateY(0);
			box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
			filter: brightness(0.97);
		}
		.biflorica-btn:focus {
			box-shadow: 0 0 0 3px rgba(70, 130, 240, 0.25);
		}
	`;
	const style = document.createElement("style");
	style.id = "biflorica-button-styles";
	style.textContent = css;
	document.head.appendChild(style);
}

function style_button(frm, fieldname, cls) {
	const $btn = frm.fields_dict[fieldname] && frm.fields_dict[fieldname].$input;
	if (!$btn) return;
	$btn.removeClass("btn-default btn-primary btn-success btn-warning btn-danger");
	$btn.addClass(cls);
	$btn.addClass("biflorica-btn");
}

function toast(message, indicator) {
	frappe.show_alert({ message: message, indicator: indicator || "blue" }, 7);
}

function start_inline_progress(frm, button_field, label) {
	const $btn_wrapper = frm.fields_dict[button_field] && frm.fields_dict[button_field].$wrapper;
	if (!$btn_wrapper) {
		return start_dashboard_progress(frm, label);
	}

	const bar_id = `biflorica-progress-${button_field}`;
	let $bar = $btn_wrapper.next(`#${bar_id}`);
	if ($bar.length === 0) {
		$bar = $(`
			<div id="${bar_id}" class="biflorica-progress" style="margin: 8px 0 16px 0; max-width: 600px;">
				<div class="biflorica-progress-label" style="margin-bottom: 4px; font-size: var(--text-sm); color: var(--text-muted);"></div>
				<div class="progress" style="height: 8px;">
					<div class="progress-bar progress-bar-success" role="progressbar" style="width: 0%;"></div>
				</div>
			</div>
		`).insertAfter($btn_wrapper);
	}

	const prior = frm._biflorica_progress && frm._biflorica_progress[button_field];
	if (prior) {
		clearInterval(prior.tick);
		clearTimeout(prior.hide_timer);
	}

	const tracker = { tick: null, hide_timer: null, pct: 0 };
	frm._biflorica_progress = frm._biflorica_progress || {};
	frm._biflorica_progress[button_field] = tracker;

	const render = (pct, status_text) => {
		$bar.find(".progress-bar").css("width", pct + "%");
		$bar.find(".biflorica-progress-label").text(`${__(status_text)} ${pct}%`);
		$bar.show();
	};

	render(0, label);
	tracker.tick = setInterval(() => {
		tracker.pct = tracker.pct + Math.max(1, Math.round((95 - tracker.pct) / 12));
		if (tracker.pct > 95) tracker.pct = 95;
		render(tracker.pct, label);
	}, 400);

	return () => {
		clearInterval(tracker.tick);
		render(100, "Done");
		tracker.hide_timer = setTimeout(() => {
			$bar.fadeOut(200);
			if (frm._biflorica_progress && frm._biflorica_progress[button_field] === tracker) {
				frm._biflorica_progress[button_field] = null;
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

function call_biflorica(frm, button_field, method, label, args, on_success) {
	if (frm.is_dirty()) {
		toast(__("Please save the form before performing this action."), "orange");
		return;
	}

	const stop_progress = start_inline_progress(frm, button_field, label);
	frappe.call({
		method: `${METHOD_BASE}.${method}`,
		args: args || {},
		callback: function (r) {
			stop_progress();
			const res = r.message || {};
			if (res.success) {
				toast(res.message || __("Done"), "green");
				if (on_success) on_success(res);
				frm.reload_doc();
			} else {
				toast(res.message || __("Request failed"), "red");
				if (on_success) on_success(res);
			}
		},
		error: function () {
			stop_progress();
		}
	});
}

frappe.ui.form.on("Biflorica Setting", {
	refresh(frm) {
		inject_button_styles();
		PRIMARY_BUTTONS.forEach((fn) => style_button(frm, fn, "btn-primary"));
		WARNING_BUTTONS.forEach((fn) => style_button(frm, fn, "btn-warning"));
	},

	update_access_token(frm) {
		call_biflorica(frm, "update_access_token", "update_access_token", "Refreshing access token");
	},

	refresh_stock(frm) {
		call_biflorica(frm, "refresh_stock", "refresh_stock", "Loading warehouse stock");
	},

	post_offers(frm) {
		call_biflorica(frm, "post_offers", "post_offers", "Posting offers to Biflorica", {}, function (res) {
			const s = res.summary || {};
			const ok = s.success_varieties || [];
			const failed = s.failed_varieties || [];

			if (ok.length) {
				toast(__("Posted: {0}", [ok.join(", ")]), "green");
			}
			if (failed.length) {
				const lines = failed.map(function (f) {
					return f.variety + " (" + (f.reason || "rejected") + ")";
				});
				toast(__("Failed: {0}", [lines.join(", ")]), "red");
			}
			if (!ok.length && !failed.length) {
				toast(__("No offers processed"), "orange");
			}
		});
	},

	get_offers(frm) {
		call_biflorica(frm, "get_offers", "get_offers", "Fetching offers");
	},

	get_deals(frm) {
		call_biflorica(frm, "get_deals", "get_deals", "Fetching deals");
	},

	get_predeals(frm) {
		call_biflorica(frm, "get_predeals", "get_predeals", "Fetching predeals");
	},

	approve_deal(frm) {
		const d = new frappe.ui.Dialog({
			title: __("Approve Deal"),
			fields: [
				{ fieldname: "deal_id", fieldtype: "Data", label: __("Deal ID"), reqd: 1 }
			],
			primary_action_label: __("Approve"),
			primary_action(values) {
				d.hide();
				call_biflorica(
					frm,
					"approve_deal",
					"approve_deal",
					"Approving deal",
					{ deal_id: values.deal_id }
				);
			}
		});
		d.show();
	}
});
