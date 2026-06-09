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
	// Frappe's "home page" fallback renders at both the bare URL and /index — treat
	// them the same. /index is the generic "My Account" portal page; it is NOT a
	// webshop page and must carry no webshop chrome.
	var is_base_url = current_path === '' || current_path === '/' || current_path === '/index';

	if (is_auth_page || is_base_url) {
		if (localStorage) localStorage.removeItem('last_visited');
	}

	// On /index and the base URL the website still renders Frappe's top navbar with
	// the "Webshop" brand. These are not webshop pages, so hide that bar entirely
	// (no subnav, no Frappe navbar). Uses hide-website-navbar — NOT hide-frappe-navbar,
	// which reserves 44px for a subnav that isn't present here.
	if (is_base_url) {
		$('body').addClass('hide-website-navbar');
	}

	// Allowlist of routes that wear the webshop chrome lives on shopping_cart
	// (see $.extend below) so it's the single source of truth shared with
	// inject_webshop_navbar's is_webshop_path() guard.
	var webshop_prefixes = shopping_cart.webshop_prefixes;
	// An exact-path or path-prefix match against the allowlist. Auth pages and the
	// base URL are never webshop pages even if they happen to share a prefix.
	var is_webshop_page = !is_auth_page && !is_base_url && webshop_prefixes.some(function(prefix) {
		return current_path === prefix || current_path.indexOf(prefix + '/') === 0;
	});
	var is_item_page = !is_auth_page && !is_base_url && $('body').hasClass('product-page');
	var is_system_message_page = $('.error-page').length > 0;

	// Some webshop-prefixed routes are actually GENERIC Frappe portal pages, not
	// webshop-templated ones: the Issue doctype web views (/issues/list,
	// /issues/new, /issues/<name>) render Frappe's standard web-list (.website-list)
	// or web-form (.web-form-container); /contact is Frappe's built-in contact page.
	// They render Frappe's native list/form markup, which BREAKS under webshop
	// full-width — but they should still wear the webshop CHROME (our dark subnav,
	// no mismatched white Frappe navbar) so they don't look like a different site.
	// So: give them the webshop subnav + hide the Frappe navbar like every other
	// webshop page, but keep their NATIVE container width (never full-width).
	var is_generic_portal_page = $('.website-list').length > 0
		|| $('.web-form-container').length > 0
		|| $('.web-list-container').length > 0;

	if ((is_webshop_page || is_item_page) && !is_system_message_page) {
		$('body').addClass('hide-frappe-navbar');
	}

	// Generic Frappe portal pages (Issue list/form, etc.) suppress the breadcrumb
	// server-side: the Issue doctype's get_list_context sets `no_breadcrumbs: True`,
	// and the web-list template hard-empties {% block breadcrumbs %}. Neither is
	// reliably overridable from our context hook, so inject a "Home › <Page>" trail
	// client-side to match the other webshop pages. Idempotent: skips if a
	// breadcrumb already renders.
	if (is_generic_portal_page && !is_system_message_page) {
		shopping_cart.inject_portal_breadcrumb();
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
	// Only apply webshop full-width to actual webshop/item pages. Generic Frappe
	// portal pages (issue list/form, contact) keep their native container width —
	// forcing full-width on them distorts the layout. They still get the webshop
	// subnav + hidden Frappe navbar above; only full-width is withheld.
	$('body').toggleClass('full-width',
		fullWidthOn && (is_webshop_page || is_item_page) && !is_generic_portal_page);

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
	shopping_cart.init_spa_nav();

	// Init wishlist count
	if (typeof webshop !== 'undefined' && webshop.webshop && webshop.webshop.wishlist) {
		webshop.webshop.wishlist.set_wishlist_count();
	}
});

