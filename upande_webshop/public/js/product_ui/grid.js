webshop.ProductGrid = class {
	/* Options:
		- items: Items
		- settings: Webshop Settings
		- products_section: Products Wrapper
		- preference: If preference is not grid view, render but hide
	*/
	constructor(options) {
		Object.assign(this, options);

		if (this.preference !== "Grid View") {
			this.products_section.addClass("hidden");
		}

		this.products_section.empty();
		this.make();
	}

	make() {
		let me = this;
		let html = ``;

		this.items.forEach(item => {
			let title = item.web_item_name || item.item_name || item.item_code || "";
			title =  title.length > 90 ? title.substr(0, 90) + "..." : title;

			html += `<div class="col-6 col-md-4 col-lg-3 item-card" style="position:relative;">`;
			if (me.settings.enable_wishlist) {
				html += me.get_wishlist_icon(item);
			}
			html += `<a href="/${ item.route || '#' }" style="text-decoration: none; color: inherit; display: block;"><div class="card text-left">`;
			html += me.get_image_html(item, title);
			html += me.get_card_body_html(item, title, me.settings);
			html += `</div></a></div>`;
		});

		let $product_wrapper = this.products_section;
		$product_wrapper.append(html);
	}

	get_image_html(item, title) {
		let image = item.website_image;

		if (image) {
			return `
				<div class="card-img-container">
					<img itemprop="image" class="card-img" src="${ image }" alt="${ title }">
				</div>
			`;
		} else {
			return `
				<div class="card-img-container">
					<div class="card-img-top no-image">
						${ frappe.get_abbr(title) }
					</div>
				</div>
			`;
		}
	}

	get_card_body_html(item, title, settings) {
		let body_html = `
			<div class="card-body text-left card-body-flex" style="width:100%">
				<div style="display: flex;">
		`;
		body_html += this.get_title(title);


		body_html += `</div>`;
		body_html += `<div class="product-category" itemprop="name">${ item.item_group || '' }</div>`;

		// Price is intentionally hidden on the listing — shown only on the detail
		// page once a stem length is selected.

		body_html += this.get_stock_availability(item, settings);
		body_html += `</div>`; // close div on line 49

		return body_html;
	}

	get_title(title) {
		let title_html = `
			<div class="product-title" itemprop="name">
				${ title || '' }
			</div>
		`;
		return title_html;
	}

	get_wishlist_icon(item) {
		let icon_class = item.wished ? "wished" : "not-wished";
		return `
			<div class="like-action ${ item.wished ? "like-action-wished" : ''}"
				data-item-code="${ item.item_code }">
				<svg class="icon sm">
					<use class="${ icon_class } wish-icon" href="#icon-heart"></use>
				</svg>
			</div>
		`;
	}

	get_price_html(item) {
		let price_html = `
			<div class="product-price" itemprop="offers" itemscope itemtype="https://schema.org/AggregateOffer">
				${ item.formatted_price || '' }
		`;

		if (item.formatted_mrp) {
			price_html += `
				<small class="striked-price">
					<s>${ item.formatted_mrp ? item.formatted_mrp.replace(/ +/g, "") : "" }</s>
				</small>
				<small class="ml-1 product-info-green">
					${ item.discount } ${ __("OFF") }
				</small>
			`;
		}
		price_html += `</div>`;
		return price_html;
	}

	get_stock_availability(item, settings) {
		if (settings.show_stock_availability) {
			if (item.on_backorder) {
				return `
					<span class="out-of-stock mb-2 mt-1" style="color: var(--primary-color)">
						${ __("Available on backorder") }
					</span>
				`;
			} else if (!item.in_stock) {
				return `
					<span class="out-of-stock mb-2 mt-1">
						${ __("Out of stock") }
					</span>
				`;
			} else {
				let qty_suffix = "";
				if (settings.show_quantity_in_website && item.stock_qty != null && Number(item.stock_qty) > 0) {
					qty_suffix = ` (${ Number(item.stock_qty).toLocaleString() })`;
				}
				return `
					<span class="in-stock in-green has-stock mb-2 mt-1"
						style="font-size: 14px;">${ __("In stock") }${ qty_suffix }</span>
				`;
			}
		}

		return ``;
	}

};
