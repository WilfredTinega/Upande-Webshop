// Inline variant selector: pick attributes + box, then "+ Add Variant" stages
// one resolved variant per row. Multiple variants can be staged at once and
// posted to the cart together via "Add to Cart".

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

		// Selection-in-progress state (top picker)
		this.selected_attributes = {};
		this.selected_box_type = '';
		this.exact_match_item = null;
		this._per_stem_rate = null;
		this._currency = '€';
		this._moq = 0;
		this._moq_bunches = 0;
		this._pack_rate = null;
		this._in_stock = null;
		this._stock_qty = null;
		this._show_stock_qty = false;
		this._on_backorder = false;
		this.bunch_size = 1;
		this.bunch_uom = null;

		// Map<row_key, row_state> — keyed by `${item_code}|${box_type}`.
		// row_state: {
		//   item_code, box_type, length_cm, per_stem_rate, currency, bunch_size,
		//   bunch_uom, stock_qty, pack_rate, moq_bunches, num_bunches,
		//   user_edited, attribute_label, specs_snapshot
		// }
		this.variant_rows = new Map();

		this.$attr_area = $root.find('.variant-attributes-area');
		this.$box_area = $root.find('.box-type-area');
		this.$box_toggle = $root.find('.box-type-toggle');
		this.$pack_rate_display = $root.find('.pack-rate-display');
		this.$rows_area = $root.find('.variant-rows-area');
		this.$rows = $root.find('.variant-rows');
		this.$grand_totals = $root.find('.grand-totals');
		this.$grand_bunches = $root.find('.grand-bunches');
		this.$grand_stems = $root.find('.grand-stems');
		this.$price_display = $root.find('.price-display');
		this.$status_area = $root.find('.variant-status-area');
		this.$add_to_cart = $root.find('.btn-add-to-cart-variant');
		this.$moq_label = $root.find('.moq-label');

		fetch_bunch_size(this.item_code).then((info) => {
			this.bunch_size = info.size;
			this.bunch_uom = info.uom;
		});
		this.init();
	}

	init() {
		this._value_stock = {}; // { attribute: { value: qty } }
		this.load_attributes()
			.then(attrs => {
				this.attribute_data = attrs;
				return this.load_attribute_value_stock(attrs).then(() => {
					this.render_attribute_toggles();
				});
			});

		this.load_box_types();
		this.bind_events();
	}

	load_attribute_value_stock(attrs) {
		// Pull per-attribute-value storefront stock so the picker can render
		// out-of-stock values with a strikethrough (matches the non-variant flow).
		const calls = (attrs || []).map((attr) =>
			new Promise((resolve) => {
				frappe.call({
					method: 'upande_webshop.upande_webshop.variant_selector.utils.get_attribute_value_stock',
					args: { template_item_code: this.item_code, attribute: attr.attribute },
					callback: (r) => {
						this._value_stock[attr.attribute] = (r && r.message) || {};
						resolve();
					},
					error: () => resolve(),
				});
			})
		);
		return Promise.all(calls);
	}

	bind_events() {
		this.$root.on('click', '.attr-toggle .attr-btn', (e) => {
			e.preventDefault();
			const $btn = $(e.currentTarget);
			if ($btn.is(':disabled') || $btn.hasClass('oos')) return;
			const attribute = $btn.data('attribute');
			const value = String($btn.data('value'));

			// Single-attribute items: button-active reflects "row staged" and a
			// re-click toggles the row off. (Non-variant flow's behavior.)
			const single_attr = (this.attribute_data || []).length === 1;
			if (single_attr && $btn.hasClass('active')) {
				const row_key = this._find_row_key_for_attr_value(attribute, value);
				if (row_key) {
					this.variant_rows.delete(row_key);
					this.render_rows();
					this.update_grand_totals();
					this.update_addable_state();
				}
				$btn.removeClass('active');
				return;
			}

			this.selected_attributes[attribute] = value;
			// In single-attribute mode, every active button represents one staged
			// row — don't clear siblings. Multi-attribute mode keeps the previous
			// "one active per attribute group" radio behavior.
			if (!single_attr) {
				$btn.siblings('.attr-btn').removeClass('active');
			}
			$btn.addClass('active');
			if (this.range_values) delete this.range_values[attribute];
			this.remove_range_input(attribute);
			this.maybe_show_range_input(attribute, value);
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
			$btn.siblings('.box-btn').removeClass('active');
			$btn.addClass('active');
			this.refresh_moq_for_box().then(() => {
				this.update_pack_rate_display();
				this.update_addable_state();
			});
		});

		this.$root.on('input', '.variant-row .bunches-input', (e) => {
			const $input = $(e.currentTarget);
			const key = String($input.closest('.variant-row').data('key'));
			const state = this.variant_rows.get(key);
			if (!state) return;
			let raw = Math.max(parseInt($input.val()) || 0, 0);
			const maxAttr = parseInt($input.attr('data-max-bunches'));
			if (!isNaN(maxAttr) && maxAttr >= 0 && raw > maxAttr) {
				raw = maxAttr;
				$input.val(raw);
			}
			state.num_bunches = raw;
			state.user_edited = true;
			this.update_row(key);
			this.update_grand_totals();
			this.update_addable_state();
		});

		this.$root.on('click', '.variant-row .btn-remove-row', (e) => {
			e.preventDefault();
			const key = String($(e.currentTarget).closest('.variant-row').data('key'));
			const state = this.variant_rows.get(key);
			this.variant_rows.delete(key);
			// Single-attribute mode: clear the matching attr-btn highlight so
			// the picker reflects what's still staged.
			if (state && state.selected_attrs) {
				Object.entries(state.selected_attrs).forEach(([attr, val]) => {
					this.$root.find(
						`.attr-toggle[data-attribute="${$.escapeSelector(attr)}"] ` +
						`.attr-btn[data-value="${$.escapeSelector(String(val))}"]`
					).removeClass('active');
				});
			}
			this.render_rows();
			this.update_grand_totals();
			this.update_addable_state();
		});

		this.$add_to_cart.on('click', (e) => {
			e.preventDefault();
			this.add_to_cart();
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
			const stock_map = this._value_stock[attr.attribute] || {};
			(attr.values || []).forEach(v => {
				const qty = Number(stock_map[v] || 0);
				const oos = qty <= 0;
				$toggle.append(`
					<button type="button" class="btn attr-btn${oos ? ' oos' : ''}"
						data-attribute="${frappe.utils.escape_html(attr.attribute)}"
						data-value="${frappe.utils.escape_html(v)}"
						data-stock-qty="${qty}"
						${oos ? 'disabled aria-disabled="true" title="' + __('Out of stock') + '"' : ''}>
						${frappe.utils.escape_html(v)}
					</button>
				`);
			});
			$area.append($group);
		});
	}

	maybe_show_range_input(attribute, value) {
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
				this.update_pack_rate_display();
				this.update_addable_state();
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
			this.update_pack_rate_display();
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
				this.auto_stage_variant();
			} else {
				this.exact_match_item = null;
				this._per_stem_rate = null;
				this._in_stock = null;
			}

			this.update_addable_state();
			this.update_pack_rate_display();
		});
	}

	auto_stage_variant() {
		// Called as soon as the picker resolves to a single variant. Snapshots
		// what we know now; fetch_per_stem_rate / fetch_stock_status / pack-rate
		// callbacks update the staged row as those async lookups complete.
		const item_code = this.exact_match_item;
		if (!item_code) return;
		const box_type = this.selected_box_type || '';
		const key = `${item_code}|${box_type}`;
		// Snapshot the attribute selection that produced this row, so re-clicking
		// the same attribute button later can find and unstage it.
		const selected_attrs_snapshot = { ...this.selected_attributes };

		if (this.variant_rows.has(key)) {
			this.flash_row(key);
			this.reset_picker_after_stage();
			return;
		}

		// Seed stock_qty from the attribute-value stock map when available
		// (avoids "0 stems" appearing in the row until fetch_stock_status returns).
		let seeded_stock = this._stock_qty;
		if (seeded_stock == null) {
			for (const [attr, val] of Object.entries(selected_attrs_snapshot)) {
				const map = this._value_stock[attr];
				if (map && map[val] != null) {
					seeded_stock = Number(map[val]);
					break;
				}
			}
		}

		this.variant_rows.set(key, {
			item_code,
			box_type,
			length_cm: this.get_selected_length(),
			per_stem_rate: this._per_stem_rate,
			currency: this._currency,
			bunch_size: this.bunch_size || 1,
			bunch_uom: this.bunch_uom,
			stock_qty: seeded_stock,
			on_backorder: this._on_backorder,
			pack_rate: this._pack_rate,
			moq_bunches: this._moq_bunches || 0,
			num_bunches: 1,
			user_edited: false,
			attribute_label: Object.entries(selected_attrs_snapshot).map(([k, v]) => `${k}: ${v}`).join(', '),
			selected_attrs: selected_attrs_snapshot,
		});
		this.reset_picker_after_stage();
		this.render_rows();
		this.update_grand_totals();
		this.update_addable_state();
	}

	_find_row_key_for_attr_value(attribute, value) {
		for (const [key, state] of this.variant_rows) {
			if (state.selected_attrs && state.selected_attrs[attribute] === value) {
				return key;
			}
		}
		return null;
	}

	fetch_stock_status(item_code) {
		// Capture box_type at call time — the picker resets right after staging,
		// so the staged row's key is `${item_code}|${box_type_when_staged}`.
		const box_type = this.selected_box_type || '';
		const row_key = `${item_code}|${box_type}`;
		frappe.call({
			method: 'upande_webshop.upande_webshop.shopping_cart.product_info.get_product_info_for_website',
			args: { item_code, skip_quotation_creation: 1 },
			callback: (r) => {
				const info = (r && r.message && r.message.product_info) || {};
				const stock_qty = (info.stock_qty != null) ? Number(info.stock_qty) : null;
				const state = this.variant_rows.get(row_key);
				if (state) {
					state.stock_qty = stock_qty;
					state.on_backorder = !!info.on_backorder;
					this.render_rows();
					this.update_grand_totals();
					this.update_addable_state();
				}
			},
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
		const $banner = this.$status_area.find('div[role="status"]').first();
		if ($banner.length) {
			$banner.append(document.createTextNode(' — ' + suffix));
		}
	}

	fetch_per_stem_rate(item_code) {
		const box_type = this.selected_box_type || '';
		const row_key = `${item_code}|${box_type}`;
		frappe.call({
			method: 'upande_webshop.upande_webshop.shopping_cart.cart.get_item_price_for_configure',
			args: { item_code },
			callback: (r) => {
				const rate = r && r.message && r.message.price_list_rate;
				if (!rate) {
					if (this.variant_rows.has(row_key)) {
						this.variant_rows.delete(row_key);
						this.render_rows();
						this.update_grand_totals();
						this.update_addable_state();
					}
					return;
				}
				this._currency = r.message.currency || this._currency || '€';
				const state = this.variant_rows.get(row_key);
				if (state) {
					state.per_stem_rate = rate;
					state.currency = r.message.currency || state.currency;
					this.update_row(row_key);
					this.update_grand_totals();
				}
			}
		});
	}

	refresh_bunch_size_for(item_code) {
		const box_type = this.selected_box_type || '';
		const row_key = `${item_code}|${box_type}`;
		fetch_bunch_size(item_code).then((info) => {
			const size = Math.max(parseInt(info.size) || 1, 1);
			const uom = info.uom || null;
			const state = this.variant_rows.get(row_key);
			if (state) {
				state.bunch_size = size;
				state.bunch_uom = uom;
				// If pack-rate is known, seed default bunches = floor(pack_rate / bunch_size)
				if (!state.user_edited && state.pack_rate && size) {
					const bunches = Math.floor(state.pack_rate / size);
					if (bunches > 0) state.num_bunches = bunches;
				} else if (!state.user_edited && state.moq_bunches) {
					state.num_bunches = state.moq_bunches;
				}
				this.render_rows();
				this.update_grand_totals();
				this.update_addable_state();
			}
		});
	}

	get_selected_length() {
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

	update_pack_rate_display() {
		const length = this.get_selected_length();
		const box = this.selected_box_type;

		if (!(box && length)) {
			this._pack_rate = null;
			this.$pack_rate_display.html('');
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
		});
	}

	reset_picker_after_stage() {
		// Clear the top picker so the user can pick another variant. The
		// staged row keeps its own snapshot of price/stock/etc.
		const single_attr = (this.attribute_data || []).length === 1;
		this.selected_attributes = {};
		this.range_values = {};
		this.exact_match_item = null;
		this._per_stem_rate = null;
		this._pack_rate = null;
		this._in_stock = null;
		this._stock_qty = null;
		this._show_stock_qty = false;
		this._on_backorder = false;
		// For single-attribute items the active class doubles as the "row staged"
		// indicator (non-variant flow's behavior). For multi-attribute items the
		// staged row encodes the full combo, so we clear the picker entirely.
		if (!single_attr) {
			this.$root.find('.attr-btn').removeClass('active');
			this.$root.find('.range-selector').remove();
		}
		this.$pack_rate_display.html('');
		this.clear_status();
	}

	flash_row(key) {
		const $row = this.$rows.find(`.variant-row[data-key="${$.escapeSelector(key)}"]`);
		if (!$row.length) return;
		const original_bg = $row.css('background');
		$row.css('background', '#fff8d6');
		setTimeout(() => $row.css('background', original_bg), 600);
	}

	render_rows() {
		this.$rows.empty();
		if (!this.variant_rows.size) {
			this.$rows_area.hide();
			this.$grand_totals.hide();
			return;
		}
		this.$rows_area.css('display', 'block');
		this.$grand_totals.css('display', 'flex');

		const tpl = (key, state) => {
			const stockText = (state.stock_qty != null)
				? `${__('Stock')}: ${Number(state.stock_qty).toLocaleString()}`
				: '';
			const bunchSize = state.bunch_size || 1;
			const maxBunches = (state.stock_qty != null && state.stock_qty >= 0)
				? Math.floor(Number(state.stock_qty) / bunchSize)
				: '';
			const maxAttr = maxBunches !== '' ? `max="${maxBunches}"` : '';
			const dataMaxAttr = maxBunches !== '' ? `data-max-bunches="${maxBunches}"` : '';
			const boxText = state.box_type
				? `<span class="variant-stock">${__('Box')}: ${frappe.utils.escape_html(state.box_type)}</span>`
				: '';
			return `
				<div class="variant-row" data-key="${frappe.utils.escape_html(key)}">
					<div>
						<span class="variant-tag">${frappe.utils.escape_html(state.item_code)}</span>
						${stockText ? `<span class="variant-stock">${frappe.utils.escape_html(stockText)}</span>` : ''}
						${boxText}
					</div>
					<div>
						<label class="d-block mb-1" style="font-weight:600; font-size:12px; color:var(--gray-700);">
							${__('Bunch Size')}
						</label>
						<input type="number" class="form-control bunch-size-display" value="${bunchSize}" readonly>
					</div>
					<div style="font-size:18px; font-weight:200; padding-bottom:4px;">×</div>
					<div>
						<label class="d-block mb-1" style="font-weight:600; font-size:12px; color:var(--gray-700);">
							${__('No. of Bunches')}
						</label>
						<input type="number" class="form-control bunches-input" value="${state.num_bunches || 0}" min="0" ${maxAttr} ${dataMaxAttr}>
					</div>
					<div style="font-size:18px; font-weight:200; padding-bottom:4px;">=</div>
					<div>
						<label class="d-block mb-1" style="font-weight:600; font-size:12px; color:var(--gray-700);">
							${__('Total Stems')}
						</label>
						<input type="number" class="form-control total-stems" value="0" readonly>
					</div>
					<div class="row-line-price ml-auto" style="font-size:13px; color:var(--gray-700); align-self:center;"></div>
					<button type="button" class="btn-remove-row" title="${__('Remove')}">×</button>
					<div class="row-msg"></div>
				</div>
			`;
		};

		this.variant_rows.forEach((state, key) => {
			this.$rows.append(tpl(key, state));
		});

		this.variant_rows.forEach((_, key) => this.update_row(key));
	}

	update_row(key) {
		const state = this.variant_rows.get(key);
		const $row = this.$rows.find(`.variant-row[data-key="${$.escapeSelector(key)}"]`);
		if (!state || !$row.length) return;

		const bunchSize = state.bunch_size || 1;
		const total_stems = (state.num_bunches || 0) * bunchSize;
		$row.find('.total-stems').val(total_stems);

		const $msg = $row.find('.row-msg');
		const $line_price = $row.find('.row-line-price');
		const stock_qty = (state.stock_qty != null) ? Number(state.stock_qty) : null;
		const moq_bunches = state.moq_bunches || 0;

		let msg = '';
		if (total_stems > 0 && moq_bunches > 0 && (state.num_bunches || 0) < moq_bunches) {
			msg = `<small style="color:#e8a000; font-weight:500;">⚠️ ${__(
				'Minimum order is {0} bunch{1} for this box type.',
				[moq_bunches, moq_bunches > 1 ? 'es' : '']
			)}</small>`;
		} else if (total_stems > 0 && stock_qty != null && stock_qty >= 0 && total_stems > stock_qty) {
			msg = `<small style="color:#c0392b; font-weight:500;">⚠️ ${__(
				'Only {0} stems available — reduce bunches.',
				[stock_qty.toLocaleString()]
			)}</small>`;
		}
		$msg.html(msg);

		if (state.per_stem_rate && total_stems > 0) {
			const total = (state.per_stem_rate * total_stems).toFixed(2);
			$line_price.html(`<strong>${state.currency || this._currency} ${total}</strong>`);
		} else if (!state.per_stem_rate && total_stems > 0) {
			$line_price.html(
				`<span style="color:var(--red-500);">${__('No price configured')}</span>`
			);
		} else {
			$line_price.empty();
		}
	}

	update_grand_totals() {
		let bunches = 0;
		let stems = 0;
		let grand_price = 0;
		let currency = this._currency;
		this.variant_rows.forEach((state) => {
			const nb = state.num_bunches || 0;
			const ts = nb * (state.bunch_size || 1);
			bunches += nb;
			stems += ts;
			if (state.per_stem_rate) grand_price += state.per_stem_rate * ts;
			if (state.currency) currency = state.currency;
		});
		this.$grand_bunches.text(bunches.toLocaleString());
		this.$grand_stems.text(stems.toLocaleString());
		if (grand_price > 0) {
			this.$price_display.html(
				`<div style="font-size:14px; color:var(--gray-700);">
					${__('Order total')}: <strong style="font-size:16px;">${currency} ${grand_price.toFixed(2)}</strong>
				</div>`
			);
		} else {
			this.$price_display.empty();
		}
	}

	update_addable_state() {
		// "Add to Cart" enabled when at least one staged row is valid and none are blocked.
		if (!this.variant_rows.size) {
			this.$add_to_cart.prop('disabled', true);
			return;
		}
		let ok = false;
		let blocked = false;
		this.variant_rows.forEach((state) => {
			const stems = (state.num_bunches || 0) * (state.bunch_size || 1);
			if (stems <= 0) return;
			const stock_qty = (state.stock_qty != null) ? Number(state.stock_qty) : null;
			const within_stock = (stock_qty == null) || stems <= stock_qty;
			const meets_moq = !state.moq_bunches || state.num_bunches >= state.moq_bunches;
			if (within_stock && meets_moq) ok = true;
			else blocked = true;
		});
		this.$add_to_cart.prop('disabled', !ok || blocked);
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

	add_to_cart() {
		if (!this.variant_rows.size) return;

		if (frappe.session.user === 'Guest') {
			if (localStorage) {
				localStorage.setItem('last_visited', window.location.pathname);
			}
			frappe.call('upande_webshop.upande_webshop.api.get_guest_redirect_on_action').then((res) => {
				window.location.href = res.message || '/login';
			});
			return;
		}

		const specs = [];
		$('.item-website-specification table tr').each(function () {
			const label = $(this).find('.spec-label').text().trim();
			const val = $(this).find('.spec-content').text().trim();
			if (label && val) specs.push(`${label}: ${val}`);
		});

		// Snapshot rows to post; each remains posted independently so a single
		// failure doesn't drop the others. We don't pass custom_length —
		// the variant item_code already encodes length (Stem Length is a Link,
		// and "80cm" isn't a valid LEN-… name; see project memory).
		const entries = [];
		this.variant_rows.forEach((state) => {
			const stems = (state.num_bunches || 0) * (state.bunch_size || 1);
			if (stems <= 0) return;
			const stock_qty = (state.stock_qty != null) ? Number(state.stock_qty) : null;
			if (stock_qty != null && stems > stock_qty) return;
			if (state.moq_bunches && (state.num_bunches || 0) < state.moq_bunches) return;
			entries.push({ state, stems });
		});

		if (!entries.length) {
			frappe.msgprint({
				title: __('Nothing to add'),
				message: __('Enter the number of bunches for at least one variant.'),
				indicator: 'orange',
			});
			return;
		}

		this.$add_to_cart.prop('disabled', true);

		const post_one = ({ state, stems }) => new Promise((resolve) => {
			const additional_notes = [
				state.box_type ? `Box: ${state.box_type}` : '',
				state.pack_rate ? `Pack Rate: ${state.pack_rate} stems/box` : '',
				`Total Stems: ${stems} (${state.num_bunches} bunches × ${state.bunch_size} stems)`,
				state.attribute_label ? `Attrs: ${state.attribute_label}` : '',
				specs.length ? `Specs: ${specs.join(', ')}` : '',
			].filter(Boolean).join(' | ');

			upande_webshop.upande_webshop.shopping_cart.update_cart({
				item_code: state.item_code,
				qty: state.num_bunches,
				uom: state.bunch_uom || undefined,
				additional_notes,
				custom_box_type: state.box_type || undefined,
				callback: (r) => resolve({ ok: !(r && r.exc), state }),
			});
		});

		const run = async () => {
			let ok_count = 0;
			const succeeded_keys = [];
			for (const entry of entries) {
				const { ok, state } = await post_one(entry);
				if (ok) {
					ok_count += 1;
					succeeded_keys.push(`${state.item_code}|${state.box_type || ''}`);
				}
			}
			// Drop successfully posted rows; leave failed ones so the user can retry.
			succeeded_keys.forEach((k) => this.variant_rows.delete(k));
			this.render_rows();
			this.update_grand_totals();
			this.update_addable_state();

			if (ok_count) {
				frappe.show_alert({
					message: __('Added {0} variant{1} to your cart.', [ok_count, ok_count === 1 ? '' : 's']),
					indicator: 'green',
				});
				$('.btn-view-in-cart').removeClass('hidden');
			}
		};
		run();
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