$.extend(shopping_cart, {
	// Single source of truth for which routes wear the webshop chrome. Every page
	// the subnav links to MUST appear here. Keep in sync with the dropdown links
	// built in inject_webshop_navbar (fullDropdown). frappe.ready() reads this too.
	webshop_prefixes: [
		'/webshop', '/cart', '/invoices',
		'/orders', '/shipments', '/issues', '/contact', '/wishlist',
		'/bouquet', '/webshop-setting', '/webshop-setup'
	],

	// ── SPA-style navigation for the webshop subnav ──────────────────────────
	// The account-menu items (Products/Orders/Invoices/Cart/Wishlist/…) are
	// separate server-rendered pages. Clicking them normally does a full document
	// reload (white flash, navbar re-injects). Instead we intercept the click,
	// fetch the target page, swap only the .page-content-wrapper, re-execute the
	// fetched page's <script>/<style> tags, re-fire frappe.ready (many pages
	// bootstrap there), and pushState — so the subnav never reloads.
	//
	// Why this is safe-ish: the subnav (#webshop-subnav) and the delegated
	// $(document).on(...) handlers live OUTSIDE .page-content-wrapper, so they
	// survive the swap and don't double-bind. Per-page bootstrapping comes back
	// via re-running scripts + re-firing frappe.ready.
	_spa: { busy: false, seen_assets: null },

	init_spa_nav: function() {
		var self = shopping_cart;
		if (self._spa.bound) return;            // guard: bind once per document
		self._spa.bound = true;
		self._spa.seen_assets = {};             // track already-loaded external src/href

		// Only intercept same-origin internal webshop links — skip logout, auth,
		// data-action toggles, new-tab/modified clicks, downloads and externals.
		$(document).on('click', '#webshop-subnav a[href]', function(e) {
			var $a = $(this);
			var href = $a.attr('href') || '';
			// Let toggles, logout, anchors and external/new-tab clicks pass through.
			if ($a.attr('data-action')) return;
			if ($a.attr('target') === '_blank') return;
			if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.which === 2) return;
			if (!href || href.charAt(0) === '#') return;
			if (/^https?:\/\//i.test(href) && href.indexOf(window.location.origin) !== 0) return;
			if (/\/logout(\?|$)/.test(href) || /\/login(\?|$)/.test(href)) return;
			// /issues and /contact are GENERIC Frappe portal pages (Issue doctype
			// web list/form; Frappe's built-in contact page), not webshop-templated.
			// SPA-swapping them into the webshop chrome strips their navbar/layout
			// and breaks their CSS (e.g. /issues/list). Let them navigate normally
			// so the server renders them with their own full Frappe layout + JS.
			if (/^\/issues(\/|$)/.test(href) || /^\/contact(\/|$)/.test(href)) return;

			e.preventDefault();
			$('#ws-account-menu').removeClass('open');
			$('#ws-account-toggle').attr('aria-expanded', 'false');

			// Same-page click (e.g. the Webshop brand while already on the products
			// listing): a full SPA re-fetch + grid re-bootstrap is both wasteful and
			// fragile — it has been wiping the listing. If we're on the products page
			// and a live ProductView exists, just reset filters/search in place.
			var here = window.location.pathname.replace(/\/$/, '');
			var target = (this.pathname || '').replace(/\/$/, '');
			var targetHasQuery = href.indexOf('?') !== -1;
			if (target === here && !targetHasQuery
				&& typeof webshop !== 'undefined' && webshop.product_view
				&& typeof webshop.product_view.make === 'function') {
				// Drop any active filters/search by clearing the query string, then
				// re-render the listing through the existing ProductView.
				if (window.location.search && window.history && history.replaceState) {
					history.replaceState({ ws_spa: true }, '', window.location.pathname);
				}
				$('#search-box').val('');
				$('.filters-section input[type="checkbox"]:checked').prop('checked', false);
				$('.filters-section .filter-lookup-input').val('');
				webshop.product_view.from_filters = false;
				webshop.product_view.make();
				return;
			}

			self.spa_navigate(href, true);
		});

		// Back/forward: re-fetch the popped URL (no reload).
		window.addEventListener('popstate', function(ev) {
			if (ev.state && ev.state.ws_spa) {
				self.spa_navigate(window.location.pathname + window.location.search, false);
			}
		});

		// Seed history so the first back press has a state to restore.
		try { history.replaceState({ ws_spa: true }, '', window.location.href); } catch (err) {}
	},

	spa_navigate: function(url, push) {
		var self = shopping_cart;
		if (self._spa.busy) return;
		self._spa.busy = true;

		var $wrapper = $('.page-content-wrapper').first();
		if (!$wrapper.length) {                 // nothing to swap into → hard nav
			window.location.href = url;
			return;
		}
		$wrapper.css('opacity', '0.4');         // light visual cue while fetching

		$.ajax({ url: url, method: 'GET', dataType: 'html' })
			.done(function(html) {
				try {
					self._spa_apply(html, url, push);
				} catch (err) {
					// Any failure → fall back to a real navigation so the user is
					// never stuck on a half-swapped page.
					console.error('SPA navigation failed, falling back to reload', err);
					window.location.href = url;
					return;
				}
				$wrapper.css('opacity', '');
				self._spa.busy = false;
			})
			.fail(function() {
				// Network/permission error → hard nav (lets the server show its
				// own login redirect / error page).
				window.location.href = url;
			});
	},

	_spa_apply: function(html, url, push) {
		var self = shopping_cart;
		var doc = new DOMParser().parseFromString(html, 'text/html');

		var $new = $(doc).find('.page-content-wrapper').first();
		if (!$new.length) throw new Error('no .page-content-wrapper in response');

		// 1) Swap the content region (breadcrumbs + header + page_content + footer).
		var $old = $('.page-content-wrapper').first();
		$old.html($new.html());

		// 2) Update the document title + the data-path/id on the page container so
		//    page JS that keys off window.location / data-path behaves correctly.
		var newTitle = (doc.querySelector('title') || {}).textContent;
		if (newTitle) document.title = newTitle;

		// 2b) The page-scoped container id (`#page-index`, `#page-cart`, …) lives on
		//     an ancestor of .page-content-wrapper, so the innerHTML swap above does
		//     NOT update it — it keeps the *origin* page's id. Page CSS keys off this
		//     id (e.g. `#page-index .webshop-row #product-listing #products-grid-area`
		//     gives the grid its scroll height); a stale id silently collapses the
		//     listing to zero height and the grid "disappears". Copy the id and
		//     data-path from the fetched document onto the current container.
		try {
			var $oldContainer = $old.closest('[id^="page-"]');
			var newContainerEl = doc.querySelector('.page-content-wrapper');
			var $newContainer = newContainerEl
				? $(newContainerEl).closest('[id^="page-"]')
				: $();
			if ($oldContainer.length && $newContainer.length) {
				$oldContainer.attr('id', $newContainer.attr('id'));
				var newPath = $newContainer.attr('data-path');
				if (newPath != null) $oldContainer.attr('data-path', newPath);
			}
		} catch (e) { console.error('SPA container-id sync failed', e); }

		// 2c) Sync the <body> class from the fetched page. Pages set body_class
		//     server-side (cart.py → "product-page", product pages → "product-page",
		//     etc.) and key CSS off it (webshop_cart.scss scopes the whole cart
		//     layout under `body.product-page`). The innerHTML swap never touches
		//     <body>, so without this the destination page keeps the *origin*
		//     page's body class and its styles silently don't apply until a hard
		//     refresh. Preserve the runtime-toggled classes the SPA owns itself
		//     (full-width, theme) — those are driven by localStorage, not the
		//     fetched HTML, and would flicker/reset if we clobbered them.
		try {
			var preserved = ['full-width', 'hide-frappe-navbar'];
			var keep = preserved.filter(function(c) { return document.body.classList.contains(c); });
			var newBody = doc.body;
			var newClass = (newBody && newBody.getAttribute('class')) || '';
			document.body.setAttribute('class', newClass);
			keep.forEach(function(c) { document.body.classList.add(c); });
		} catch (e) { console.error('SPA body-class sync failed', e); }

		// 3) pushState BEFORE running scripts so any script reading location sees
		//    the new URL.
		if (push) {
			history.pushState({ ws_spa: true }, newTitle || '', url);
		}

		// 4) Pull in any <link rel=stylesheet> / external <script src> the new page
		//    needs that the current document doesn't already have (load once).
		self._spa_load_assets(doc);

		// 5) Re-execute the new page's inline scripts. There are TWO locations:
		//    (a) inside .page_content (page-body inline <script> blocks), and
		//    (b) the page-companion JS Frappe injects via {% block script %}, which
		//        renders at the END of <body> — OUTSIDE .page-content-wrapper (e.g.
		//        cart.js, order.js, wishlist bindings, www/webshop/index.js). Setting
		//        innerHTML never executes <script>, and (b) isn't even in the swapped
		//        region, so we collect every inline <script> in the FETCHED <body>
		//        and re-run it. External src scripts are handled (deduped) in step 4;
		//        the head theme-init script is in <head> so it's excluded here.
		// Snapshot how many ready callbacks exist BEFORE we re-run the page's
		// scripts, so step 6 can fire ONLY the ones this page just registered.
		var readyBefore = (frappe && Array.isArray(frappe.ready_events))
			? frappe.ready_events.length : 0;

		self._spa_run_body_scripts(doc);

		// 6) Run the page's own frappe.ready callbacks. Webshop pages bootstrap via
		//    frappe.ready(fn) (cart.js → bind_events, order.js, item configurator…).
		//    Whether frappe.ready runs fn immediately post-load is version-dependent
		//    and unreliable — relying on it left the cart's × / qty handlers unbound
		//    after an SPA swap. So we explicitly run the callbacks that step 5 just
		//    PUSHED (the slice past readyBefore), and only those — never the whole
		//    historical queue, which would re-run unrelated apps' + this file's
		//    one-time setup and double-init the page. Page bind_*() are made
		//    idempotent (.off().on()) so a double-run can't stack handlers.
		self._spa_run_new_ready(readyBefore);

		// Re-bind Frappe's idempotent post-content UI helpers (dropdowns, code
		// highlighting) — mirrors the safe parts of website.js's page-change.
		self._spa_after_swap();

		// NOTE: we do NOT separately re-instantiate the product listing here.
		// www/webshop/index.js is INLINED into the page's {% block script %}
		// (verified: `new ProductListing()` appears inline in the rendered page,
		// not as an external src), so step 5's _spa_run_body_scripts already
		// re-runs its `$(() => new ProductListing())` — which, post-DOMReady,
		// jQuery executes immediately, rebuilding exactly one ProductView. An
		// extra instance here was creating a SECOND ProductView with its own
		// bind_paging_action handler, so Prev/Next fired twice and the duplicate
		// render overwrote the paged grid (URL went to ?start=N but page 1 showed).

		// 6c) Re-bind the cart's delivery-schedule controls. Like the product
		//     listing, cart.js is inlined and step 5/6 re-run its frappe.ready —
		//     but that path proved unreliable for the cart specifically (the
		//     delivery-date/point/consignee/box-type controls came back unbound,
		//     leaving only their labels). Those binds are JS-built (AJAX <select>
		//     + a date control) and idempotent (.empty()/.off().on()), so an
		//     explicit re-run here is safe and guarantees the fields populate
		//     after an SPA swap regardless of frappe.ready firing semantics.
		self._spa_init_cart();

		// 7) Re-apply our own subnav-dependent bits (cart/wish counts come from
		//    cookies the new page may have refreshed).
		self.set_cart_count();
		if (typeof webshop !== 'undefined' && webshop.webshop && webshop.webshop.wishlist) {
			webshop.webshop.wishlist.set_wishlist_count();
		}

		// 8) Scroll to top like a real navigation.
		window.scrollTo(0, 0);
	},

	_spa_init_cart: function() {
		// Only the /cart page carries the cart container + delivery-schedule
		// wrappers. If they aren't present, this isn't the cart — nothing to do.
		if (!$('.cart-container').length) return;
		if (typeof shopping_cart.bind_events !== 'function') return;
		try {
			shopping_cart.parent = $('.cart-container');
			shopping_cart.bind_events();
		} catch (err) {
			console.error('SPA cart re-init failed', err);
		}
	},

	_spa_run_body_scripts: function(doc) {
		// Run every inline <script> in the fetched <body>, in document order, by
		// re-creating each as a fresh <script> appended to the live <body> (the
		// only way to make injected script text execute). Skips src scripts
		// (handled in _spa_load_assets). Idempotent for our pages: their bodies
		// register via frappe.ready(fn)/define-then-call, which re-run cleanly.
		var body = doc.body;
		if (!body) return;
		var inline = Array.prototype.filter.call(
			body.querySelectorAll('script'),
			function(s) { return !s.getAttribute('src'); }
		);
		inline.forEach(function(orig) {
			var s = document.createElement('script');
			if (orig.type) s.type = orig.type;
			s.text = orig.textContent;
			document.body.appendChild(s);
			// Remove the just-run node so repeated navigations don't pile up inert
			// <script> tags at the end of <body>.
			s.parentNode.removeChild(s);
		});
	},

	_spa_load_assets: function(doc) {
		var self = shopping_cart;
		// Stylesheets (external <link rel=stylesheet>)
		Array.prototype.forEach.call(doc.querySelectorAll('link[rel="stylesheet"][href]'), function(l) {
			var href = l.getAttribute('href');
			if (!href || self._spa.seen_assets['css:' + href]) return;
			if (document.querySelector('link[rel="stylesheet"][href="' + href + '"]')) {
				self._spa.seen_assets['css:' + href] = true; return;
			}
			self._spa.seen_assets['css:' + href] = true;
			var link = document.createElement('link');
			link.rel = 'stylesheet'; link.href = href;
			document.head.appendChild(link);
		});

		// Inline <style> blocks injected into the fetched page's <head> via
		// {% block head_include %} (e.g. /bouquet's .bouquet-grid styles). These
		// live OUTSIDE .page-content-wrapper, so the content swap never brings them
		// in — the page would render unstyled after an SPA navigation. Adopt each
		// once (deduped by content) so the styling is present, and persists for
		// later pages (harmless — they're scoped by their own selectors).
		// NB: <style> inside .page_content IS applied by the innerHTML swap, so we
		// only need the ones in <head> here.
		if (doc.head) {
			Array.prototype.forEach.call(doc.head.querySelectorAll('style'), function(st) {
				var css = st.textContent || '';
				if (!css.trim()) return;
				var key = 'style:' + css.length + ':' + css.slice(0, 80);
				if (self._spa.seen_assets[key]) return;
				self._spa.seen_assets[key] = true;
				var s = document.createElement('style');
				s.setAttribute('data-ws-spa-style', '1');
				s.textContent = css;
				document.head.appendChild(s);
			});
		}
		// External scripts (e.g. controls.bundle on the cart page). Load once,
		// in order; their global side-effects then exist for the inline scripts.
		Array.prototype.forEach.call(doc.querySelectorAll('script[src]'), function(sc) {
			var src = sc.getAttribute('src');
			if (!src || self._spa.seen_assets['js:' + src]) return;
			if (document.querySelector('script[src="' + src + '"]')) {
				self._spa.seen_assets['js:' + src] = true; return;
			}
			self._spa.seen_assets['js:' + src] = true;
			var s = document.createElement('script');
			s.src = src; s.async = false;
			document.head.appendChild(s);
		});
	},

	_spa_run_new_ready: function(readyBefore) {
		// Fire the frappe.ready callbacks registered by the page scripts we just
		// re-ran (everything pushed past the pre-swap baseline). These are THIS
		// page's bootstraps; running them binds the swapped-in DOM (cart × / qty,
		// delivery controls, item configurator, etc.). We slice rather than call
		// frappe.trigger_ready() so we never re-run the historical queue.
		try {
			if (!(frappe && Array.isArray(frappe.ready_events))) return;
			var added = frappe.ready_events.slice(readyBefore);
			added.forEach(function(fn) {
				try { fn(); } catch (e) { console.error('SPA ready callback error', e); }
			});
		} catch (e) { console.error('SPA run-new-ready error', e); }
	},

	_spa_after_swap: function() {
		// Re-bind Frappe's idempotent post-content UI helpers WITHOUT re-running
		// the ready_events queue (frappe.trigger_ready) — see step 6. These mirror
		// the safe parts of website.js's page-change handler: re-activate Bootstrap
		// dropdowns and re-highlight any code blocks in the new content. They no-op
		// if there's nothing to bind, so they can't double-init.
		try {
			if ($.fn.dropdown) $('.dropdown-toggle').dropdown();
			if (typeof frappe.highlight_code_blocks === 'function') frappe.highlight_code_blocks();
		} catch (e) { console.error('SPA after-swap rebind error', e); }
	},

	// Decide whether the current path is allowed to wear the webshop subnav. This
	// is the SAME allowlist gate frappe.ready() uses; inject_webshop_navbar calls
	// it too so the subnav can never paint on an off-list path, no matter who calls
	// the injector (initial load, SPA swap, async).
	is_webshop_path: function() {
		var auth_paths = ['/login', '/logout', '/register', '/update-password', '/forgot-password'];
		var current_path = window.location.pathname.replace(/\/$/, '');
		var is_auth_page = auth_paths.some(function(p) {
			return current_path === p || current_path.indexOf(p + '/') === 0;
		});
		var is_base_url = current_path === '' || current_path === '/';
		if (is_auth_page || is_base_url) return false;

		var prefixes = shopping_cart.webshop_prefixes || [];
		var is_prefix_match = prefixes.some(function(prefix) {
			return current_path === prefix || current_path.indexOf(prefix + '/') === 0;
		});
		var is_item_page = $('body').hasClass('product-page');
		return is_prefix_match || is_item_page;
	},

	inject_portal_breadcrumb: function() {
		// Render a "Home › <Page>" breadcrumb on generic Frappe portal pages
		// (Issue list, etc.) that suppress it server-side, so they match the rest
		// of the webshop. Idempotent and defensive.
		try {
			var $wrapper = $('.page-content-wrapper').first();
			if (!$wrapper.length) return;
			// Already has a (non-empty) breadcrumb? Leave it.
			if ($wrapper.find('.breadcrumb-container .breadcrumb-item').length) return;
			if ($('#ws-portal-breadcrumb').length) return;   // our own, already added

			// Page label: prefer the page heading, else derive from the path.
			var label = '';
			var $h = $wrapper.find('h1, h3.my-account-header, .web-list-title h1').first();
			if ($h.length) label = ($h.text() || '').trim();
			if (!label) {
				var seg = (window.location.pathname.replace(/\/(list|new)\/?$/, '')
					.split('/').filter(Boolean).pop() || '').replace(/[-_]/g, ' ');
				label = seg ? seg.charAt(0).toUpperCase() + seg.slice(1) : '';
			}
			if (!label) return;

			var html =
				'<div id="ws-portal-breadcrumb" class="page-breadcrumbs">' +
					'<div class="breadcrumb-container container">' +
						'<nav aria-label="breadcrumb"><ol class="breadcrumb">' +
							'<li class="breadcrumb-item"><a href="/webshop">' + __('Home') + '</a></li>' +
							'<li class="breadcrumb-item active" aria-current="page"><span>' +
								frappe.utils.escape_html(label) + '</span></li>' +
						'</ol></nav>' +
					'</div>' +
				'</div>';
			$wrapper.prepend(html);
		} catch (e) { console.error('portal breadcrumb inject failed', e); }
	},

	inject_webshop_navbar: function() {
		// Only the allowlisted webshop paths (+ product pages) get the subnav.
		if (!shopping_cart.is_webshop_path()) {
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

		var brandHref = '/webshop';
		var brandLabel = 'Webshop';
		var prefDropdown = `
			<li class="webshop-subnav-dropdown-divider"></li>
			<li><a href="#" class="webshop-subnav-dropdown-item" data-action="toggle-full-width">Toggle Full Width</a></li>
			<li><a href="#" class="webshop-subnav-dropdown-item" data-action="toggle-theme">Toggle Theme</a></li>
		`;
		var fullDropdown = `
			<li><a href="/webshop" class="webshop-subnav-dropdown-item">Products</a></li>
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

						<!-- Account dropdown -->
						<div class="webshop-subnav-dropdown">
							<button class="webshop-subnav-link webshop-subnav-dropdown-toggle" id="ws-account-toggle" aria-expanded="false" aria-label="Account" title="Account">
								${webshop_user_avatar}
								<svg style="width:12px;height:12px;margin-left:4px;vertical-align:middle;" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<polyline points="4 6 8 10 12 6"/>
								</svg>
							</button>
							<ul class="webshop-subnav-dropdown-menu" id="ws-account-menu" role="menu">
								${fullDropdown}
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
			// Always use our own two-option (Light / Dark) chooser. The desk's
			// real ThemeSwitcher offers Frappe Light / Timeless Night / Automatic
			// which we don't want here.
			shopping_cart.open_theme_switcher();
		});

		// NOTE: the brand "Webshop" link (.webshop-subnav-shop-link) is handled by
		// the SPA navigation interceptor (init_spa_nav) like every other subnav
		// link — it fetches /webshop and swaps content in place (no full reload).
		// The swapped-in page's inlined index.js (`$(() => new ProductListing())`)
		// re-runs via _spa_run_body_scripts and rebuilds the grid. A clean /webshop
		// href naturally drops any active filters/search, so clicking the brand
		// lands you on a fresh products home. No separate handler needed.
	},

	open_theme_switcher: function() {
		var current = (document.documentElement.getAttribute('data-theme-mode') || 'light').toLowerCase();
		var themes = [
			{ name: 'light', label: __('Light'), info: __('Light Theme'), swatch: '#ffffff' },
			{ name: 'dark',  label: __('Dark'),  info: __('Dark Theme'),  swatch: '#1f272e' }
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
				'<div class="po-modal" style="max-width:340px;">' +
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
