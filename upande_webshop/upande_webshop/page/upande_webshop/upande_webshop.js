frappe.pages['upande_webshop'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Upande Webshop',
		single_column: true
	});

	new UpandeWebshopPage(page, wrapper);
};

class UpandeWebshopPage {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.field_filters = {};
		this.attribute_filters = {};
		this.start = 0;
		this.items_count = 0;
		this.preference = localStorage.getItem('upande_webshop_view') || 'Grid View';
		this.search_term = '';

		this.setup_layout();
		this.load_products();
	}

	setup_layout() {
		$(this.wrapper).find('.page-content').html(`
			<style>
				.upande-webshop-container .ws-item-card {
					transition: box-shadow 0.2s;
					cursor: pointer;
				}
				.upande-webshop-container .ws-item-card:hover {
					box-shadow: var(--shadow-md);
				}
				.upande-webshop-container .ws-item-image {
					height: 180px;
					object-fit: cover;
					width: 100%;
				}
				.upande-webshop-container .ws-no-image {
					height: 180px;
					background: var(--bg-light-gray);
					display: flex;
					align-items: center;
					justify-content: center;
					font-size: 2rem;
					font-weight: bold;
					color: var(--text-muted);
				}
				.upande-webshop-container .ws-list-image {
					height: 80px;
					width: 80px;
					object-fit: cover;
					border-radius: var(--border-radius);
					flex-shrink: 0;
				}
				.upande-webshop-container .ws-list-no-image {
					height: 80px;
					width: 80px;
					background: var(--bg-light-gray);
					border-radius: var(--border-radius);
					display: flex;
					align-items: center;
					justify-content: center;
					font-weight: bold;
					color: var(--text-muted);
					flex-shrink: 0;
				}
				.upande-webshop-container .filter-block {
					padding-bottom: 12px;
					border-bottom: 1px solid var(--border-color);
					margin-bottom: 12px;
				}
				.upande-webshop-container .filter-label {
					font-size: 11px;
					text-transform: uppercase;
					font-weight: 600;
					letter-spacing: 0.5px;
					color: var(--text-muted);
					margin-bottom: 8px;
				}
				.upande-webshop-container .hidden {
					display: none !important;
				}
			</style>

			<div class="upande-webshop-container">
				<!-- Toolbar -->
				<div class="d-flex align-items-center mb-4" style="gap: 10px; flex-wrap: wrap;">
					<div class="input-group" style="flex: 1; max-width: 400px;">
						<input type="search" id="ws-search-box" class="form-control"
							placeholder="${__('Search for Products')}">
						<div class="input-group-append">
							<span class="input-group-text">
								<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
									viewBox="0 0 24 24" fill="none" stroke="currentColor"
									stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<circle cx="11" cy="11" r="8"></circle>
									<line x1="21" y1="21" x2="16.65" y2="16.65"></line>
								</svg>
							</span>
						</div>
					</div>
					<div class="btn-group">
						<button id="ws-grid-view" class="btn btn-default btn-sm" title="${__('Grid View')}">
							<svg class="icon icon-sm"><use href="#icon-image-view"></use></svg>
						</button>
						<button id="ws-list-view" class="btn btn-default btn-sm" title="${__('List View')}">
							<svg class="icon icon-sm"><use href="#icon-list"></use></svg>
						</button>
					</div>
					<span id="ws-items-count" class="text-muted small"></span>
				</div>

				<!-- Main Content Row -->
				<div class="row">
					<!-- Filters Sidebar -->
					<div class="col-md-3" id="ws-filters-sidebar">
						<div class="frappe-card p-3">
							<div class="d-flex justify-content-between align-items-center mb-3">
								<strong>${__('Filters')}</strong>
								<a href="#" id="ws-clear-filters" class="text-muted" style="font-size: 12px;">
									${__('Clear All')}
								</a>
							</div>
							<div id="ws-filter-content">
								<div class="text-muted small">${__('Loading filters...')}</div>
							</div>
						</div>
					</div>

					<!-- Products Area -->
					<div class="col-md-9" id="ws-product-listing">
						<div id="ws-loading" class="text-center py-5">
							<div class="text-muted">${__('Loading products...')}</div>
						</div>
						<div id="ws-products-grid" class="row hidden"></div>
						<div id="ws-products-list" class="hidden"></div>
						<div id="ws-no-products" class="text-center py-5 hidden">
							<img src="/assets/webshop/images/cart-empty-state.png"
								alt="${__('No Products')}" style="height: 150px; opacity: 0.5;"
								onerror="this.style.display='none'">
							<div class="text-muted mt-3">${__('No products found')}</div>
						</div>
						<div id="ws-paging" class="d-flex justify-content-between align-items-center mt-4"></div>
					</div>
				</div>
			</div>
		`);

		this.setup_toolbar_actions();
	}

	setup_toolbar_actions() {
		let me = this;

		// Search with debounce
		$('#ws-search-box').on('input', frappe.utils.debounce(function () {
			me.search_term = $(this).val().trim();
			me.start = 0;
			me.load_products(true);
		}, 400));

		// Grid / List view toggles
		$('#ws-grid-view').on('click', function () {
			me.preference = 'Grid View';
			localStorage.setItem('upande_webshop_view', 'Grid View');
			$('#ws-products-grid').removeClass('hidden');
			$('#ws-products-list').addClass('hidden');
			$(this).addClass('btn-primary');
			$('#ws-list-view').removeClass('btn-primary');
		});

		$('#ws-list-view').on('click', function () {
			me.preference = 'List View';
			localStorage.setItem('upande_webshop_view', 'List View');
			$('#ws-products-list').removeClass('hidden');
			$('#ws-products-grid').addClass('hidden');
			$(this).addClass('btn-primary');
			$('#ws-grid-view').removeClass('btn-primary');
		});

		// Clear filters
		$('#ws-clear-filters').on('click', function (e) {
			e.preventDefault();
			me.field_filters = {};
			me.attribute_filters = {};
			me.start = 0;
			$('#ws-filter-content input[type="checkbox"]').prop('checked', false);
			me.load_products();
		});

		// Apply initial view state
		if (this.preference === 'List View') {
			$('#ws-list-view').addClass('btn-primary');
		} else {
			$('#ws-grid-view').addClass('btn-primary');
		}
	}

	load_products(from_filters) {
		let me = this;

		$('#ws-loading').removeClass('hidden');
		$('#ws-products-grid').addClass('hidden');
		$('#ws-products-list').addClass('hidden');
		$('#ws-no-products').addClass('hidden');

		frappe.call({
			method: 'upande_webshop.upande_webshop.api.get_product_filter_data',
			args: {
				query_args: {
					search: me.search_term || null,
					field_filters: me.field_filters,
					attribute_filters: me.attribute_filters,
					start: me.start,
					from_filters: from_filters || false
				}
			},
			callback: function (r) {
				$('#ws-loading').addClass('hidden');

				if (!r || r.exc || !r.message || r.message.exc) {
					me.render_error();
					return;
				}

				let data = r.message;
				me.ws_settings = data.settings;
				me.items_count = data.items_count || 0;

				$('#ws-items-count').text(
					me.items_count + ' ' + __('item(s) found')
				);

				if (data.items && data.items.length) {
					me.render_products(data.items, data.settings);
					me.render_paging(data.settings);
					// Show correct view
					if (me.preference === 'List View') {
						$('#ws-products-list').removeClass('hidden');
					} else {
						$('#ws-products-grid').removeClass('hidden');
					}
				} else {
					$('#ws-no-products').removeClass('hidden');
					$('#ws-paging').html('');
				}

				// Render filters only on initial load (not on every filter change)
				if (!from_filters) {
					me.render_filters();
				}
			}
		});
	}

	render_products(items, settings) {
		this.render_grid(items, settings);
		this.render_list(items, settings);
	}

	render_grid(items, settings) {
		let me = this;
		let html = '';

		items.forEach(item => {
			let title = item.web_item_name || item.item_name || item.item_code || '';
			title = title.length > 90 ? title.substr(0, 90) + '...' : title;
			let safe_title = frappe.utils.escape_html(title);

			let image_html = item.website_image
				? `<a href="/${item.route || '#'}" target="_blank" style="text-decoration:none;">
					<img class="ws-item-image" src="${item.website_image}" alt="${safe_title}">
				   </a>`
				: `<a href="/${item.route || '#'}" target="_blank" style="text-decoration:none;">
					<div class="ws-no-image">${frappe.get_abbr(title)}</div>
				   </a>`;

			html += `
				<div class="col-sm-4 mb-4">
					<div class="frappe-card ws-item-card p-0" style="overflow: hidden;">
						${image_html}
						<div class="p-3">
							<a href="/${item.route || '#'}" target="_blank"
								style="text-decoration:none; color: var(--text-color);">
								<div style="font-weight: 600; font-size: 14px; margin-bottom: 4px;">${safe_title}</div>
							</a>
							<div class="text-muted" style="font-size: 12px; margin-bottom: 6px;">${item.item_group || ''}</div>
							${item.formatted_price
								? `<div style="font-weight:600; color: var(--primary);">${item.formatted_price}</div>`
								: ''}
							${me.get_stock_badge(item, settings)}
							${me.get_action_button(item, settings)}
						</div>
					</div>
				</div>
			`;
		});

		$('#ws-products-grid').html(html);
		this.bind_cart_actions();
	}

	render_list(items, settings) {
		let me = this;
		let html = '';

		items.forEach(item => {
			let title = item.web_item_name || item.item_name || item.item_code || '';
			let safe_title = frappe.utils.escape_html(title);

			let image_html = item.website_image
				? `<img class="ws-list-image" src="${item.website_image}" alt="${safe_title}">`
				: `<div class="ws-list-no-image">${frappe.get_abbr(title)}</div>`;

			html += `
				<div class="frappe-card d-flex align-items-start mb-3 p-3" style="gap: 16px;">
					<a href="/${item.route || '#'}" target="_blank" style="text-decoration:none; flex-shrink:0;">
						${image_html}
					</a>
					<div style="flex: 1; min-width: 0;">
						<div class="d-flex justify-content-between align-items-start">
							<a href="/${item.route || '#'}" target="_blank"
								style="font-weight: 600; font-size: 15px; color: var(--text-color); text-decoration: none;">
								${safe_title}
							</a>
							<div style="flex-shrink: 0; margin-left: 12px;">
								${me.get_action_button(item, settings)}
							</div>
						</div>
						<div class="text-muted" style="font-size: 12px; margin-bottom: 4px;">
							${item.item_group || ''} | ${__('Item Code')}: ${item.item_code}
						</div>
						<div class="text-muted" style="font-size: 13px; margin-bottom: 6px;">
							${item.short_description || ''}
						</div>
						${item.formatted_price
							? `<span style="font-weight:600; color: var(--primary);">${item.formatted_price}</span>`
							: ''}
						${me.get_stock_badge(item, settings)}
					</div>
				</div>
			`;
		});

		$('#ws-products-list').html(html);
		this.bind_cart_actions();
	}

	get_stock_badge(item, settings) {
		if (!settings || !settings.show_stock_availability || item.has_variants) return '';
		if (item.on_backorder) {
			return `<span class="badge badge-warning ml-1" style="font-size: 11px;">${__('Backorder')}</span>`;
		}
		if (!item.in_stock) {
			return `<span class="badge badge-danger ml-1" style="font-size: 11px;">${__('Out of Stock')}</span>`;
		}
		return `<span class="badge badge-success ml-1" style="font-size: 11px;">${__('In Stock')}</span>`;
	}

	get_action_button(item, settings) {
		if (item.has_variants) {
			return `
				<a href="/${item.route || '#'}" target="_blank"
					class="btn btn-xs btn-default mt-2">${__('Explore')}</a>
			`;
		}
		if (settings && settings.enabled && (settings.allow_items_not_in_stock || item.in_stock)) {
			let add_label = settings.enable_checkout ? __('Add to Cart') : __('Add to Quote');
			let go_label = settings.enable_checkout ? __('Go to Cart') : __('Go to Quote');
			return `
				<button class="btn btn-xs btn-primary mt-2 ws-add-to-cart ${item.in_cart ? 'hidden' : ''}"
					data-item-code="${frappe.utils.escape_html(item.item_code)}">
					${add_label}
				</button>
				<a href="/cart" target="_blank"
					class="btn btn-xs btn-primary mt-2 ws-go-to-cart ${item.in_cart ? '' : 'hidden'}"
					data-item-code="${frappe.utils.escape_html(item.item_code)}">
					${go_label}
				</a>
			`;
		}
		return '';
	}

	bind_cart_actions() {
		$('.ws-add-to-cart').off('click').on('click', function () {
			let item_code = $(this).data('item-code');
			let $add_btn = $(this);
			let $go_btn = $add_btn.siblings('.ws-go-to-cart');

			$add_btn.prop('disabled', true).text(__('Adding...'));

			frappe.call({
				method: 'upande_webshop.upande_webshop.shopping_cart.cart.update_cart',
				args: { item_code: item_code, qty: 1 },
				callback: function (r) {
					if (!r.exc) {
						$add_btn.addClass('hidden').prop('disabled', false);
						$go_btn.removeClass('hidden');
						frappe.show_alert({
							message: __('Item added to cart'),
							indicator: 'green'
						});
					} else {
						$add_btn.prop('disabled', false).text(__('Add to Cart'));
					}
				}
			});
		});
	}

	render_filters() {
		$('#ws-filter-content').html(`<div class="text-muted small">${__('Loading...')}</div>`);

		frappe.call({
			method: 'upande_webshop.upande_webshop.page.upande_webshop.upande_webshop.get_webshop_filters',
			callback: (r) => {
				$('#ws-filter-content').html('');

				if (!r || !r.message) {
					$('#ws-filter-content').html(
						`<div class="text-muted small">${__('No filters configured')}</div>`
					);
					return;
				}

				let { field_filters, attribute_filters } = r.message;

				(field_filters || []).forEach(filter => {
					if (filter.values && filter.values.length) {
						this.append_field_filter(filter.fieldname, filter.label, filter.values);
					}
				});

				(attribute_filters || []).forEach(attr => {
					if (attr.values && attr.values.length) {
						this.append_attribute_filter(attr.attribute, attr.values);
					}
				});

				if (!$('#ws-filter-content').children().length) {
					$('#ws-filter-content').html(
						`<div class="text-muted small">${__('No filters configured')}</div>`
					);
				}

				this.bind_filter_actions();
			}
		});
	}

	append_field_filter(fieldname, label, values) {
		let html = `
			<div class="filter-block" data-filter-type="field" data-fieldname="${fieldname}">
				<div class="filter-label">${__(label || fieldname)}</div>
				<div class="filter-options">
		`;
		values.forEach(val => {
			let display = (typeof val === 'object') ? (val[fieldname] || val.name || '') : val;
			html += `
				<div class="mb-1">
					<label class="d-flex align-items-center" style="font-weight: normal; cursor: pointer;">
						<input type="checkbox" class="product-filter field-filter mr-2"
							data-filter-name="${fieldname}"
							data-filter-value="${frappe.utils.escape_html(display)}">
						<span style="font-size: 13px;">${frappe.utils.escape_html(display)}</span>
					</label>
				</div>
			`;
		});
		html += `</div></div>`;
		$('#ws-filter-content').append(html);
	}

	append_attribute_filter(attribute, values) {
		let html = `
			<div class="filter-block" data-filter-type="attribute" data-attribute="${attribute}">
				<div class="filter-label">${__(attribute)}</div>
				<div class="filter-options">
		`;
		values.forEach(val => {
			html += `
				<div class="mb-1">
					<label class="d-flex align-items-center" style="font-weight: normal; cursor: pointer;">
						<input type="checkbox" class="product-filter attribute-filter mr-2"
							data-attribute-name="${attribute}"
							data-attribute-value="${frappe.utils.escape_html(val.attribute_value)}">
						<span style="font-size: 13px;">${frappe.utils.escape_html(val.attribute_value)}</span>
					</label>
				</div>
			`;
		});
		html += `</div></div>`;
		$('#ws-filter-content').append(html);
	}

	bind_filter_actions() {
		let me = this;

		$('.field-filter').off('change').on('change', function () {
			let filter_name = $(this).data('filter-name');
			let filter_value = $(this).data('filter-value');
			let is_checked = $(this).is(':checked');

			me.field_filters[filter_name] = me.field_filters[filter_name] || [];

			if (is_checked) {
				if (!me.field_filters[filter_name].includes(filter_value)) {
					me.field_filters[filter_name].push(filter_value);
				}
			} else {
				me.field_filters[filter_name] = me.field_filters[filter_name].filter(v => v !== filter_value);
				if (!me.field_filters[filter_name].length) {
					delete me.field_filters[filter_name];
				}
			}

			me.start = 0;
			me.load_products(true);
		});

		$('.attribute-filter').off('change').on('change', function () {
			let attr_name = $(this).data('attribute-name');
			let attr_value = $(this).data('attribute-value');
			let is_checked = $(this).is(':checked');

			me.attribute_filters[attr_name] = me.attribute_filters[attr_name] || [];

			if (is_checked) {
				if (!me.attribute_filters[attr_name].includes(attr_value)) {
					me.attribute_filters[attr_name].push(attr_value);
				}
			} else {
				me.attribute_filters[attr_name] = me.attribute_filters[attr_name].filter(v => v !== attr_value);
				if (!me.attribute_filters[attr_name].length) {
					delete me.attribute_filters[attr_name];
				}
			}

			me.start = 0;
			me.load_products(true);
		});
	}

	render_paging(settings) {
		let me = this;
		let page_length = (settings && settings.products_per_page) || 20;
		let prev_disabled = me.start <= 0;
		let next_disabled = me.items_count <= (me.start + page_length);

		let html = `
			<div>
				<button class="btn btn-default btn-sm ws-btn-prev" ${prev_disabled ? 'disabled' : ''}>
					${__('&larr; Prev')}
				</button>
			</div>
			<div class="text-muted small">
				${me.start + 1} – ${Math.min(me.start + page_length, me.items_count)} ${__('of')} ${me.items_count}
			</div>
			<div>
				<button class="btn btn-default btn-sm ws-btn-next" ${next_disabled ? 'disabled' : ''}>
					${__('Next &rarr;')}
				</button>
			</div>
		`;

		$('#ws-paging').html(html);

		$('.ws-btn-prev').on('click', function () {
			me.start = Math.max(0, me.start - page_length);
			me.load_products();
			$(me.wrapper).find('.page-content')[0].scrollIntoView({ behavior: 'smooth' });
		});

		$('.ws-btn-next').on('click', function () {
			me.start = me.start + page_length;
			me.load_products();
			$(me.wrapper).find('.page-content')[0].scrollIntoView({ behavior: 'smooth' });
		});
	}

	render_error() {
		$('#ws-no-products').html(`
			<div class="alert alert-danger">
				${__('Something went wrong. Please refresh or contact support.')}
			</div>
		`).removeClass('hidden');
	}
}
