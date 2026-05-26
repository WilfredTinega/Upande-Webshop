// Copyright (c) 2026, Upande LTD and contributors
// License: GNU General Public License v3. See license.txt

// JS exclusive to /cart page
frappe.provide("upande_webshop.upande_webshop.shopping_cart");
var shopping_cart = upande_webshop.upande_webshop.shopping_cart;

$.extend(shopping_cart, {
	show_error: function(title, text) {
		$("#cart-container").html('<div class="msg-box"><h4>' +
			title + '</h4><p class="text-muted">' + text + '</p></div>');
	},

	bind_events: function() {
		shopping_cart.bind_place_order();
		shopping_cart.bind_request_quotation();
		shopping_cart.bind_change_qty();
		shopping_cart.bind_remove_cart_item();
		shopping_cart.bind_coupon_code();
		shopping_cart.bind_remove_coupon_code();
		shopping_cart.bind_delivery_date();
		shopping_cart.bind_delivery_point();
	},

	bind_place_order: function() {
		$(".btn-place-order").on("click", function() {
			// Validate delivery date is set before placing order
			var delivery_date = $("#delivery-date").val();
			if (!delivery_date) {
				frappe.show_alert({
					message: __('Please select an expected delivery date before placing your order.'),
					indicator: 'red'
				}, 5);
				$("#delivery-date").focus();
				return;
			}
			shopping_cart.place_order(this);
		});
	},

	bind_request_quotation: function() {
		$('.btn-request-for-quotation').on('click', function() {
			frappe.ui && frappe.ui.form && frappe.ui.form.dirty_dialog && frappe.ui.form.dirty_dialog.hide();
			window.onbeforeunload = null;
			shopping_cart.request_quotation(this);
		});
	},

	bind_change_qty: function() {
		$(".cart-items").on("change", ".cart-qty", function() {
			var input = $(this);
			var item_code = input.attr("data-item-code");
			var bunches = parseInt(input.val()) || 1;
			// Clamp typed qty at the per-row stock cap (0 = no cap).
			var maxBunches = parseInt(input.attr("data-max-bunches")) || 0;
			if (maxBunches > 0 && bunches > maxBunches) {
				bunches = maxBunches;
				input.val(bunches);
				frappe.show_alert({
					message: __("Stock limit reached — capped at {0}.", [maxBunches]),
					indicator: "orange"
				}, 5);
			}
			var row = input.closest("tr");
			var uom = row.attr("data-uom") || undefined;
			var custom_length = row.attr("data-custom-length") || undefined;
			var custom_box_type = row.attr("data-custom-box-type") || undefined;
			var child_docname = row.attr("data-name") || undefined;
			shopping_cart.shopping_cart_update({item_code, qty: bunches, uom, custom_length, custom_box_type, child_docname});
		});

		$(".cart-items").on('click', '.number-spinner button', function () {
			var btn = $(this),
				input = btn.closest('.number-spinner').find('input'),
				oldValue = parseInt(input.val().trim()) || 1,
				newVal = 0;

			if (btn.attr('data-dir') == 'up') {
				// Honour the per-row stock cap (0 = no cap). At/over cap → no-op.
				var maxBunches = parseInt(input.attr("data-max-bunches")) || 0;
				if (maxBunches > 0 && oldValue >= maxBunches) {
					frappe.show_alert({
						message: __("Stock limit reached — only {0} bunch(es) available.", [maxBunches]),
						indicator: "orange"
					}, 5);
					return;
				}
				newVal = oldValue + 1;
			} else {
				if (oldValue > 1) {
					newVal = oldValue - 1;
				} else {
					newVal = 1;
				}
			}
			input.val(newVal);

			var item_code = input.attr("data-item-code");
			var row = input.closest("tr");
			var uom = row.attr("data-uom") || undefined;
			var custom_length = row.attr("data-custom-length") || undefined;
			var custom_box_type = row.attr("data-custom-box-type") || undefined;
			var child_docname = row.attr("data-name") || undefined;
			shopping_cart.shopping_cart_update({
				item_code,
				qty: newVal,
				uom,
				custom_length,
				custom_box_type,
				child_docname
			});
		});
	},

	bind_remove_cart_item: function() {
		$(".cart-items").on("click", ".remove-cart-item", (e) => {
			const $btn = $(e.currentTarget);
			var item_code = $btn.data("item-code");
			var child_docname = $btn.data("child-docname") || undefined;

			shopping_cart.shopping_cart_update({
				item_code: item_code,
				qty: 0,
				child_docname: child_docname
			});
		});
	},

	// ---- Delivery Date ----
	bind_delivery_date: function() {
		var $wrapper = $("#delivery-date-wrapper");
		if (!$wrapper.length) return;

		var transit_days = parseInt($(".delivery-date-section").data("transit-days")) || 1;
		var min_offset = Math.max(transit_days, 1);
		var min_date = new Date();
		min_date.setDate(min_date.getDate() + min_offset);
		min_date.setHours(0, 0, 0, 0);

		var initial_value = $wrapper.data("initial-value") || "";

		// controls.bundle.js is included on this page (cart.html base_scripts),
		// so frappe.ui.form.make_control is available synchronously.
		if (!(frappe.ui && frappe.ui.form && frappe.ui.form.make_control)) {
			shopping_cart._render_native_date_input($wrapper, initial_value, min_date, min_offset);
			return;
		}

		var control = frappe.ui.form.make_control({
			parent: $wrapper.get(0),
			df: {
				fieldtype: "Date",
				fieldname: "delivery_date",
				label: "",
				placeholder: __("Select delivery date"),
			},
			render_input: true,
			only_input: true,
		});

		var apply_min = function() {
			if (control.datepicker) {
				// Floor at tomorrow and hide the "Today" shortcut button so users can't
				// jump to a date that the server will reject.
				control.datepicker.update({ minDate: min_date, todayButton: false });
				return true;
			}
			return false;
		};
		if (!apply_min()) {
			var tries = 0;
			var iv = setInterval(function() {
				tries++;
				if (apply_min() || tries > 20) clearInterval(iv);
			}, 50);
		}

		// Default to the next valid delivery date when the cart has no saved
		// date. The server-side _ensure_default_delivery_date already wrote
		// tomorrow into the quotation on this request, so we only need to fill
		// the picker — don't POST again or we race the existing save.
		var default_value = shopping_cart._format_date(min_date);
		var prefill = initial_value || default_value;

		// set_value schedules onchange via a microtask (Promise.then in
		// base_control.js), so a synchronous `suppress_save = false` right after
		// set_value runs BEFORE the change fires — the guard fails and we POST
		// on every page load, racing the server's _ensure_default_delivery_date
		// write and hitting `Record has changed since last read`. Release the
		// guard in a microtask of our own so it runs strictly after onchange.
		var suppress_save = true;
		control.df.onchange = function() {
			if (suppress_save) return;

			var value = control.get_value();
			if (!value) return;

			var selected = frappe.datetime.str_to_obj(value);
			selected.setHours(0, 0, 0, 0);

			var today = new Date();
			today.setHours(0, 0, 0, 0);

			// Reject today (and earlier) regardless of transit_days configuration.
			if (selected <= today || selected < min_date) {
				frappe.show_alert({
					message: __("Please select a date after today."),
					indicator: "orange",
				}, 5);
				suppress_save = true;
				control.set_value("");
				Promise.resolve().then(function() { suppress_save = false; });
				return;
			}

			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_delivery_date",
				args: { delivery_date: value },
			});
		};

		control.set_value(prefill);
		Promise.resolve().then(function() { suppress_save = false; });
	},

	// ---- Delivery Point ----
	bind_delivery_point: function() {
		var $wrapper = $("#delivery-point-wrapper");
		if (!$wrapper.length) return;

		var initial_value = $wrapper.data("initial-value") || "";

		if (!(frappe.ui && frappe.ui.form && frappe.ui.form.make_control)) {
			shopping_cart._render_native_delivery_point($wrapper, initial_value);
			return;
		}

		var control = frappe.ui.form.make_control({
			parent: $wrapper.get(0),
			df: {
				fieldtype: "Autocomplete",
				fieldname: "custom_delivery_point",
				label: "",
				placeholder: __("Select delivery point"),
			},
			render_input: true,
			only_input: true,
		});

		var load_options = function(txt) {
			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.search_delivery_points",
				args: { txt: txt || "", limit: 50 },
				callback: function(r) {
					var rows = (r && r.message) || [];
					control.set_data(rows);
				},
			});
		};
		load_options("");

		if (control.$input && control.$input.length) {
			control.$input.on("input", function() {
				load_options($(this).val() || "");
			});
		}

		// Wire onchange before set_value, with a suppress flag so the initial
		// prefill doesn't race a save against the page-load _ensure_default_*
		// path.
		var suppress_save = true;
		control.df.onchange = function() {
			if (suppress_save) return;
			var value = control.get_value() || "";
			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_delivery_point",
				args: { delivery_point: value },
			});
		};

		if (initial_value) {
			control.set_value(initial_value);
		}
		suppress_save = false;
	},

	// Fallback if controls.bundle fails to load — keeps the form functional.
	_render_native_delivery_point: function($wrapper, initial_value) {
		var $input = $('<input type="text" class="form-control font-md" placeholder="' + __("Select delivery point") + '">')
			.val(initial_value);
		$wrapper.empty().append($input);

		$input.on("change", function() {
			var value = $(this).val() || "";
			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_delivery_point",
				args: { delivery_point: value },
			});
		});
	},
	// ---- End Delivery Point ----

	// Fallback if controls.bundle fails to load — keeps the form functional.
	_render_native_date_input: function($wrapper, initial_value, min_date, min_offset) {
		var min_iso = shopping_cart._format_date(min_date);
		// _ensure_default_delivery_date already wrote tomorrow server-side, so
		// just prefill the input without POSTing again.
		var default_value = initial_value || min_iso;
		var $input = $('<input type="date" class="form-control font-md" style="cursor:pointer;">')
			.attr("min", min_iso)
			.val(default_value);
		$wrapper.empty().append($input);

		$input.on("click focus", function() {
			if (typeof this.showPicker === "function") {
				try { this.showPicker(); } catch (e) {}
			}
		});

		$input.on("change", function() {
			var value = $(this).val();
			if (!value) return;
			var selected = new Date(value);
			selected.setHours(0, 0, 0, 0);

			var today = new Date();
			today.setHours(0, 0, 0, 0);

			if (selected <= today || selected < min_date) {
				frappe.show_alert({
					message: __("Please select a date after today."),
					indicator: "orange",
				}, 5);
				$(this).val("");
				return;
			}
			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_delivery_date",
				args: { delivery_date: value },
			});
		});
	},

	_format_date: function(date) {
		var y = date.getFullYear();
		var m = String(date.getMonth() + 1).padStart(2, "0");
		var d = String(date.getDate()).padStart(2, "0");
		return y + "-" + m + "-" + d;
	},
	// ---- End Delivery Date ----

	render_tax_row: function($cart_taxes, doc, shipping_rules) {
		var shipping_selector;
		if(shipping_rules) {
			shipping_selector = '<select class="form-control">' + $.map(shipping_rules, function(rule) {
				return '<option value="' + rule[0] + '">' + rule[1] + '</option>' }).join("\n") +
			'</select>';
		}

		var $tax_row = $(repl('<div class="row">\
			<div class="col-md-9 col-sm-9">\
				<div class="row">\
					<div class="col-md-9 col-md-offset-3">' +
					(shipping_selector || '<p>%(description)s</p>') +
					'</div>\
				</div>\
			</div>\
			<div class="col-md-3 col-sm-3 text-right">\
				<p' + (shipping_selector ? ' style="margin-top: 5px;"' : "") + '>%(formatted_tax_amount)s</p>\
			</div>\
		</div>', doc)).appendTo($cart_taxes);

		if(shipping_selector) {
			$tax_row.find('select option').each(function(i, opt) {
				if($(opt).html() == doc.description) {
					$(opt).attr("selected", "selected");
				}
			});
			$tax_row.find('select').on("change", function() {
				shopping_cart.apply_shipping_rule($(this).val(), this);
			});
		}
	},

	apply_shipping_rule: function(rule, btn) {
		return frappe.call({
			btn: btn,
			type: "POST",
			method: "upande_webshop.upande_webshop.shopping_cart.cart.apply_shipping_rule",
			args: { shipping_rule: rule },
			callback: function(r) {
				if(!r.exc) {
					shopping_cart.render(r.message);
				}
			}
		});
	},

	_extract_server_message: function(r) {
		var msg = "";
		try {
			if (r && r._server_messages) {
				var parts = JSON.parse(r._server_messages) || [];
				msg = parts.map(function(p) {
					try { return (JSON.parse(p).message || "").replace(/<[^>]*>/g, ""); }
					catch(e) { return (p || "").toString().replace(/<[^>]*>/g, ""); }
				}).filter(Boolean).join(" ");
			}
		} catch (e) {}
		return msg;
	},

	place_order: function(btn) {
		return frappe.call({
			type: "POST",
			method: "upande_webshop.upande_webshop.shopping_cart.cart.place_order",
			btn: btn,
			callback: function(r) {
				if (r.exc) {
					var msg = shopping_cart._extract_server_message(r) || __("Something went wrong!");
					r._server_messages = null;
					frappe.show_alert({ message: msg, indicator: "red" }, 7);
					return;
				}
				if (r.message && typeof r.message === "object" && r.message.error) {
					frappe.show_alert({ message: r.message.error, indicator: "red" }, 7);
					return;
				}
				$(btn).hide();
				window.location.href = '/orders/' + encodeURIComponent(r.message);
			}
		});
	},

	request_quotation: function(btn) {
		var target = $(btn).attr("data-cart-target") || "quotation";
		return frappe.call({
			type: "POST",
			method: "upande_webshop.upande_webshop.shopping_cart.cart.request_for_quotation",
			btn: btn,
			callback: function(r) {
				if (r.exc) {
					var msg = shopping_cart._extract_server_message(r) || __("Something went wrong!");
					r._server_messages = null;
					frappe.show_alert({ message: msg, indicator: "red" }, 7);
					return;
				}
				if (r.message && typeof r.message === "object" && r.message.error) {
					frappe.show_alert({ message: r.message.error, indicator: "red" }, 7);
					return;
				}
				$(btn).hide();
				var base = target === "sales_order" ? "/orders/" : "/quotations/";
				window.location.href = base + encodeURIComponent(r.message);
			}
		});
	},

	bind_coupon_code: function() {
		$(".bt-coupon").on("click", function() {
			shopping_cart.apply_coupon_code(this);
		});
	},

	apply_coupon_code: function(btn) {
		return frappe.call({
			type: "POST",
			method: "upande_webshop.upande_webshop.shopping_cart.cart.apply_coupon_code",
			btn: btn,
			args : {
				applied_code : $('.txtcoupon').val(),
				applied_referral_sales_partner: $('.txtreferral_sales_partner').val()
			},
			callback: function(r) {
				if (r && r.message){
					location.reload();
				}
			}
		});
	},

	bind_remove_coupon_code: function() {
		$(".bt-remove-coupon-code").on("click", function() {
			shopping_cart.remove_coupon_code(this);
		});
	},

	remove_coupon_code: function(btn) {
		return frappe.call({
			type: "POST",
			method: "upande_webshop.upande_webshop.shopping_cart.cart.remove_coupon_code",
			btn: btn,
			callback: function(r) {
				if (r && r.message){
					location.reload();
				}
			}
		});
	},
});

frappe.ready(function() {
	if (window.location.pathname === "/cart") {
		$(".cart-icon").hide();
		window.onbeforeunload = null;
	}
	shopping_cart.parent = $(".cart-container");
	shopping_cart.bind_events();
});

function show_terms() {
	var html = $(".cart-terms").html();
	frappe.msgprint(html);
}