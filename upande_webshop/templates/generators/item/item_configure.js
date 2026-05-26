// Inline variant selector: toggle buttons per attribute + box type.
// Customer picks a variant + box, then enters No. of Bunches.
// Total stems = bunch_size (from item's sales UOM) × num_bunches.

const _pack_rate_cache = {};
const _bunch_size_cache = {};

function fetch_bunch_size(item_code) {
	if (!item_code) return Promise.resolve({ size: 1, uom: null });
	if (_bunch_size_cache[item_code] !== undefined) {
		return Promise.resolve(_bunch_size_cache[item_code]);
	}
	return new Promise((resolve) => {
		frappe.call({
			method: 'upande_webshop.api.pack_rate.get_item_bunch_size',
			args: { item_code },
			callback: (r) => {
				const msg = (r && r.message) || {};
				const result = { size: msg.bunch_size || 1, uom: msg.sales_uom || null };
				_bunch_size_cache[item_code] = result;
				resolve(result);
			},
			error: () => resolve({ size: 1, uom: null }),
		});
	});
}

function fetch_pack_rate(box_name, length_cm) {
	if (!box_name || !length_cm) {
		return Promise.resolve({ pack_rate: null });
	}
	const key = `${box_name}|${length_cm}`;
	if (_pack_rate_cache[key] !== undefined) {
		return Promise.resolve(_pack_rate_cache[key]);
	}
	return new Promise((resolve) => {
		frappe.call({
			method: 'upande_webshop.api.pack_rate.get_pack_rate',
			args: { box_name, length_cm },
			callback: (r) => {
				const result = (r && r.message) || { pack_rate: null };
				_pack_rate_cache[key] = result;
				resolve(result);
			},
			error: () => resolve({ pack_rate: null }),
		});
	});
}

class InlineVariantSelector {
	constructor($root, item_code, item_name) {
		this.$root = $root;
		this.item_code = item_code;
		this.item_name = item_name;
		this.selected_attributes = {};
		this.selected_box_type = '';
		this.exact_match_item = null;
		this._per_stem_rate = null;
		this._currency = '€';
		this._moq = 0; // MOQ expressed in stems
		this._moq_bunches = 0;
		this._pack_rate = null;
		this._user_edited_bunches = false;
		this.bunch_size = 1;
		this.bunch_uom = null; // sales UOM (e.g. "Bunch (12)") — sent to update_cart
		this._in_stock = null; // null=unknown, true/false once resolved
		this._stock_qty = null;
		this._show_stock_qty = false;
		this._on_backorder = false;

		this.$attr_area = $root.find('.variant-attributes-area');
		this.$box_area = $root.find('.box-type-area');
		this.$box_toggle = $root.find('.box-type-toggle');
		this.$pack_rate_display = $root.find('.pack-rate-display');
		this.$totals_area = $root.find('.totals-area');
		this.$bunch_size_input = $root.find('.bunch-size-input');
		this.$bunches_display = $root.find('.bunches-display');
		this.$total_stems_display = $root.find('.total-stems-display');
		this.$validation_msg = $root.find('.stems-validation-msg');
		this.$price_display = $root.find('.price-display');
		this.$status_area = $root.find('.variant-status-area');
		this.$add_to_cart = $root.find('.btn-add-to-cart-variant');
		this.$clear = $root.find('.btn-clear-variant');
		this.$moq_label = $root.find('.moq-label');

		fetch_bunch_size(this.item_code).then((info) => {
			this.bunch_size = info.size;
			this.bunch_uom = info.uom;
			this.$bunch_size_input.val(info.size);
		});
		this.init();
	}

	init() {
		this.load_attributes()
			.then(attrs => {
				this.attribute_data = attrs;
				this.render_attribute_toggles();
				this.restore_from_cache();
			});

		this.load_box_types();
		this.bind_events();
	}

