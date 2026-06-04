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
	$(document).on('click', 'a[href*="/logout"]', function(e) {
		e.preventDefault();
		// Honor ?redirect-to= on the logout link so Customer-only users land on /webshop
		// (set by the webshop nav dropdown) instead of /index.
		var href = $(this).attr('href') || '';
		var redirect_to = '/index';
		try {
			var qs = href.split('?')[1] || '';
			var match = qs.split('&').find(function(p) { return p.indexOf('redirect-to=') === 0; });
			if (match) redirect_to = decodeURIComponent(match.split('=')[1] || '/index');
		} catch (err) { /* keep default */ }
		frappe.call({ method: 'logout' }).then(function() {
			window.location.href = redirect_to;
		});
	});

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
		'/webshop', '/cart', '/invoices',
		'/orders', '/shipments', '/issues', '/contact', '/wishlist'
	];
	var is_webshop_page = webshop_prefixes.some(function(prefix) {
		return current_path === prefix || current_path.indexOf(prefix + '/') === 0;
	});
	var is_item_page = $('body').hasClass('product-page');
	var is_system_message_page = $('.error-page').length > 0;
	if ((is_webshop_page || is_item_page) && !is_system_message_page) {
		$('body').addClass('hide-frappe-navbar');
	}

	// Apply Full Width preference: the user's localStorage override wins over
	// the server-side Webshop Settings default. Mirrors the desk's
	// frappe.ui.toolbar.toggle_full_width: same key (container_fullwidth) and
	// same body class (full-width) so the choice carries desk ↔ webshop.
	var storedFullWidth = null;
	try {
		var raw = localStorage.getItem('container_fullwidth');
		if (raw !== null) storedFullWidth = JSON.parse(raw);
	} catch (e) { /* corrupt value — fall back to default */ }
	var fullWidthOn = (storedFullWidth === null)
		? !!window.webshop_full_width_default
		: !!storedFullWidth;
	$('body').toggleClass('full-width', fullWidthOn);

	if ((!is_webshop_page && !is_item_page) || is_system_message_page) {
		shopping_cart.inject_webshop_navbar = function() {};
		$('#webshop-subnav').remove();

		var observer = new MutationObserver(function(mutations) {
			mutations.forEach(function(m) {
				m.addedNodes.forEach(function(node) {
					if (node.id === 'webshop-subnav') {
						node.remove();
					} else if (node.querySelector && node.querySelector('#webshop-subnav')) {
						node.querySelector('#webshop-subnav').remove();
					}
				});
			});
		});
		observer.observe(document.body, { childList: true, subtree: true });
		return;
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

		var appLogo = '/assets/upande_webshop/images/UpandeLogo.png';
		var webshop_user_fullname = window.webshop_user_fullname || (frappe.session && frappe.session.user_fullname) || (frappe.session && frappe.session.user) || '';
		var webshop_user_initials = webshop_user_fullname.split(' ').filter(function(word) {
			return word;
		}).slice(0, 2).map(function(word) {
			return word[0];
		}).join('').toUpperCase() || 'U';
		var webshop_user_avatar = window.webshop_user_image
			? `<img src="${window.webshop_user_image}" alt="Account" style="width:28px;height:28px;border-radius:50%;object-fit:cover;vertical-align:middle;">`
			: `<span style="display:inline-flex;width:28px;height:28px;align-items:center;justify-content:center;border-radius:50%;background:#0d6efd;color:#fff;font-size:0.8rem;font-weight:600;line-height:1;">${webshop_user_initials}</span>`;
		var shopIconHtml = appLogo
			? `<img src="${appLogo}" class="webshop-subnav-app-logo" alt="Shop">`
			: `<svg xmlns="http://www.w3.org/2000/svg" style="width:20px;height:20px;vertical-align:middle;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/>
				<line x1="3" y1="6" x2="21" y2="6"/>
				<path d="M16 10a4 4 0 0 1-8 0"/>
			</svg>`;

		var poOnly = !!window.webshop_show_product_overview;
		var brandHref = poOnly ? '/product-overview' : '/webshop';
		var brandLabel = poOnly ? 'Product Overview' : 'Webshop';
		var logoutRedirect = poOnly ? '/product-overview' : '/webshop';
		var prefDropdown = `
			<li class="webshop-subnav-dropdown-divider"></li>
			<li><a href="#" class="webshop-subnav-dropdown-item" data-action="toggle-full-width">Toggle Full Width</a></li>
			<li><a href="#" class="webshop-subnav-dropdown-item" data-action="toggle-theme">Toggle Theme</a></li>
		`;
		var fullDropdown = `
			<li><a href="/webshop" class="webshop-subnav-dropdown-item">Products</a></li>
			${window.webshop_show_product_overview ? `<li><a href="/product-overview" class="webshop-subnav-dropdown-item">Product Overview</a></li>` : ``}
			<li><a href="/orders" class="webshop-subnav-dropdown-item">Orders</a></li>
			<li><a href="/invoices" class="webshop-subnav-dropdown-item">Invoices</a></li>
			<li><a href="/cart" class="webshop-subnav-dropdown-item">Cart</a></li>
			${window.webshop_show_bouquets_page ? `<li><a href="/bouquet" class="webshop-subnav-dropdown-item">Bouquet</a></li>` : ``}
			<li><a href="/wishlist" class="webshop-subnav-dropdown-item">Wishlist</a></li>
			<li><a href="/shipments" class="webshop-subnav-dropdown-item">Shipments</a></li>
			<li class="webshop-subnav-dropdown-divider"></li>
			<li><a href="/issues" class="webshop-subnav-dropdown-item">Issues</a></li>
			<li><a href="/contact" class="webshop-subnav-dropdown-item">Contact</a></li>
			<li class="webshop-subnav-dropdown-divider"></li>
			<li><a href="/webshop-setting" class="webshop-subnav-dropdown-item">Setting</a></li>
			${prefDropdown}
			<li class="webshop-subnav-dropdown-divider"></li>
			<li><a href="/logout?redirect-to=/webshop" class="webshop-subnav-dropdown-item">Logout</a></li>
		`;
		var poOnlyDropdown = `
			<li><a href="/product-overview" class="webshop-subnav-dropdown-item">Product Overview</a></li>
			<li class="webshop-subnav-dropdown-divider"></li>
			<li><a href="/webshop-setting" class="webshop-subnav-dropdown-item">Setting</a></li>
			${prefDropdown}
			<li class="webshop-subnav-dropdown-divider"></li>
			<li><a href="/logout?redirect-to=${logoutRedirect}" class="webshop-subnav-dropdown-item">Logout</a></li>
		`;
		var html = `
			<div id="webshop-subnav">
				<div class="webshop-subnav-inner">
					<!-- Left: App logo / Shop link -->
					<nav class="webshop-subnav-links">
						<a href="${brandHref}" class="webshop-subnav-link webshop-subnav-shop-link" title="${brandLabel}">
							${shopIconHtml}
							<span class="webshop-subnav-shop-label">${brandLabel}</span>
						</a>
					</nav>

					<!-- Right: Wishlist, Cart, Account -->
					<div class="webshop-subnav-right">
						${frappe.session.user && frappe.session.user !== 'Guest' ? `
						${poOnly ? `` : `
						<!-- Wishlist link -->
						<a href="/wishlist" class="webshop-subnav-cart-link wishlist-icon mr-3" aria-label="Wishlist" title="Wishlist">
							<svg xmlns="http://www.w3.org/2000/svg" style="width:20px;height:20px;vertical-align:middle;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
							</svg>
							${wishBadgeHtml}
						</a>

						<!-- Cart link -->
						<a href="/cart" class="webshop-subnav-cart-link cart-icon" aria-label="Cart" title="Cart">
							<svg class="icon icon-md" style="width:20px;height:20px;">
								<use href="#icon-assets"></use>
							</svg>
							${badgeHtml}
						</a>
						`}

						<!-- Account dropdown -->
						<div class="webshop-subnav-dropdown">
							<button class="webshop-subnav-link webshop-subnav-dropdown-toggle" id="ws-account-toggle" aria-expanded="false" aria-label="Account" title="Account">
								${webshop_user_avatar}
								<svg style="width:12px;height:12px;margin-left:4px;vertical-align:middle;" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<polyline points="4 6 8 10 12 6"/>
								</svg>
							</button>
							<ul class="webshop-subnav-dropdown-menu" id="ws-account-menu" role="menu">
								${poOnly ? poOnlyDropdown : fullDropdown}
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

		$(document).on('click', '#ws-account-menu [data-action="toggle-full-width"]', function(e) {
			e.preventDefault();
			$('#ws-account-menu').removeClass('open');
			$('#ws-account-toggle').attr('aria-expanded', 'false');
			// Emulate the desk's frappe.ui.toolbar.toggle_full_width: same
			// localStorage key, same body class, same custom event.
			if (frappe.ui && frappe.ui.toolbar && typeof frappe.ui.toolbar.toggle_full_width === 'function') {
				frappe.ui.toolbar.toggle_full_width();
				return;
			}
			var current = false;
			try { current = JSON.parse(localStorage.container_fullwidth || 'false'); } catch (err) {}
			var next = !current;
			try { localStorage.setItem('container_fullwidth', JSON.stringify(next)); } catch (err) {}
			$(document.body).toggleClass('full-width', next).trigger('toggleFullWidth');
		});

		$(document).on('click', '#ws-account-menu [data-action="toggle-theme"]', function(e) {
			e.preventDefault();
			$('#ws-account-menu').removeClass('open');
			$('#ws-account-toggle').attr('aria-expanded', 'false');
			// Emulate the desk's "Switch Theme" dialog: prefer the real one if
			// the desk bundle is loaded; otherwise show an equivalent 3-option
			// chooser (Light / Dark / Automatic) backed by the same
			// switch_theme xcall.
			if (frappe.ui && typeof frappe.ui.ThemeSwitcher === 'function') {
				if (frappe.theme_switcher && frappe.theme_switcher.dialog && frappe.theme_switcher.dialog.is_visible) {
					frappe.theme_switcher.hide();
				} else {
					frappe.theme_switcher = new frappe.ui.ThemeSwitcher();
					frappe.theme_switcher.show();
				}
				return;
			}
			shopping_cart.open_theme_switcher();
		});
	},

	open_theme_switcher: function() {
		var current = (document.documentElement.getAttribute('data-theme-mode') || 'light').toLowerCase();
		var themes = [
			{ name: 'light',     label: __('Frappe Light'),  info: __('Light Theme'),  swatch: '#ffffff' },
			{ name: 'dark',      label: __('Timeless Night'), info: __('Dark Theme'),  swatch: '#1f272e' },
			{ name: 'automatic', label: __('Automatic'),     info: __("Uses system's theme to switch between light and dark mode"), swatch: 'linear-gradient(135deg, #ffffff 50%, #1f272e 50%)' }
		];
		var $existing = $('#ws-theme-switcher');
		if ($existing.length) { $existing.remove(); }

		var tiles = themes.map(function(t) {
			var sel = t.name === current ? ' selected' : '';
			return (
				'<button type="button" class="ws-theme-tile' + sel + '" data-theme="' + t.name + '" title="' + frappe.utils.escape_html(t.info) + '">' +
					'<span class="ws-theme-swatch" style="background:' + t.swatch + ';"></span>' +
					'<span class="ws-theme-tile-label">' + frappe.utils.escape_html(t.label) + '</span>' +
				'</button>'
			);
		}).join('');

		var $modal = $(
			'<div id="ws-theme-switcher" class="po-modal-backdrop">' +
				'<div class="po-modal" style="max-width:520px;">' +
					'<div class="po-modal-header">' +
						'<h5 class="po-modal-title">' + __('Switch Theme') + '</h5>' +
						'<button type="button" class="po-modal-close" aria-label="Close">&times;</button>' +
					'</div>' +
					'<div class="po-modal-body">' +
						'<div class="ws-theme-grid">' + tiles + '</div>' +
					'</div>' +
				'</div>' +
			'</div>'
		).appendTo('body');

		function close() { $modal.remove(); }
		$modal.on('click', function(e) { if (e.target === $modal[0]) close(); });
		$modal.find('.po-modal-close').on('click', close);

		$modal.find('.ws-theme-tile').on('click', function() {
			var name = $(this).data('theme');
			$modal.find('.ws-theme-tile').removeClass('selected');
			$(this).addClass('selected');
			document.documentElement.setAttribute('data-theme-mode', name);
			if (frappe.ui && typeof frappe.ui.set_theme === 'function') {
				frappe.ui.set_theme(name === 'automatic' ? undefined : name);
			} else {
				var resolved = name;
				if (name === 'automatic' && window.matchMedia) {
					resolved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
				}
				document.documentElement.setAttribute('data-theme', resolved);
			}
			// Cache the choice client-side so the early head-init script can
			// apply it before paint on the next page load (no flash). Server
			// also gets it via switch_theme below for cross-device sync.
			try { localStorage.setItem('desk_theme_mode', name); } catch (e) {}
			frappe.show_alert && frappe.show_alert(__('Theme Changed'), 3);
			if (frappe.session && frappe.session.user && frappe.session.user !== 'Guest') {
				frappe.xcall('frappe.core.doctype.user.user.switch_theme', {
					theme: name.charAt(0).toUpperCase() + name.slice(1)
				}).catch(function() {});
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
			return frappe.call({
				type: "POST",
				method: "upande_webshop.upande_webshop.shopping_cart.cart.update_cart",
				args: {
					item_code: opts.item_code,
					qty: opts.qty,
					uom: opts.uom || undefined,
					custom_length: opts.custom_length || undefined,
					custom_box_type: opts.custom_box_type || opts.box_type || undefined,
					additional_notes: opts.additional_notes !== undefined ? opts.additional_notes : undefined,
					with_items: opts.with_items || 0,
					child_docname: opts.child_docname || undefined
				},
				btn: opts.btn,
				callback: function(r) {
					// Prefer the count returned in the response — avoids any cookie
					// propagation race and works even if the cookie isn't readable yet.
					var explicit_count = (r && r.message && r.message.cart_count != null)
						? r.message.cart_count
						: undefined;
					shopping_cart.set_cart_count(true, explicit_count);
					if(opts.callback)
						opts.callback(r);
				}
			});
		}
	},

	set_cart_count: function(animate=false, explicit_count=undefined) {
		$(".intermediate-empty-cart").remove();

		// explicit_count (when provided by an update_cart response) wins over the
		// cookie, since the cookie may lag a frame on some browsers.
		var cart_count = (explicit_count !== undefined)
			? explicit_count
			: frappe.get_cookie("cart_count");
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

	shopping_cart_update: function({item_code, qty, cart_dropdown, additional_notes, uom, custom_length, box_type, custom_box_type, child_docname}) {
		shopping_cart.update_cart({
			item_code,
			qty,
			additional_notes,
			uom,
			custom_length,
			custom_box_type: custom_box_type || box_type,
			child_docname,
			with_items: 1,
			btn: this,
			callback: function(r) {
				if (r.exc) {
					var msg = "";
					try {
						if (r._server_messages) {
							var parts = JSON.parse(r._server_messages) || [];
							msg = parts.map(function(p) {
								try { return (JSON.parse(p).message || "").replace(/<[^>]*>/g, ""); }
								catch(e) { return (p || "").toString().replace(/<[^>]*>/g, ""); }
							}).filter(Boolean).join(" ");
						}
					} catch (e) {}
					r._server_messages = null;
					frappe.show_alert({ message: msg || __("Could not update cart"), indicator: "red" }, 7);
					return;
				}
				$(".cart-items").html(r.message.items);
				$(".cart-tax-items").html(r.message.total);
				$(".payment-summary").html(r.message.taxes_and_totals);
				shopping_cart.set_cart_count();

				if (cart_dropdown != true) {
					$(".cart-icon").hide();
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

		frappe.call({
			method: "upande_webshop.upande_webshop.doctype.webshop_settings.webshop_settings.is_wishlist_enabled",
			callback: function(r) {
				if (!r.message) {
					$('#webshop-subnav .wishlist-icon').hide();
					$('#webshop-subnav .webshop-subnav-dropdown-item[href="/wishlist"]')
						.closest('li').hide();
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

			const item_code = $btn.data('item-code');
			upande_webshop.upande_webshop.shopping_cart.update_cart({
				item_code,
				qty: 1
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
