// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
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
			var row = input.closest("tr");
			var uom = row.attr("data-uom") || undefined;
			var custom_length = row.attr("data-custom-length") || undefined;
			var child_docname = row.attr("data-name") || undefined;
			shopping_cart.shopping_cart_update({item_code, qty: bunches, uom, custom_length, child_docname});
		});

		$(".cart-items").on('click', '.number-spinner button', function () {
			var btn = $(this),
				input = btn.closest('.number-spinner').find('input'),
				oldValue = parseInt(input.val().trim()) || 1,
				newVal = 0;

			if (btn.attr('data-dir') == 'up') {
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
			var child_docname = row.attr("data-name") || undefined;
			shopping_cart.shopping_cart_update({
				item_code,
				qty: newVal,
				uom,
				custom_length,
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

	// ---- Delivery Date & Shipment Date ----
	bind_delivery_date: function() {
		var $deliveryInput = $("#delivery-date");
		if (!$deliveryInput.length) return;

		// Set minimum date: today + transit_days
		var transit_days = parseInt($("#transit-days-label").text()) || 2;
		var min_date = new Date();
		min_date.setDate(min_date.getDate() + transit_days);
		$deliveryInput.attr("min", shopping_cart._format_date(min_date));

		// If a delivery date is already saved on the quotation, show shipment date
		if ($deliveryInput.val()) {
			shopping_cart._calculate_shipment_date($deliveryInput.val(), transit_days);
		}

		// Bind change event
		$deliveryInput.on("change", function() {
			var delivery_date = $(this).val();
			if (!delivery_date) {
				$("#shipment-date-display").text("—");
				return;
			}

			// Validate: delivery date must be at least transit_days from today
			var selected = new Date(delivery_date);
			var min_allowed = new Date();
			min_allowed.setDate(min_allowed.getDate() + transit_days);
			min_allowed.setHours(0, 0, 0, 0);

			if (selected < min_allowed) {
				frappe.show_alert({
					message: __('Expected delivery date must be at least {0} days from today (transit time).', [transit_days]),
					indicator: 'orange'
				}, 5);
				$(this).val("");
				$("#shipment-date-display").text("—");
				return;
			}

			// Show calculated shipment date immediately (client-side)
			shopping_cart._calculate_shipment_date(delivery_date, transit_days);

			// Save to server
			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_delivery_date",
				args: { delivery_date: delivery_date },
				callback: function(r) {
					if (r.message && r.message.shipment_date) {
						// Only update if server returned a valid date
						$("#shipment-date-display")
							.text(shopping_cart._display_date(r.message.shipment_date))
							.css("color", "var(--text-color)");
					}
					// Otherwise keep the client-side calculated value already showing
				}
			});
		});
	},

	_calculate_shipment_date: function(delivery_date, transit_days) {
		var d = new Date(delivery_date);
		d.setDate(d.getDate() - transit_days);
		var formatted = shopping_cart._display_date(shopping_cart._format_date(d));
		$("#shipment-date-display")
			.text(formatted)
			.css("color", "var(--text-color)");
	},

	_format_date: function(date) {
		// Returns YYYY-MM-DD
		var y = date.getFullYear();
		var m = String(date.getMonth() + 1).padStart(2, "0");
		var d = String(date.getDate()).padStart(2, "0");
		return y + "-" + m + "-" + d;
	},

	_display_date: function(date_str) {
		// Converts YYYY-MM-DD to "14 Mar 2026"
		if (!date_str) return "—";
		var parts = date_str.split("-");
		if (parts.length !== 3) return date_str;
		var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
		var day = parseInt(parts[2]);
		var month = months[parseInt(parts[1]) - 1];
		var year = parts[0];
		return day + " " + month + " " + year;
	},
	// ---- End Delivery Date & Shipment Date ----

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

	place_order: function(btn) {
		shopping_cart.freeze();

		return frappe.call({
			type: "POST",
			method: "upande_webshop.upande_webshop.shopping_cart.cart.place_order",
			btn: btn,
			callback: function(r) {
				if(r.exc) {
					shopping_cart.unfreeze();
					var msg = "";
					if(r._server_messages) {
						msg = JSON.parse(r._server_messages || []).join("<br>");
					}

					$("#cart-error")
						.empty()
						.html(msg || frappe._("Something went wrong!"))
						.toggle(true);
				} else {
					$(btn).hide();
					window.location.href = '/orders/' + encodeURIComponent(r.message);
				}
			}
		});
	},

	request_quotation: function(btn) {
		shopping_cart.freeze();

		return frappe.call({
			type: "POST",
			method: "upande_webshop.upande_webshop.shopping_cart.cart.request_for_quotation",
			btn: btn,
			callback: function(r) {
				if(r.exc) {
					shopping_cart.unfreeze();
					var msg = "";
					if(r._server_messages) {
						msg = JSON.parse(r._server_messages || []).join("<br>");
					}

					$("#cart-error")
						.empty()
						.html(msg || frappe._("Something went wrong!"))
						.toggle(true);
				} else {
					$(btn).hide();
					window.location.href = '/quotations/' + encodeURIComponent(r.message);
				}
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