	bind_events() {
		this.$root.on('click', '.attr-toggle .attr-btn', (e) => {
			e.preventDefault();
			const $btn = $(e.currentTarget);
			const attribute = $btn.data('attribute');
			const value = String($btn.data('value'));
			if (this.selected_attributes[attribute] === value) return;
			this.selected_attributes[attribute] = value;
			this._user_edited_bunches = false;
			$btn.siblings('.attr-btn').removeClass('active');
			$btn.addClass('active');
			if (this.range_values) delete this.range_values[attribute];
			this.remove_range_input(attribute);
			this.maybe_show_range_input(attribute, value);
			this.persist_cache();
			this.refresh_attribute_state();
			if (this.selected_box_type) {
				this.refresh_moq_for_box();
			}
		});

		this.$root.on('click', '.box-type-toggle .box-btn', (e) => {
			e.preventDefault();
			const $btn = $(e.currentTarget);
			const value = String($btn.data('value'));
			if (this.selected_box_type === value) return;
			this.selected_box_type = value;
			this._user_edited_bunches = false;
			$btn.siblings('.box-btn').removeClass('active');
			$btn.addClass('active');
			this.refresh_moq_for_box().then(() => {
				this.update_pack_rate_and_totals();
			});
		});

		this.$root.on('input', '.bunches-display', () => {
			this._user_edited_bunches = true;
			this.recalculate_totals();
		});

		this.$add_to_cart.on('click', (e) => {
			e.preventDefault();
			this.add_to_cart();
		});

		this.$clear.on('click', (e) => {
			e.preventDefault();
			this.clear_all();
		});
	}

	load_attributes() {
		return this.call(
			'upande_webshop.upande_webshop.variant_selector.utils.get_attributes_and_values',
			{ item_code: this.item_code }
		);
	}

	load_box_types() {
		frappe.call({
			method: 'upande_webshop.api.pack_rate.get_box_types',
			callback: (r) => {
				const rows = (r && r.message) || [];
				if (!rows.length) {
					this.$box_area.hide();
					return;
				}
				this.$box_toggle.empty();
				rows.forEach(row => {
					const label = row.box_type_name || row.name;
					this.$box_toggle.append(`
						<button type="button" class="btn box-btn" data-value="${frappe.utils.escape_html(label)}">
							${frappe.utils.escape_html(label)}
						</button>
					`);
				});
				this.$box_area.show();
			},
			error: () => {
				this.$box_area.hide();
			}
		});
	}

	render_attribute_toggles() {
		const $area = this.$attr_area;
		$area.empty();

		if (!this.attribute_data || !this.attribute_data.length) {
			$area.html(`<div style="color:var(--gray-500); font-size:13px;">
				${__('No variant options available.')}
			</div>`);
			return;
		}

		this.attribute_data.forEach(attr => {
			const $group = $(`
				<div class="attr-group" data-attribute="${frappe.utils.escape_html(attr.attribute)}">
					<label class="d-block mb-2" style="font-weight:600; font-size:13px; color:var(--gray-700);">
						${frappe.utils.escape_html(attr.attribute)}
					</label>
					<div class="attr-toggle" data-attribute="${frappe.utils.escape_html(attr.attribute)}"></div>
				</div>
			`);
			const $toggle = $group.find('.attr-toggle');
			(attr.values || []).forEach(v => {
				$toggle.append(`
					<button type="button" class="btn attr-btn"
						data-attribute="${frappe.utils.escape_html(attr.attribute)}"
						data-value="${frappe.utils.escape_html(v)}">
						${frappe.utils.escape_html(v)}
					</button>
				`);
			});
			$area.append($group);
		});
	}

	maybe_show_range_input(attribute, value) {
		// Some attribute values are stored as "60 to 70" — let the user pick
		// a specific number within that range.
		this.remove_range_input(attribute);
		if (!value || !value.includes(' to ')) return;
		const numbers = value.split(' to ').map(n => parseFloat(n));
		if (numbers.some(n => isNaN(n))) return;
		numbers.sort((a, b) => a - b);
		const $group = this.$root.find(`.attr-group[data-attribute="${$.escapeSelector(attribute)}"]`);
		const $wrapper = $(`
			<div class="range-selector mt-2" data-range-for="${frappe.utils.escape_html(attribute)}">
				<small style="color:var(--gray-600);">
					${__('Enter a value between {0} and {1}', [numbers[0], numbers[1]])}
				</small>
				<input type="number" class="form-control range-input mt-1"
					min="${numbers[0]}" max="${numbers[1]}"
					style="max-width:140px; font-size:14px;">
			</div>
		`);
		$group.append($wrapper);
		$wrapper.find('.range-input').on('input', (e) => {
			const val = parseInt($(e.currentTarget).val());
			if (val >= numbers[0] && val <= numbers[1]) {
				this.range_values = this.range_values || {};
				this.range_values[attribute] = val;
				this._user_edited_bunches = false;
				this.update_pack_rate_and_totals();
			}
		});
	}

