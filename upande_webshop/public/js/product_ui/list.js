webshop.ProductList = class {
	/* Options:
		- items: Items
		- settings: Webshop Settings
		- products_section: Products Wrapper
		- preference: If preference is not list view, render but hide
	*/
	constructor(options) {
		Object.assign(this, options);

		if (this.preference !== "List View") {
			this.products_section.addClass("hidden");
		}

		this.products_section.empty();
		this.make();
	}

	make() {
		let me = this;
		let html = `<br><br>`;

		this.items.forEach(item => {
			let title = item.web_item_name || item.item_name || item.item_code || "";
			title =  title.length > 200 ? title.substr(0, 200) + "..." : title;

			html += `<a href="/${ item.route || '#' }" style="text-decoration: none; color: inherit; display: block; width: 100%;"><div class='row list-row w-100 mb-4'>`;
			html += me.get_image_html(item, title, me.settings);
			html += me.get_row_body_html(item, title, me.settings);
			html += `</div></a>`;
		});

		let $product_wrapper = this.products_section;
		$product_wrapper.append(html);
	}

	get_image_html(item, title, settings) {
		let image = item.website_image;
		let wishlist_enabled = false; // wishlist disabled
		let image_html = ``;

		if (image) {
			image_html += `
				<div class="col-2 border text-center rounded list-image">
					<img itemprop="image" class="website-image h-100 w-100" alt="${ title }"
						src="${ image }">
					${ wishlist_enabled ? this.get_wishlist_icon(item): '' }
				</div>
			`;
		} else {
			image_html += `
				<div class="col-2 border text-center rounded list-image">
					<div class="card-img-top no-image-list">
						${ frappe.get_abbr(title) }
					</div>
					${ wishlist_enabled ? this.get_wishlist_icon(item): '' }
				</div>
			`;
		}

		return image_html;
	}

	get_row_body_html(item, title, settings) {
		let body_html = `<div class='col-10 text-left'>`;
		body_html += this.get_title_html(title);
		body_html += this.get_item_details(item, settings);
		body_html += `</div>`;
		return body_html;
	}

	get_title_html(title) {
		let title_html = `<div style="display: flex; margin-left: -15px;">`;
		title_html += `
			<div class="col-12" style="margin-right: -15px; font-weight: 500;">
				${ title }
			</div>
		`;
		title_html += `</div>`;

		return title_html;
	}

	get_item_details(item, settings) {
		// Price is intentionally hidden on the listing — shown only on the detail
		// page once a stem length is selected.
		let details = `
			<p class="product-code">
				${ item.item_group } | ${ __('Item Code') } : ${ item.item_code }
			</p>
			<div class="mt-2" style="color: var(--gray-600) !important; font-size: 13px;">
				${ item.short_description || '' }
			</div>
			<div>
		`;

		details += this.get_stock_availability(item, settings);
		details += `</div>`;

		return details;
	}

	get_stock_availability(item, settings) {
		if (settings.show_stock_availability && !item.has_variants) {
			if (item.on_backorder) {
				return `
					<br>
					<span class="out-of-stock mt-2" style="color: var(--primary-color)">
						${ __("Available on backorder") }
					</span>
				`;
			} else if (!item.in_stock) {
				return `
					<br>
					<span class="out-of-stock mt-2">${ __("Out of stock") }</span>
				`;
			} else if (item.is_stock) {
				return `
					<br>
					<span class="in-stock in-green has-stock mt-2"
						style="font-size: 14px;">${ __("In stock") }</span>
				`;
			}
		}
		return ``;
	}

	get_wishlist_icon(item) {
		let icon_class = item.wished ? "wished" : "not-wished";

		return `
			<div class="like-action-list ${ item.wished ? "like-action-wished" : ''}"
				data-item-code="${ item.item_code }">
				<svg class="icon sm">
					<use class="${ icon_class } wish-icon" href="#icon-heart"></use>
				</svg>
			</div>
		`;
	}

};