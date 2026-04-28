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
		shopping_cart.bind_drop_off_point();
	},

	bind_place_order: function() {
		$(".btn-place-order").on("click", function() {
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

	// ---- Drop-off Point ----
	bind_drop_off_point: function() {
		$("#drop-off-point").on("change", function() {
			var drop_off_point = $(this).val();
			frappe.call({
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart_drop_off_point",
				args: { drop_off_point: drop_off_point }
			});
		});
	},

	load_drop_off_points: function() {
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Delivery Point',
				fields: ['name', 'delivery_point'],
				limit_page_length: 100,
				order_by: 'name asc'
			},
			callback: function(r) {
				var current = $("#drop-off-point").data("current");
				var $select = $("#drop-off-point");
				$select.empty().append('<option value="">-- Select Drop-off Point --</option>');
				(r.message || []).forEach(function(p) {
					var label = p.delivery_point || p.name;
					var selected = p.name === current ? 'selected' : '';
					$select.append('<option value="' + p.name + '" ' + selected + '>' + label + '</option>');
				});
			}
		});
	},
	// ---- End Drop-off Point ----

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
	shopping_cart.load_drop_off_points();
});

function show_terms() {
	var html = $(".cart-terms").html();
	frappe.msgprint(html);
}