	remove_range_input(attribute) {
		this.$root.find(`.range-selector[data-range-for="${$.escapeSelector(attribute)}"]`).remove();
	}

	refresh_attribute_state() {
		const values = this.selected_attributes;
		this.set_loading_status();

		if (Object.keys(values).length === 0) {
			this.exact_match_item = null;
			this._per_stem_rate = null;
			this._in_stock = null;
			this.clear_status();
			this.update_addable_state();
			this.update_pack_rate_and_totals();
			return;
		}

		this.call(
			'upande_webshop.upande_webshop.variant_selector.utils.get_next_attribute_and_values',
			{ item_code: this.item_code, selected_attributes: values }
		).then(data => {
			const { exact_match } = data;
			this.set_item_found_status(data);

			if (exact_match && exact_match.length === 1) {
				this.exact_match_item = exact_match[0];
				this.fetch_per_stem_rate(this.exact_match_item);
				this.refresh_bunch_size_for(this.exact_match_item);
				this.fetch_stock_status(this.exact_match_item);
			} else {
				this.exact_match_item = null;
				this._per_stem_rate = null;
				this._in_stock = null;
				this.update_price_display();
			}

			this.update_addable_state();
			this.update_pack_rate_and_totals();
		});
	}

	fetch_stock_status(item_code) {
		frappe.call({
			method: 'upande_webshop.upande_webshop.shopping_cart.product_info.get_product_info_for_website',
			args: { item_code, skip_quotation_creation: 1 },
			callback: (r) => {
				if (this.exact_match_item !== item_code) return;
				const info = (r && r.message && r.message.product_info) || {};
				this._on_backorder = !!info.on_backorder;
				this._stock_qty = (info.stock_qty != null) ? Number(info.stock_qty) : null;
				this._show_stock_qty = !!info.show_stock_qty;
				if (this._on_backorder) {
					this._in_stock = true;
				} else if (info.in_stock === 1 || info.in_stock === true) {
					this._in_stock = true;
				} else if (info.in_stock === 0 || info.in_stock === false) {
					this._in_stock = false;
				} else {
					this._in_stock = null;
				}
				this.set_item_found_status_with_stock();
				this.update_addable_state();
			},
			error: () => {
				if (this.exact_match_item !== item_code) return;
				this._in_stock = null;
				this._stock_qty = null;
				this._show_stock_qty = false;
				this._on_backorder = false;
				this.update_addable_state();
			}
		});
	}

	stock_suffix() {
		if (this._on_backorder) return __('On backorder');
		if (this._in_stock !== true) return '';
		if (this._show_stock_qty && this._stock_qty != null && this._stock_qty > 0) {
			return `${__('In stock')} (${this._stock_qty.toLocaleString()})`;
		}
		return __('In stock');
	}

	set_item_found_status_with_stock() {
		if (this._in_stock === false) {
			this.$status_area.html(`
				<div style="color:var(--red-500); font-weight:500;" role="alert">
					${frappe.utils.escape_html(this.exact_match_item)} — ${__('Out of stock')}
				</div>
			`);
			return;
		}
		const suffix = this.stock_suffix();
		if (!suffix) return;
		// Append stock info to the existing green item-found banner without
		// losing its price suffix.
		const $banner = this.$status_area.find('div[role="status"]').first();
		if ($banner.length) {
			$banner.append(document.createTextNode(' — ' + suffix));
		}
	}

