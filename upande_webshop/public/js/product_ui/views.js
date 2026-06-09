webshop.ProductView =  class {
	/* Options:
		- View Type
		- Products Section Wrapper,
		- Item Group: If its an Item Group page
	*/
	constructor(options) {
		Object.assign(this, options);
		this.preference = this.view_type;
		this.make();

		// Browser back/forward (after a paging pushState) should re-render the
		// listing in place too — never a full page reload. get_query_filters()
		// re-reads `start` from the now-restored URL.
		if (!webshop._product_popstate_bound) {
			webshop._product_popstate_bound = true;
			let me = this;
			window.addEventListener("popstate", () => me.make(true, true));
		}
	}

	make(from_filters=false, preserve_toolbar=false, is_paging=false) {
		if (preserve_toolbar) {
			// Remove only product/list/grid areas, keep the toolbar so the search input keeps focus
			this.products_section.find("#products-grid-area, #products-list-area, .cart-empty, .alert-error").remove();
			this.products_section.find("br").remove();
		} else {
			this.products_section.empty();
			this.prepare_toolbar();
		}
		// `is_paging` re-renders the next/prev page: it must keep the filters bound
		// (don't re-bind) but, unlike a filter change, must NOT reset `start` to 0
		// on the server — otherwise paging always re-fetches page 1.
		this.is_paging = is_paging;
		this.get_item_filter_data(from_filters);
	}

	prepare_toolbar() {
		this.products_section.append(`
			<div class="toolbar d-flex">
			</div>
		`);
		this.prepare_search();
		this.prepare_view_toggler();

		new webshop.ProductSearch();
		this.bind_grid_search();
	}

	bind_grid_search() {
		const me = this;
		const $box = $("#search-box");
		if (!$box.length) return;

		// Restore the current search term (if any) from the URL into the input
		const initial = frappe.utils.get_query_params().search || "";
		if (initial && !$box.val()) {
			$box.val(initial);
		}

		const apply_search = (term) => {
			const params = frappe.utils.get_query_params();
			const current = params.search || "";
			if (term === current) return;

			if (term) {
				params.search = term;
			} else {
				delete params.search;
			}
			params.start = 0;

			const qs = me.get_query_string(params);
			const path = qs ? `${location.pathname}?${qs}` : location.pathname;
			window.history.replaceState("search", "", path);

			me.from_filters = true;
			me.make(true, true);
		};

		const debounced = frappe.utils.debounce((term) => apply_search(term), 300);

		$box.on("input", (e) => {
			const term = (e.target.value || "").trim();
			// Clear immediately on empty; otherwise debounce
			if (!term) {
				apply_search("");
			} else {
				debounced(term);
			}
		});
	}

	prepare_view_toggler() {

		if (!$("#list").length || !$("#image-view").length) {
			this.render_view_toggler();
			this.bind_view_toggler_actions();
			this.set_view_state();
		}
	}

	get_item_filter_data(from_filters=false) {
		// Get and render all Product related views
		let me = this;
		this.from_filters = from_filters;
		let args = this.get_query_filters();

		this.disable_view_toggler(true);

		frappe.call({
			method: "upande_webshop.upande_webshop.api.get_product_filter_data",
			args: {
				query_args: args
			},
			callback: function(result) {
				if (!result || result.exc || !result.message || result.message.exc) {
					me.render_no_products_section(true);
				} else {
					// Sub Category results are independent of Items
					if (me.item_group && result.message["sub_categories"].length) {
						me.render_item_sub_categories(result.message["sub_categories"]);
					}

					if (!result.message["items"].length) {
						// if result has no items or result is empty
						me.render_no_products_section();
					} else {
						// Add discount filters
						me.re_render_discount_filters(result.message["filters"].discount_filters);

						// Render views
						me.render_list_view(result.message["items"], result.message["settings"]);
						me.render_grid_view(result.message["items"], result.message["settings"]);

						me.products = result.message["items"];
						me.product_count = result.message["items_count"];
					}

					// Bind filter actions
					if (!from_filters && !me.is_paging) {
						// If `get_product_filter_data` was triggered after checking a filter
						// or via paging, don't touch filters unnecessarily, only data must
						// change — filter persistence is handled on filter change event.
						me.bind_filters();
						me.restore_filters_state();
					}

					// Bottom paging
					me.add_paging_section(result.message["settings"]);
				}

				me.disable_view_toggler(false);
			}
		});
	}

	disable_view_toggler(disable=false) {
		$('#list').prop('disabled', disable);
		$('#image-view').prop('disabled', disable);
	}

	render_grid_view(items, settings) {
		// loop over data and add grid html to it
		let me = this;
		this.prepare_product_area_wrapper("grid");

		new webshop.ProductGrid({
			items: items,
			products_section: $("#products-grid-area"),
			settings: settings,
			preference: me.preference
		});
	}

	render_list_view(items, settings) {
		let me = this;
		this.prepare_product_area_wrapper("list");

		new webshop.ProductList({
			items: items,
			products_section: $("#products-list-area"),
			settings: settings,
			preference: me.preference
		});
	}

	prepare_product_area_wrapper(view) {
		let left_margin = view == "list" ? "ml-2" : "";
		let top_margin = view == "list" ? "mt-6" : "mt-minus-1";
		return this.products_section.append(`
			<br>
			<div id="products-${view}-area" class="row products-list ${ top_margin } ${ left_margin }" itemscope itemtype="https://schema.org/Product"></div>
		`);
	}

	get_query_filters() {
		const filters = frappe.utils.get_query_params();
		let {field_filters, attribute_filters} = filters;

		field_filters = field_filters ? JSON.parse(field_filters) : {};
		attribute_filters = attribute_filters ? JSON.parse(attribute_filters) : {};

		return {
			field_filters: field_filters,
			attribute_filters: attribute_filters,
			item_group: this.item_group,
			start: filters.start || null,
			from_filters: this.from_filters || false,
			search: filters.search || null
		};
	}

	add_paging_section(settings) {
		$(".product-paging-area").remove();

		if (this.products) {
			let query_params = frappe.utils.get_query_params();
			let start = query_params.start ? cint(JSON.parse(query_params.start)) : 0;
			let page_length = settings.products_per_page || 0;

			let prev_disable = start > 0 ? "" : "disabled";
			// Disable Next on the last page: enabled only while more items remain
			// beyond the current page window.
			let has_next = page_length > 0 && (start + page_length) < this.product_count;
			let next_disable = has_next ? "" : "disabled";

			// Prev pinned to the far LEFT, Next to the far RIGHT, via a full-width
			// flex with space-between (the old col-3 + col-9/text-right layout left
			// Prev floating near the centre).
			let paging_html = `
				<div class="product-paging-area mt-5 d-flex justify-content-between align-items-center">
					<button class="btn btn-default btn-prev" data-start="${ start - page_length }" ${prev_disable}>
						${ __("Prev") }
					</button>
					<button class="btn btn-default btn-next" data-start="${ start + page_length }" ${next_disable}>
						${ __("Next") }
					</button>
				</div>
			`;

			$("#product-listing").append(paging_html);
			this.bind_paging_action();
		}
	}

	prepare_search() {
		$(".toolbar").append(`
			<div class="input-group col-8 p-0">
				<div class="dropdown w-100" id="dropdownMenuSearch">
					<input type="search" name="query" id="search-box" class="form-control font-md"
						placeholder="${__("Search for Products")}"
						aria-label="Product" aria-describedby="button-addon2">
					<div class="search-icon">
						<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor" stroke-width="2" stroke-linecap="round"
							stroke-linejoin="round"
							class="feather feather-search">
							<circle cx="11" cy="11" r="8"></circle>
							<line x1="21" y1="21" x2="16.65" y2="16.65"></line>
						</svg>
					</div>
					<!-- Results dropdown rendered in product_search.js -->
				</div>
			</div>
		`);
	}

	render_view_toggler() {
		$(".toolbar").append(`<div class="toggle-container col-4 p-0"></div>`);

		["btn-list-view", "btn-grid-view"].forEach(view => {
			let icon = view === "btn-list-view" ? "list" : "image-view";
			$(".toggle-container").append(`
				<div class="form-group mb-0" id="toggle-view">
					<button id="${ icon }" class="btn ${ view } mr-2">
						<span>
							<svg class="icon icon-md">
								<use href="#icon-${ icon }"></use>
							</svg>
						</span>
					</button>
				</div>
			`);
		});
	}

	bind_view_toggler_actions() {
		$("#list").click(function() {
			let $btn = $(this);
			$btn.removeClass('btn-primary');
			$btn.addClass('btn-primary');
			$(".btn-grid-view").removeClass('btn-primary');

			$("#products-grid-area").addClass("hidden");
			$("#products-list-area").removeClass("hidden");
			localStorage.setItem("product_view", "List View");
		});

		$("#image-view").click(function() {
			let $btn = $(this);
			$btn.removeClass('btn-primary');
			$btn.addClass('btn-primary');
			$(".btn-list-view").removeClass('btn-primary');

			$("#products-list-area").addClass("hidden");
			$("#products-grid-area").removeClass("hidden");
			localStorage.setItem("product_view", "Grid View");
		});
	}

	set_view_state() {
		if (this.preference === "List View") {
			$("#list").addClass('btn-primary');
			$("#image-view").removeClass('btn-primary');
		} else {
			$("#image-view").addClass('btn-primary');
			$("#list").removeClass('btn-primary');
		}
	}

	bind_paging_action() {
		let me = this;
		$('.btn-prev, .btn-next').click((e) => {
			const $btn = $(e.target);

			$btn.prop('disabled', true);
			const start = $btn.data('start');

			// Update the URL's `start` WITHOUT reloading the page, so the change
			// is bookmarkable / back-button-friendly. get_query_filters() reads
			// `start` from the URL, so the in-place re-render below picks it up.
			let query_params = frappe.utils.get_query_params();
			query_params.start = start;
			let path = window.location.pathname + '?' + frappe.utils.get_url_from_dict(query_params);
			history.pushState({ start: start }, '', path);

			// Re-render ONLY the product listing (grid/list + paging), keeping the
			// toolbar, search box and filters intact. Paging passes is_paging=true
			// (NOT from_filters): from_filters makes the server reset `start` to 0,
			// which would make every Next/Prev re-fetch page 1.
			me.make(false, true, true);

			// Scroll the listing's own scroll container back to the top so the
			// new page starts at the first card (the column scrolls, not the page).
			let $scroll = $('#products-grid-area:visible, #products-list-area:visible').first();
			if ($scroll.length) {
				$scroll.scrollTop(0);
			} else {
				$('#product-listing').scrollTop(0);
			}
		});
	}

	re_render_discount_filters(filter_data) {
		this.get_discount_filter_html(filter_data);
		if (this.from_filters) {
			// Bind filter action if triggered via filters
			// if not from filter action, page load will bind actions
			this.bind_discount_filter_action();
		}
		// discount filters are rendered with Items (later)
		// unlike the other filters
		this.restore_discount_filter();
	}

	get_discount_filter_html(filter_data) {
		$("#discount-filters").remove();
		if (filter_data) {
			$("#product-filters").append(`
				<div id="discount-filters" class="mb-4 filter-block pb-5">
					<div class="filter-label mb-3">${ __("Discounts") }</div>
				</div>
			`);

			let html = `<div class="filter-options">`;
			filter_data.forEach(filter => {
				html += `
					<div class="checkbox">
						<label data-value="${ filter[0] }">
							<input type="radio"
								class="product-filter discount-filter"
								name="discount" id="${ filter[0] }"
								data-filter-name="discount"
								data-filter-value="${ filter[0] }"
								style="width: 14px !important"
							>
								<span class="label-area" for="${ filter[0] }">
									${ filter[1] }
								</span>
						</label>
					</div>
				`;
			});
			html += `</div>`;

			$("#discount-filters").append(html);
		}
	}

	restore_discount_filter() {
		const filters = frappe.utils.get_query_params();
		let field_filters = filters.field_filters;
		if (!field_filters) return;

		field_filters = JSON.parse(field_filters);

		if (field_filters && field_filters["discount"]) {
			const values = field_filters["discount"];
			const selector = values.map(value => {
				return `input[data-filter-name="discount"][data-filter-value="${value}"]`;
			}).join(',');
			$(selector).prop('checked', true);
			this.field_filters = field_filters;
		}
	}

	bind_discount_filter_action() {
		let me = this;
		$('.discount-filter').on('change', (e) => {
			const $checkbox = $(e.target);
			const is_checked = $checkbox.is(':checked');

			const {
				filterValue: filter_value
			} = $checkbox.data();

			delete this.field_filters["discount"];

			if (is_checked) {
				this.field_filters["discount"] = [];
				this.field_filters["discount"].push(filter_value);
			}

			if (this.field_filters["discount"].length === 0) {
				delete this.field_filters["discount"];
			}

			me.change_route_with_filters();
		});
	}

	bind_filters() {
		let me = this;
		this.field_filters = {};
		this.attribute_filters = {};

		$('.product-filter').on('change', (e) => {
			me.from_filters = true;

			const $checkbox = $(e.target);
			const is_checked = $checkbox.is(':checked');

			if ($checkbox.is('.attribute-filter')) {
				const {
					attributeName: attribute_name,
					attributeValue: attribute_value
				} = $checkbox.data();

				if (is_checked) {
					this.attribute_filters[attribute_name] = this.attribute_filters[attribute_name] || [];
					this.attribute_filters[attribute_name].push(attribute_value);
				} else {
					this.attribute_filters[attribute_name] = this.attribute_filters[attribute_name] || [];
					this.attribute_filters[attribute_name] = this.attribute_filters[attribute_name].filter(v => v !== attribute_value);
				}

				if (this.attribute_filters[attribute_name].length === 0) {
					delete this.attribute_filters[attribute_name];
				}
			} else if ($checkbox.is('.field-filter') || $checkbox.is('.discount-filter')) {
				const {
					filterName: filter_name,
					filterValue: filter_value
				} = $checkbox.data();

				if ($checkbox.is('.discount-filter')) {
					// clear previous discount filter to accomodate new
					delete this.field_filters["discount"];
				}
				if (is_checked) {
					this.field_filters[filter_name] = this.field_filters[filter_name] || [];
					if (!in_list(this.field_filters[filter_name], filter_value)) {
						this.field_filters[filter_name].push(filter_value);
					}
				} else {
					this.field_filters[filter_name] = this.field_filters[filter_name] || [];
					this.field_filters[filter_name] = this.field_filters[filter_name].filter(v => v !== filter_value);
				}

				if (this.field_filters[filter_name].length === 0) {
					delete this.field_filters[filter_name];
				}
			}

			me.change_route_with_filters();
		});

		// bind filter lookup input box
		$('.filter-lookup-input').on('keydown', frappe.utils.debounce((e) => {
			const $input = $(e.target);
			const keyword = ($input.val() || '').toLowerCase();
			const $filter_options = $input.next('.filter-options');

			$filter_options.find('.filter-lookup-wrapper').show();
			$filter_options.find('.filter-lookup-wrapper').each((i, el) => {
				const $el = $(el);
				const value = $el.data('value').toLowerCase();
				if (!value.includes(keyword)) {
					$el.hide();
				}
			});
		}, 300));
	}

	change_route_with_filters() {
		let route_params = frappe.utils.get_query_params();

		let start = this.if_key_exists(route_params.start) || 0;
		if (this.from_filters) {
			start = 0; // show items from first page if new filters are triggered
		}

		const query_string = this.get_query_string({
			start: start,
			field_filters: JSON.stringify(this.if_key_exists(this.field_filters)),
			attribute_filters: JSON.stringify(this.if_key_exists(this.attribute_filters)),
		});
		window.history.pushState('filters', '', `${location.pathname}?` + query_string);

		$('.page_content input').prop('disabled', true);

		this.make(true);
		$('.page_content input').prop('disabled', false);
	}

	restore_filters_state() {
		const filters = frappe.utils.get_query_params();
		let {field_filters, attribute_filters} = filters;

		if (field_filters) {
			field_filters = JSON.parse(field_filters);
			for (let fieldname in field_filters) {
				const values = field_filters[fieldname];
				const selector = values.map(value => {
					return `input[data-filter-name="${fieldname}"][data-filter-value="${value}"]`;
				}).join(',');
				$(selector).prop('checked', true);
			}
			this.field_filters = field_filters;
		}
		if (attribute_filters) {
			attribute_filters = JSON.parse(attribute_filters);
			for (let attribute in attribute_filters) {
				const values = attribute_filters[attribute];
				const selector = values.map(value => {
					return `input[data-attribute-name="${attribute}"][data-attribute-value="${value}"]`;
				}).join(',');
				$(selector).prop('checked', true);
			}
			this.attribute_filters = attribute_filters;
		}
	}

	render_no_products_section(error=false) {
		let error_section = `
			<div class="mt-4 w-100 alert alert-error font-md">
				${ __("Something went wrong. Please refresh or contact us.") }
			</div>
		`;
		let no_results_section = `
			<div class="cart-empty frappe-card mt-4">
				<div class="cart-empty-state">
					<img src="/assets/upande_webshop/images/cart-empty-state.png" alt="Empty Cart">
				</div>
				<div class="cart-empty-message mt-4">${ __("No products found") }</p>
			</div>
		`;

		this.products_section.append(error ? error_section : no_results_section);
	}

	render_item_sub_categories(categories) {
		if (categories && categories.length) {
			let sub_group_html = `
				<div class="sub-category-container scroll-categories">
			`;

			categories.forEach(category => {
				sub_group_html += `
					<a href="/${ category.route || '#' }" style="text-decoration: none;">
						<div class="category-pill">
							${ category.name }
						</div>
					</a>
				`;
			});
			sub_group_html += `</div>`;

			$("#product-listing").prepend(sub_group_html);
		}
	}

	get_query_string(object) {
		const url = new URLSearchParams();
		for (let key in object) {
			const value = object[key];
			if (value) {
				url.append(key, value);
			}
		}
		return url.toString();
	}

	if_key_exists(obj) {
		let exists = false;
		for (let key in obj) {
			if (Object.prototype.hasOwnProperty.call(obj, key) && obj[key]) {
				exists = true;
				break;
			}
		}
		return exists ? obj : undefined;
	}
};
