// shopping cart
frappe.provide("upande_webshop.upande_webshop.shopping_cart");
var shopping_cart = upande_webshop.upande_webshop.shopping_cart;

var getParams = function (url) {
	var params = [];
	var parser = document.createElement('a');
	parser.href = url;
	var query = parser.search.substring(1);
	var vars = query.split('&');
	for (var i = 0; i < vars.length; i++) {
		var pair = vars[i].split('=');
		params[pair[0]] = decodeURIComponent(pair[1]);
	}
	return params;
};

frappe.ready(function() {
	var full_name = frappe.session && frappe.session.user_fullname;
	if(full_name) {
		$('.navbar li[data-label="User"] a')
			.html('<i class="fa fa-fixed-width fa fa-user"></i> ' + full_name);
	}

	var url_args = getParams(window.location.href);
	var referral_coupon_code = url_args['cc'];
	var referral_sales_partner = url_args['sp'];

	var d = new Date();
	d.setTime(d.getTime() + (0.02 * 24 * 60 * 60 * 1000));
	var expires = "expires="+d.toUTCString();
	if (referral_coupon_code) {
		document.cookie = "referral_coupon_code=" + referral_coupon_code + ";" + expires + ";path=/";
	}
	if (referral_sales_partner) {
		document.cookie = "referral_sales_partner=" + referral_sales_partner + ";" + expires + ";path=/";
	}
	referral_coupon_code=frappe.get_cookie("referral_coupon_code");
	referral_sales_partner=frappe.get_cookie("referral_sales_partner");

	if (referral_coupon_code && $(".tot_quotation_discount").val()==undefined ) {
		$(".txtcoupon").val(referral_coupon_code);
	}
	if (referral_sales_partner) {
		$(".txtreferral_sales_partner").val(referral_sales_partner);
	}

	var auth_paths = ['/login', '/logout', '/register', '/update-password', '/forgot-password'];
	var current_path = window.location.pathname.replace(/\/$/, '');
	var is_auth_page = auth_paths.some(function(p) {
		return current_path === p || current_path.indexOf(p + '/') === 0;
	});
	var is_base_url = current_path === '' || current_path === '/';

	if (is_auth_page || is_base_url) {
		if (localStorage) localStorage.removeItem('last_visited');
		if ($('#webshop-subnav').length) {
			$('#webshop-subnav').remove();
		}
		return;
	}

	var webshop_prefixes = [
		'/upande-webshop', '/cart', '/quotations', '/invoices',
		'/orders', '/shipments', '/issues', '/contact', '/wishlist'
	];
	var is_webshop_page = webshop_prefixes.some(function(prefix) {
		return current_path === prefix || current_path.indexOf(prefix + '/') === 0;
	});
	var is_item_page = $('body').hasClass('product-page');
	if (is_webshop_page || is_item_page) {
		$('body').addClass('hide-frappe-navbar');
	}

	shopping_cart.inject_webshop_navbar();
	shopping_cart.show_shoppingcart_dropdown();
	shopping_cart.set_cart_count();
	shopping_cart.show_cart_navbar();

	// Init wishlist count
	if (typeof webshop !== 'undefined' && webshop.webshop && webshop.webshop.wishlist) {
		webshop.webshop.wishlist.set_wishlist_count();
	}
});