	fetch_per_stem_rate(item_code) {
		frappe.call({
			method: 'upande_webshop.upande_webshop.shopping_cart.cart.get_item_price_for_configure',
			args: { item_code },
			callback: (r) => {
				if (r.message) {
					this._per_stem_rate = r.message.price_list_rate;
					this._currency = r.message.currency || '€';
					this.update_price_display();
				}
			}
		});
	}

	refresh_bunch_size_for(item_code) {
		fetch_bunch_size(item_code).then((info) => {
			if (this.exact_match_item !== item_code) return;
			this.bunch_size = Math.max(parseInt(info.size) || 1, 1);
			this.bunch_uom = info.uom || null;
			this.$bunch_size_input.val(this.bunch_size);
			// MOQ bunches->stems depends on bunch_size; refresh moq line if a box is picked
			if (this.selected_box_type) {
				this._moq = this._moq_bunches * this.bunch_size;
			}
			this.autofill_bunches_from_pack_rate();
			this.recalculate_totals();
		});
	}

	get_selected_length() {
		// Look for a Length / Stem Length attribute among the selected values
		// (the dialog used the field name 'Length', so keep that as primary).
		const candidates = ['Length', 'Stem Length'];
		for (const attr of candidates) {
			if (this.range_values && this.range_values[attr]) {
				return this.range_values[attr];
			}
			const raw = this.selected_attributes[attr];
			if (!raw) continue;
			const match = String(raw).match(/(\d+)/);
			if (match) return parseInt(match[1]);
		}
		return null;
	}

	refresh_moq_for_box() {
		const box = this.selected_box_type;
		if (!box) {
			this._moq = 0;
			this._moq_bunches = 0;
			this.$moq_label.text('');
			return Promise.resolve();
		}
		return new Promise((resolve) => {
			frappe.call({
				method: 'upande_webshop.upande_webshop.api.get_box_min_order_qty',
				args: { box_name: box },
				callback: (r) => {
					const bunches = (r && r.message && r.message.min_order_qty) || 0;
					this._moq_bunches = bunches;
					this._moq = bunches * (this.bunch_size || 1);
					this.$moq_label.text(
						this._moq_bunches
							? ` — MOQ: ${this._moq_bunches} bunch${this._moq_bunches > 1 ? 'es' : ''}`
							: ''
					);
					if (this._moq_bunches && !this._user_edited_bunches) {
						this.$bunches_display.val(this._moq_bunches);
					}
					resolve();
				},
				error: () => {
					this._moq = 0;
					this._moq_bunches = 0;
					this.$moq_label.text('');
					resolve();
				}
			});
		});
	}

	update_pack_rate_and_totals() {
		const length = this.get_selected_length();
		const box = this.selected_box_type;

		if (this.exact_match_item) {
			this.$totals_area.css('display', 'flex');
		}

		if (!(box && length)) {
			this._pack_rate = null;
			this.$pack_rate_display.html('');
			this.recalculate_totals();
			return;
		}

		this.$pack_rate_display.html(
			`<small style="color:var(--gray-500);">${__('Looking up pack rate...')}</small>`
		);

		fetch_pack_rate(box, length).then((result) => {
			if (this.get_selected_length() !== length || this.selected_box_type !== box) return;

			this._pack_rate = result.pack_rate;
			if (this._pack_rate) {
				this.$pack_rate_display.html(`
					<small style="color:var(--gray-600);">
						<strong>${this._pack_rate} stems/box</strong>
					</small>
				`);
			} else {
				this.$pack_rate_display.html(
					`<small style="color:var(--gray-500);">${__('No pack rate data for this combination')}</small>`
				);
			}
			this.autofill_bunches_from_pack_rate();
			this.recalculate_totals();
		});
	}

	autofill_bunches_from_pack_rate() {
		// One box's worth of bunches = pack_rate / bunch_size.
		// Only seed if the user hasn't manually overridden the value.
		if (this._user_edited_bunches) return;
		if (!this._pack_rate || !this.bunch_size) return;
		const bunches = Math.floor(this._pack_rate / this.bunch_size);
		if (bunches > 0) {
			this.$bunches_display.val(bunches);
		}
	}

