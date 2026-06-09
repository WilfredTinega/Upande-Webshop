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
		shopping_cart.bind_consignee();
		shopping_cart.bind_box_type();
		shopping_cart.bind_line_code();
		shopping_cart.bind_box_label();
		shopping_cart.bind_box_id();
	},

	bind_box_id: function() {
		// Per-item Box ID (editable). The cart auto-assigns box ids by packing
		// lines into boxes of the box type's pack rate; this lets the user
		// override the assigned id. Save on change/blur; skip if unchanged.
		// Delegated so it survives cart fragment re-renders.
		var $items = $(".cart-items");
		if (!$items.length) return;

		$items.on("focus", ".cart-box-id", function() {
			$(this).data("last-saved", $(this).val());
		});
		$items.on("change blur", ".cart-box-id", function() {
			var $el = $(this);
			var value = $el.val() || "";
			if (value !== "" && parseInt(value, 10) < 1) {
				value = "1";
				$el.val(value);
			}
			if ($el.data("last-saved") === value) return;
			$el.data("last-saved", value);
			frappe.call({
				type: "POST",
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_item_box_id",
				args: {
					child_docname: $el.attr("data-child-docname"),
					box_id: value,
				},
			});
		});
		$items.on("keydown", ".cart-box-id", function(e) {
			if (e.key === "Enter") {
				e.preventDefault();
				$(this).blur();
			}
		});
	},

	bind_box_label: function() {
		// Per-item Box Label (optional). Save on blur/Enter; skip if unchanged.
		// Delegated so it survives cart fragment re-renders (e.g. box-type change).
		var $items = $(".cart-items");
		if (!$items.length) return;

		$items.off("focus.wsBoxLabel").on("focus.wsBoxLabel", ".cart-box-label", function() {
			$(this).data("last-saved", $(this).val());
		});
		$items.off("change.wsBoxLabel blur.wsBoxLabel").on("change.wsBoxLabel blur.wsBoxLabel", ".cart-box-label", function() {
			var $el = $(this);
			var value = $el.val() || "";
			if ($el.data("last-saved") === value) return;
			$el.data("last-saved", value);
			frappe.call({
				type: "POST",
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_item_box_label",
				args: {
					child_docname: $el.attr("data-child-docname"),
					box_label: value,
				},
			});
		});
		$items.off("keydown.wsBoxLabel").on("keydown.wsBoxLabel", ".cart-box-label", function(e) {
			if (e.key === "Enter") {
				e.preventDefault();
				$(this).blur();
			}
		});
	},

	bind_line_code: function() {
		// Cart-level Line Code (sidebar input). Save on blur/Enter; skip if unchanged.
		var $input = $("#cart-line-code");
		if (!$input.length) return;
		$input.off("focus.wsLineCode").on("focus.wsLineCode", function() {
			$(this).data("last-saved", $(this).val());
		});
		// Force uppercase while typing
		$input.off("input.wsLineCode").on("input.wsLineCode", function() {
			$(this).val($(this).val().toUpperCase());
		});
		$input.off("change.wsLineCode blur.wsLineCode").on("change.wsLineCode blur.wsLineCode", function() {
			var $el = $(this);
			var value = $el.val() || "";
			if ($el.data("last-saved") === value) return;
			$el.data("last-saved", value);
			frappe.call({
				type: "POST",
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_line_code",
				args: { line_code: value },
			});
		});
		$input.off("keydown.wsLineCode").on("keydown.wsLineCode", function(e) {
			if (e.key === "Enter") {
				e.preventDefault();
				$(this).blur();
			}
		});
	},

	_validate_required_cart_fields: function() {
		// Returns true when all required cart-level fields are filled in.
		// Shows an alert + focuses the offending input on the first miss.
		var $dd = $("#delivery-date-wrapper").find("input").first();
		var delivery_date = $dd.length ? $dd.val() : "";
		if (!delivery_date) {
			frappe.show_alert({
				message: __('Please select an expected delivery date before placing your order.'),
				indicator: 'red'
			}, 5);
			if ($dd.length) $dd.focus();
			return false;
		}
		// Delivery point renders as a <select> (falls back to input if a Link
		// control is ever used). Read whichever control is present.
		var $dp = $("#delivery-point-wrapper").find("select, input").first();
		if ($dp.length && !($dp.val() || "").trim()) {
			frappe.show_alert({
				message: __('Please select a Delivery Point before placing your order.'),
				indicator: 'red'
			}, 5);
			$dp.focus();
			return false;
		}
		var $lc = $("#cart-line-code");
		if ($lc.length && !($lc.val() || "").trim()) {
			frappe.show_alert({
				message: __('Please enter a Line Code before placing your order.'),
				indicator: 'red'
			}, 5);
			$lc.focus();
			return false;
		}
		return true;
	},

	bind_place_order: function() {
		// Namespaced off/on so re-binding (SPA re-init) can't stack handlers and
		// fire place_order twice — a double order submit.
		$(".btn-place-order").off("click.wsOrder").on("click.wsOrder", function() {
			if (!shopping_cart._validate_required_cart_fields()) return;
			shopping_cart.place_order(this);
		});
	},

	bind_request_quotation: function() {
		$('.btn-request-for-quotation').off('click.wsRfq').on('click.wsRfq', function() {
			if (!shopping_cart._validate_required_cart_fields()) return;
			frappe.ui && frappe.ui.form && frappe.ui.form.dirty_dialog && frappe.ui.form.dirty_dialog.hide();
			window.onbeforeunload = null;
			shopping_cart.request_quotation(this);
		});
	},

	bind_change_qty: function() {
		$(".cart-items").off("change.wsQty").on("change.wsQty", ".cart-qty", function() {
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

		$(".cart-items").off('click.wsSpin').on('click.wsSpin', '.number-spinner button', function () {
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
		// Namespaced + .off first so re-running bind_events (e.g. after an SPA
		// content swap to /cart) can't stack duplicate handlers on .cart-items.
		$(".cart-items").off("click.wsRemove").on("click.wsRemove", ".remove-cart-item", (e) => {
			const $btn = $(e.currentTarget);
			var item_code = $btn.attr("data-item-code") || $btn.closest("tr").find(".cart-qty").attr("data-item-code");
			// Prefer the button's data-child-docname; fall back to the row's
			// data-name (the same value the qty handlers use). Use attr() not
			// data() to avoid jQuery's cached/coerced values.
			var child_docname = $btn.attr("data-child-docname") || $btn.closest("tr").attr("data-name") || undefined;

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

		// Earliest selectable delivery is tomorrow (next-day to JKIA).
		var min_offset = 1;
		var min_date = new Date();
		min_date.setDate(min_date.getDate() + min_offset);
		min_date.setHours(0, 0, 0, 0);

		var initial_value = $wrapper.data("initial-value") || "";

		// controls.bundle.js is included on this page, but on SPA navigation it is
		// pulled in asynchronously (a fresh <script src>), so make_control may not
		// exist yet when this runs. Wait briefly for it; only after it fails to
		// arrive do we fall back to the native <input type="date">. (On a hard load
		// the bundle is already parsed, so the first check passes immediately.)
		var has_make_control = function() {
			return !!(frappe.ui && frappe.ui.form && frappe.ui.form.make_control);
		};
		if (!has_make_control()) {
			var waited = 0;
			var wait = setInterval(function() {
				waited += 50;
				if (has_make_control()) {
					clearInterval(wait);
					shopping_cart.bind_delivery_date();   // re-enter now that it's ready
				} else if (waited >= 2000) {
					clearInterval(wait);
					// Bundle never arrived — keep the form usable with a native picker.
					if (!$wrapper.children().length) {
						shopping_cart._render_native_date_input($wrapper, initial_value, min_date, min_offset);
					}
				}
			}, 50);
			return;
		}

		// Idempotent: a prior native-fallback or control may already be mounted
		// (re-entry above, or an SPA re-init). Clear before re-mounting.
		$wrapper.empty();

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

			// Reject today (and earlier); earliest delivery is tomorrow.
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

		// Load all delivery points and render as select dropdown
		frappe.call({
			method: "upande_webshop.upande_webshop.shopping_cart.cart.search_delivery_points",
			args: { txt: "", limit: 500 },
			callback: function(r) {
				var rows = (r && r.message) || [];
				shopping_cart._render_delivery_point_select($wrapper, rows, initial_value);
			}
		});
	},

	_render_delivery_point_select: function($wrapper, options, initial_value) {
		var $select = $('<select class="form-control font-md"></select>');
		$select.append('<option value="">' + __("Select delivery point") + '</option>');
		
		options.forEach(function(opt) {
			$select.append('<option value="' + opt.value + '">' + (opt.label || opt.value) + '</option>');
		});
		
		if (initial_value) {
			$select.val(initial_value);
		}
		
		$wrapper.empty().append($select);
		
		$select.on("change", function() {
			var value = $(this).val() || "";
			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_delivery_point",
				args: { delivery_point: value },
			});
		});
	},
	// ---- End Delivery Point ----

	// ---- Consignee ----
	bind_consignee: function() {
		var $wrapper = $("#consignee-wrapper");
		if (!$wrapper.length) return;

		var initial_value = $wrapper.data("initial-value") || "";

		frappe.call({
			method: "upande_webshop.upande_webshop.shopping_cart.cart.search_consignees",
			args: { txt: "", limit: 500 },
			callback: function(r) {
				var rows = (r && r.message) || [];
				shopping_cart._render_consignee_select($wrapper, rows, initial_value);
			}
		});
	},

	_render_consignee_select: function($wrapper, options, initial_value) {
		var $select = $('<select class="form-control font-md"></select>');
		$select.append('<option value="">' + __("Select consignee") + '</option>');

		options.forEach(function(opt) {
			$select.append('<option value="' + opt.value + '">' + (opt.label || opt.value) + '</option>');
		});

		if (initial_value) {
			$select.val(initial_value);
		}

		$wrapper.empty().append($select);

		$select.on("change", function() {
			var value = $(this).val() || "";
			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_consignee",
				args: { consignee: value },
			});
		});
	},
	// ---- End Consignee ----

	// ---- Box Type ----
	bind_box_type: function() {
		var $wrapper = $("#box-type-wrapper");
		if (!$wrapper.length) return;

		var initial_value = $wrapper.data("initial-value") || "";

		// Load all box types and render as select dropdown
		frappe.call({
			method: "upande_webshop.upande_webshop.shopping_cart.cart.search_box_types",
			args: { txt: "", limit: 500 },
			callback: function(r) {
				var rows = (r && r.message) || [];
				shopping_cart._render_box_type_select($wrapper, rows, initial_value);
			}
		});
	},

	_render_box_type_select: function($wrapper, options, initial_value) {
		var $select = $('<select class="form-control font-md"></select>');
		$select.append('<option value="">' + __("Select box type") + '</option>');

		// box type name -> pack rate, so the inline label can update on change
		// without another round-trip to the server.
		var packrate_by_value = {};
		options.forEach(function(opt) {
			packrate_by_value[opt.value] = opt.packrate || "";
			$select.append('<option value="' + opt.value + '">' + (opt.label || opt.value) + '</option>');
		});

		if (initial_value) {
			$select.val(initial_value);
		}

		// Inline pack rate shown alongside the select once a box type is chosen.
		var $packrate = $('<span class="box-type-packrate text-muted small ml-2 text-nowrap"></span>');
		var render_packrate = function(value) {
			var rate = packrate_by_value[value];
			if (value && rate) {
				$packrate.text(__("Pack rate") + ": " + rate).show();
			} else {
				$packrate.text("").hide();
			}
		};

		var $row = $('<div class="d-flex align-items-center"></div>');
		$select.addClass("flex-grow-1");
		$row.append($select).append($packrate);
		$wrapper.empty().append($row);
		render_packrate($select.val() || "");

		$select.on("change", function() {
			var value = $(this).val() || "";
			render_packrate(value);
			$select.prop("disabled", true);
			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_box_type",
				args: { box_type: value },
				callback: function(r) {
					var m = r && r.message;
					if (m && m.items !== undefined) {
						// Swap the re-rendered cart fragments in place — no reload.
						$(".cart-items").html(m.items);
						$(".cart-tax-items").html(m.total);
						$(".payment-summary").html(m.taxes_and_totals);
						shopping_cart.set_cart_count();
					}
				},
				always: function() {
					$select.prop("disabled", false);
				},
			});
		});
	},
	// ---- End Box Type ----

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
				// Staff place orders on behalf of customers, so the customer-facing
				// /orders/<SO> portal page is permission-gated against them ("Not
				// Permitted"). Confirm the order and return to the storefront so
				// they can immediately place another.
				var so = r.message;
				frappe.show_alert(
					{
						message: __("Order {0} created.", [so]),
						indicator: "green",
					},
					8
				);
				setTimeout(function () {
					window.location.href = "/webshop";
				}, 1200);
			}
		});
	},

	request_quotation: function(btn) {
		var target = $(btn).attr("data-cart-target") || "sales_order";
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
				// Staff save orders on behalf of customers; the customer-facing
				// /orders/<SO> portal page is permission-gated against them
				// ("Not Permitted" / 403). Confirm and return to the storefront
				// so they can place another order immediately. (Mirrors place_order.)
				var so = r.message;
				frappe.show_alert(
					{
						message: __("Order {0} saved.", [so]),
						indicator: "green",
					},
					8
				);
				setTimeout(function () {
					window.location.href = "/webshop";
				}, 1200);
			}
		});
	},

	bind_coupon_code: function() {
		$(".bt-coupon").off("click.wsCoupon").on("click.wsCoupon", function() {
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
		$(".bt-remove-coupon-code").off("click.wsRemoveCoupon").on("click.wsRemoveCoupon", function() {
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