$.extend(shopping_cart, {
	inject_webshop_navbar: function() {
		var auth_paths = ['/login', '/logout', '/register', '/update-password', '/forgot-password'];
		var current_path = window.location.pathname.replace(/\/$/, '');
		var is_auth_page = auth_paths.some(function(p) {
			return current_path === p || current_path.indexOf(p + '/') === 0;
		});
		var is_base_url = current_path === '' || current_path === '/';

		if (is_auth_page || is_base_url) {
			if ($('#webshop-subnav').length) {
				$('#webshop-subnav').remove();
			}
			return;
		}

		if ($('#webshop-subnav').length) return;

		var cartCount = frappe.get_cookie("cart_count");
		var badgeHtml = (cartCount && parseInt(cartCount) > 0)
			? `<span class="webshop-subnav-badge" id="cart-count">${cartCount}</span>`
			: `<span class="webshop-subnav-badge" id="cart-count" style="display:none;">${cartCount || 0}</span>`;

		var wishCount = frappe.get_cookie("wish_count");
		var wishBadgeHtml = (wishCount && parseInt(wishCount) > 0)
			? `<span class="webshop-subnav-badge" id="wish-count">${wishCount}</span>`
			: `<span class="webshop-subnav-badge" id="wish-count" style="display:none;">${wishCount || 0}</span>`;

		var appLogo = window.webshop_app_logo || (frappe.boot && frappe.boot.app_logo_url) || '';
		var shopIconHtml = appLogo
			? `<img src="${appLogo}" class="webshop-subnav-app-logo" alt="Shop">`
			: `<svg xmlns="http://www.w3.org/2000/svg" style="width:20px;height:20px;vertical-align:middle;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/>
					<line x1="3" y1="6" x2="21" y2="6"/>
					<path d="M16 10a4 4 0 0 1-8 0"/>
				</svg>`;

		var html = `
			<div id="webshop-subnav">
				<div class="webshop-subnav-inner">
					<!-- Left: App logo / Shop link -->
					<nav class="webshop-subnav-links">
						<a href="/upande-webshop" class="webshop-subnav-link webshop-subnav-shop-link" title="Shop">
							${shopIconHtml}
							<span class="webshop-subnav-shop-label">Upande Webshop</span>
						</a>
					</nav>

					<!-- Right: Wishlist, Cart, Account -->
					<div class="webshop-subnav-right">
						${frappe.session.user && frappe.session.user !== 'Guest' ? `
						<!-- Wishlist link -->
						<a href="/wishlist" class="webshop-subnav-cart-link wishlist-icon mr-3">
							<svg xmlns="http://www.w3.org/2000/svg" style="width:20px;height:20px;vertical-align:middle;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
							</svg>
							<span class="webshop-subnav-cart-label">Wishlist</span>
							${wishBadgeHtml}
						</a>

						<!-- Cart / Quote link -->
						<a href="/cart" class="webshop-subnav-cart-link cart-icon">
							<svg class="icon icon-md" style="width:20px;height:20px;">
								<use href="#icon-assets"></use>
							</svg>
							<span class="webshop-subnav-cart-label">Quote</span>
							${badgeHtml}
						</a>

						<!-- Account dropdown -->
						<div class="webshop-subnav-dropdown">
							<button class="webshop-subnav-link webshop-subnav-dropdown-toggle" id="ws-account-toggle" aria-expanded="false">
								Account
								<svg style="width:12px;height:12px;margin-left:4px;vertical-align:middle;" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<polyline points="4 6 8 10 12 6"/>
								</svg>
							</button>
							<ul class="webshop-subnav-dropdown-menu" id="ws-account-menu" role="menu">
								<li><a href="/upande-webshop" class="webshop-subnav-dropdown-item">Products</a></li>
								<li class="webshop-subnav-dropdown-divider"></li>
								<li><a href="/orders" class="webshop-subnav-dropdown-item">Orders</a></li>
								<li><a href="/quotations" class="webshop-subnav-dropdown-item">Quotations</a></li>
								<li><a href="/invoices" class="webshop-subnav-dropdown-item">Invoices</a></li>
								<li><a href="/cart" class="webshop-subnav-dropdown-item">Cart / Quote</a></li>
								<li><a href="/wishlist" class="webshop-subnav-dropdown-item">Wishlist</a></li>
								<li><a href="/shipments" class="webshop-subnav-dropdown-item">Shipments</a></li>
								<li><a href="/wishlist" class="webshop-subnav-dropdown-item">Wishlist</a></li>
								<li class="webshop-subnav-dropdown-divider"></li>
								<li><a href="/issues" class="webshop-subnav-dropdown-item">Issues</a></li>
								<li><a href="/contact" class="webshop-subnav-dropdown-item">Contact</a></li>
								<li class="webshop-subnav-dropdown-divider"></li>
								<li><a href="/logout?redirect-to=/upande-webshop" class="webshop-subnav-dropdown-item">Logout</a></li>
							</ul>
						</div>
						` : `
						<!-- Guest: show Login button -->
						<a href="/login" class="webshop-subnav-login-btn">Login</a>
						`}
					</div>
				</div>
			</div>
		`;

		var $header = $('header.navbar, nav.navbar').first();
		if ($header.length) {
			$header.after(html);
		} else {
			$('body').prepend(html);
		}

		$(document).on('click', '#ws-account-toggle', function(e) {
			e.stopPropagation();
			var $menu = $('#ws-account-menu');
			var isOpen = $menu.hasClass('open');
			$menu.toggleClass('open', !isOpen);
			$(this).attr('aria-expanded', !isOpen);
		});

		$(document).on('click.ws-subnav', function(e) {
			if (!$(e.target).closest('.webshop-subnav-dropdown').length) {
				$('#ws-account-menu').removeClass('open');
				$('#ws-account-toggle').attr('aria-expanded', 'false');
			}
		});
	},

	show_shoppingcart_dropdown: function() {
		$(".shopping-cart").on('shown.bs.dropdown', function() {
			if (!$('.shopping-cart-menu .cart-container').length) {
				return frappe.call({
					method: 'upande_webshop.upande_webshop.shopping_cart.cart.get_shopping_cart_menu',
					callback: function(r) {
						if (r.message) {
							$('.shopping-cart-menu').html(r.message);
						}
					}
				});
			}
		});
	},

	update_cart: function(opts) {
		if (frappe.session.user==="Guest") {
			if (localStorage) {
				localStorage.setItem("last_visited", window.location.pathname);
			}
			frappe.call('upande_webshop.upande_webshop.api.get_guest_redirect_on_action').then((res) => {
				window.location.href = res.message || "/login";
			});
		} else {
			shopping_cart.freeze();
			return frappe.call({
				type: "POST",
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart",
				args: {
					item_code: opts.item_code,
					qty: opts.qty,
					uom: opts.uom || undefined,
					custom_length: opts.custom_length || undefined,
					box_type: opts.box_type || undefined,
					additional_notes: opts.additional_notes !== undefined ? opts.additional_notes : undefined,
					with_items: opts.with_items || 0,
					child_docname: opts.child_docname || undefined
				},
				btn: opts.btn,
				callback: function(r) {
					shopping_cart.unfreeze();
					shopping_cart.set_cart_count(true);
					if(opts.callback)
						opts.callback(r);
				}
			});
		}
	},

	set_cart_count: function(animate=false) {
		$(".intermediate-empty-cart").remove();

		var cart_count = frappe.get_cookie("cart_count");
		if(frappe.session.user==="Guest") {
			cart_count = 0;
		}

		var $badge = $("#cart-count");
		var count = parseInt(cart_count) || 0;

		if(count === 0 || cart_count === undefined) {
			$badge.hide();
			$(".cart-tax-items").hide();
			$(".btn-place-order").hide();
			$(".cart-payment-addresses").hide();

			let intermediate_empty_cart_msg = `
				<div class="text-center w-100 intermediate-empty-cart mt-4 mb-4 text-muted">
					${ __("Cart is Empty") }
				</div>
			`;
			$(".cart-table").after(intermediate_empty_cart_msg);
		} else {
			$badge.text(count).show();

			if (animate) {
				var $cartLink = $badge.closest('.webshop-subnav-cart-link');
				$cartLink.addClass("cart-animate");
				setTimeout(() => {
					$cartLink.removeClass("cart-animate");
				}, 500);
			}
		}
	},

	shopping_cart_update: function({item_code, qty, cart_dropdown, additional_notes, uom, custom_length, box_type, child_docname}) {
		shopping_cart.update_cart({
			item_code,
			qty,
			additional_notes,
			uom,
			custom_length,
			box_type,
			child_docname,
			with_items: 1,
			btn: this,
			callback: function(r) {
				if(!r.exc) {
					$(".cart-items").html(r.message.items);
					$(".cart-tax-items").html(r.message.total);
					$(".payment-summary").html(r.message.taxes_and_totals);
					shopping_cart.set_cart_count();

					if (cart_dropdown != true) {
						$(".cart-icon").hide();
					}
				}
			},
		});
	},

	show_cart_navbar: function () {
		frappe.call({
			method: "upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings.is_cart_enabled",
			callback: function(r) {
				if (!r.message) {
					$('#webshop-subnav .webshop-subnav-cart').hide();
				}
			}
		});
	},

	toggle_button_class(button, remove, add) {
		button.removeClass(remove);
		button.addClass(add);
	},

	bind_add_to_cart_action() {
		$('.page_content').on('click', '.btn-add-to-cart-list', (e) => {
			const $btn = $(e.currentTarget);
			$btn.prop('disabled', true);

			if (frappe.session.user==="Guest") {
				if (localStorage) {
					localStorage.setItem("last_visited", window.location.pathname);
				}
				frappe.call('upande_webshop.upande_webshop.api.get_guest_redirect_on_action').then((res) => {
					window.location.href = res.message || "/login";
				});
				return;
			}

			$btn.addClass('hidden');
			$btn.closest('.cart-action-container').addClass('d-flex');
			$btn.parent().find('.go-to-cart').removeClass('hidden');
			$btn.parent().find('.go-to-cart-grid').removeClass('hidden');
			$btn.parent().find('.cart-indicator').removeClass('hidden');

			const item_code = $btn.data('item-code');
			upande_webshop.upande_webshop.shopping_cart.update_cart({
				item_code,
				qty: 1
			});
		});

		// Remove from quote via cart-indicator × button in grid view
		$('.page_content').on('click', '.remove-from-cart-grid', (e) => {
			e.preventDefault();
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			const item_code = $btn.data('item-code');
			upande_webshop.upande_webshop.shopping_cart.update_cart({
				item_code,
				qty: 0,
				callback: function(r) {
					if (!r.exc) {
						$btn.closest('.cart-indicator').addClass('hidden');
						shopping_cart.set_cart_count();
					}
				}
			});
		});
	},

	freeze() {
		if (window.location.pathname !== "/cart") return;

		if (!$('#freeze').length) {
			let freeze = $('<div id="freeze" class="modal-backdrop fade"></div>')
				.appendTo("body");

			setTimeout(function() {
				freeze.addClass("show");
			}, 1);
		} else {
			$("#freeze").addClass("show");
		}
	},

	unfreeze() {
		if ($('#freeze').length) {
			let freeze = $('#freeze').removeClass("show");
			setTimeout(function() {
				freeze.remove();
			}, 1);
		}
	}
});