	recalculate_totals() {
		const num_bunches = parseInt(this.$bunches_display.val()) || 0;
		const bunch_size = this.bunch_size || 1;
		const total_stems = num_bunches * bunch_size;
		this.$total_stems_display.val(total_stems);

		this.validate_moq(total_stems, num_bunches);
		this.update_price_display();
		this.update_addable_state();
	}

	validate_moq(total_stems, num_bunches) {
		const moq_bunches = this._moq_bunches;
		const stock_qty = (this._stock_qty != null) ? Number(this._stock_qty) : null;

		if (total_stems > 0 && moq_bunches > 0 && (num_bunches || 0) < moq_bunches) {
			this.$validation_msg.html(`
				<small style="color:#e8a000; font-weight:500;">
					⚠️ ${__('Minimum order is {0} bunch{1} for this box type.', [moq_bunches, moq_bunches > 1 ? 'es' : ''])}
				</small>
			`);
		} else if (total_stems > 0 && stock_qty != null && stock_qty >= 0 && total_stems > stock_qty) {
			this.$validation_msg.html(`
				<small style="color:#c0392b; font-weight:500;">
					⚠️ ${__('Only {0} stems available in stock — reduce the number of bunches.', [stock_qty.toLocaleString()])}
				</small>
			`);
		} else {
			this.$validation_msg.html('');
		}
	}

	update_addable_state() {
		const stems = parseInt(this.$total_stems_display.val()) || 0;
		const has_stock = this._in_stock !== false;
		const stock_qty = (this._stock_qty != null) ? Number(this._stock_qty) : null;
		const within_stock = (stock_qty == null) || stems <= stock_qty;
		const can_add = !!(this.exact_match_item && stems > 0 && stems >= (this._moq || 0) && has_stock && within_stock);
		this.$add_to_cart.prop('disabled', !can_add);
	}

	update_price_display() {
		const stems = parseInt(this.$total_stems_display.val()) || 0;
		if (this._per_stem_rate && stems > 0) {
			const total = (this._per_stem_rate * stems).toFixed(2);
			this.$price_display.html(`
				<div class="d-flex align-items-center" style="font-size:14px; color:var(--gray-700);">
					<span>${this._currency} ${this._per_stem_rate.toFixed(3)} / stem</span>
					<span class="mx-2">×</span>
					<span>${stems} stems</span>
					<span class="mx-2">=</span>
					<strong style="font-size:16px;">${this._currency} ${total}</strong>
				</div>
			`);
		} else {
			this.$price_display.empty();
		}
	}

	set_loading_status() {
		this.$status_area.html(`
			<div class="alert alert-warning d-flex justify-content-between align-items-center mb-0" role="alert">
				${__('Loading...')}
			</div>
		`);
	}

	clear_status() {
		this.$status_area.empty();
	}

	set_item_found_status(data) {
		const { filtered_items_count, filtered_items, exact_match, product_info } = data;
		const one_item = exact_match.length === 1
			? exact_match[0]
			: filtered_items_count === 1 ? filtered_items[0] : '';

		const items_found = filtered_items_count === 1
			? __('{0} item found.', [filtered_items_count])
			: __('{0} items found.', [filtered_items_count]);

		const html = exact_match.length === 1
			? `<div style="color:var(--green-600); font-weight:500;" role="status">
					${frappe.utils.escape_html(one_item)}
					${product_info && product_info.price && !$.isEmptyObject(product_info.price)
						? ' (' + product_info.price.formatted_price_sales_uom + ')' : ''}
				</div>`
			: `<div style="color:var(--yellow-600); font-weight:500;" role="status">${items_found}</div>`;

		this.$status_area.html(html);
	}

	clear_all() {
		this.selected_attributes = {};
		this.range_values = {};
		this.selected_box_type = '';
		this.exact_match_item = null;
		this._per_stem_rate = null;
		this._pack_rate = null;
		this._moq = 0;
		this._moq_bunches = 0;
		this._in_stock = null;
		this._user_edited_bunches = false;

		this.$root.find('.attr-btn').removeClass('active').prop('disabled', false);
		this.$root.find('.box-btn').removeClass('active');
		this.$root.find('.range-selector').remove();
		this.$bunch_size_input.val(this.bunch_size || 1);
		this.$bunches_display.val(0);
		this.$total_stems_display.val(0);
		this.$pack_rate_display.html('');
		this.$validation_msg.html('');
		this.$moq_label.text('');
		this.clear_status();
		this.update_price_display();
		this.update_addable_state();
		this.$totals_area.css('display', 'none');
		localStorage.removeItem(this.get_cache_key());
	}

	persist_cache() {
		if (Object.keys(this.selected_attributes).length === 0) {
			localStorage.removeItem(this.get_cache_key());
			return;
		}
		localStorage.setItem(this.get_cache_key(), JSON.stringify(this.selected_attributes));
	}

	restore_from_cache() {
		try {
			const raw = localStorage.getItem(this.get_cache_key());
			if (!raw) return;
			const saved = JSON.parse(raw);
			if (!saved || typeof saved !== 'object') return;
			Object.entries(saved).forEach(([attr, val]) => {
				const $btn = this.$root.find(
					`.attr-toggle[data-attribute="${$.escapeSelector(attr)}"] ` +
					`.attr-btn[data-value="${$.escapeSelector(String(val))}"]`
				);
				if ($btn.length) {
					this.selected_attributes[attr] = String(val);
					$btn.addClass('active');
					this.maybe_show_range_input(attr, String(val));
				}
			});
			if (Object.keys(this.selected_attributes).length) {
				this.refresh_attribute_state();
			}
		} catch (e) {
			// ignore corrupted cache
		}
	}

	add_to_cart() {
		const item_code = this.exact_match_item;
		if (!item_code) return;

		const box_type = this.selected_box_type || '';
		const total_stems = parseInt(this.$total_stems_display.val()) || 0;
		const num_bunches = parseInt(this.$bunches_display.val()) || 0;
		const bunch_size = this.bunch_size || 1;
		const custom_length = this.selected_attributes['Length'] || this.selected_attributes['Stem Length'] || '';
		const pack_rate = this._pack_rate || 0;

		if (!total_stems) {
			frappe.msgprint({
				title: __('Select Variant'),
				message: __('Enter the number of bunches before adding to quote.'),
				indicator: 'orange',
			});
			return;
		}

		if (frappe.session.user === 'Guest') {
			if (localStorage) {
				localStorage.setItem('last_visited', window.location.pathname);
			}
			frappe.call('upande_webshop.upande_webshop.api.get_guest_redirect_on_action').then((res) => {
				window.location.href = res.message || '/login';
			});
			return;
		}

		localStorage.removeItem(this.get_cache_key());

		const specs = [];
		$(".item-website-specification table tr").each(function() {
			const label = $(this).find(".spec-label").text().trim();
			const val = $(this).find(".spec-content").text().trim();
			if (label && val) specs.push(`${label}: ${val}`);
		});

		const additional_notes = [
			box_type ? `Box: ${box_type}` : '',
			pack_rate ? `Pack Rate: ${pack_rate} stems/box` : '',
			`Total Stems: ${total_stems} (${num_bunches} bunches × ${bunch_size} stems)`,
			specs.length ? `Specs: ${specs.join(", ")}` : '',
		].filter(Boolean).join(' | ');

		this.$add_to_cart.prop('disabled', true);

		upande_webshop.upande_webshop.shopping_cart.update_cart({
			item_code,
			qty: num_bunches,
			uom: this.bunch_uom || undefined,
			additional_notes,
			custom_length,
			box_type,
			callback: (r) => {
				this.update_addable_state();
				if (r && !r.exc) {
					frappe.show_alert({
						message: __('Added {0} bunch{1} of {2} to your quote.', [num_bunches, num_bunches === 1 ? '' : 'es', item_code]),
						indicator: 'green',
					});
				}
			},
		});
	}

	get_cache_key() {
		return `configure:${this.item_code}`;
	}

	call(method, args) {
		return new Promise((resolve, reject) => {
			frappe.call(method, args)
				.then(r => resolve(r.message))
				.fail(reject);
		});
	}
}

frappe.ready(() => {
	const $root = $('.inline-variant-selector');
	if (!$root.length) return;
	const { itemCode, itemName } = $root.data();
	new InlineVariantSelector($root, itemCode, itemName);
});
