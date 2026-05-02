// Pack rates are loaded from the Pack Rate doctype on first dialog open.
// Shape: { variety_lowercase: { box_key: { length_cm: stems_per_box } } }
// Box keys: 'zim' covers ZIM, WAFEX, TFH HUB, FDT, JUMBO; 'std' covers STANDARD BOXES.
let PACK_RATES = {};
let PACK_RATES_LOADED = null;

function load_pack_rates() {
	if (PACK_RATES_LOADED) return PACK_RATES_LOADED;
	PACK_RATES_LOADED = new Promise((resolve) => {
		frappe.call({
			method: 'upande_webshop.upande_webshop.api.get_pack_rates_map',
			callback: (r) => {
				PACK_RATES = r.message || {};
				resolve(PACK_RATES);
			},
			error: () => {
				PACK_RATES = {};
				resolve(PACK_RATES);
			},
		});
	});
	return PACK_RATES_LOADED;
}

const BUNCH_SIZE = 10;

function get_box_key(box_name) {
	const b = (box_name || '').toLowerCase();
	if (b.includes('standard')) return 'std';
	if (b.includes('zim') || b.includes('wafex') || b.includes('tfh') ||
		b.includes('fdt') || b.includes('jumbo')) return 'zim';
	return null;
}

function get_pack_rate(variety_name, box_name, length_cm) {
	const key = (variety_name || '').toLowerCase().trim();
	const box_key = get_box_key(box_name);
	if (!box_key || !length_cm) return null;
	const rates = PACK_RATES[key];
	if (!rates || !rates[box_key]) return null;
	return rates[box_key][parseInt(length_cm)] || null;
}

class ItemConfigure {
	constructor(item_code, item_name) {
		this.item_code = item_code;
		this.item_name = item_name;
		this.selected_box_type = '';
		this._per_stem_rate = null;
		this._currency = '€';
		this._flower_type = null;
		this._moq = 10;
		this._pack_rate = null;

		load_pack_rates();

		frappe.call({
			method: 'frappe.client.get_value',
			args: {
				doctype: 'Website Item',
				filters: { item_code: this.item_code },
				fieldname: 'custom_flower_type'
			},
			callback: (r) => {
				if (r.message) {
					this._flower_type = r.message.custom_flower_type;
					this._moq = this._flower_type === 'Spray' ? 1000 : 1500;
				}
				this.get_attributes_and_values()
					.then(attribute_data => {
						this.attribute_data = attribute_data;
						this.show_configure_dialog();
					});
			}
		});
	}

	show_configure_dialog() {
		const fields = this.attribute_data.map(a => {
			return {
				fieldtype: 'Select',
				label: a.attribute,
				fieldname: a.attribute,
				options: a.values.map(v => ({ label: v, value: v })),
				change: (e) => {
					this.on_attribute_selection(e);
					this.update_pack_rate_and_totals();
				}
			};
		});

		this.dialog = new frappe.ui.Dialog({
			title: __('Select Variant for {0}', [this.item_name]),
			fields,
			on_hide: () => set_continue_configuration()
		});

		this.attribute_data.forEach(a => {
			const field = this.dialog.get_field(a.attribute);
			const $a = $(`<a href>${__("Clear")}</a>`);
			$a.on('click', (e) => {
				e.preventDefault();
				this.dialog.set_value(a.attribute, '');
			});
			field.$wrapper.find('.help-box').append($a);
		});

		this.append_status_area();
		this.dialog.show();
		this.dialog.set_values(JSON.parse(localStorage.getItem(this.get_cache_key())));
		$('.btn-configure').prop('disabled', false);
	}

	on_attribute_selection(e) {
		if (e) {
			const changed_fieldname = $(e.target).data('fieldname');
			this.show_range_input_if_applicable(changed_fieldname);
		} else {
			this.show_range_input_for_all_fields();
		}

		const values = this.dialog.get_values();
		if (Object.keys(values).length === 0) {
			this.clear_status();
			localStorage.removeItem(this.get_cache_key());
			return;
		}

		localStorage.setItem(this.get_cache_key(), JSON.stringify(values));
		this.set_loading_status();

		this.get_next_attribute_and_values(values)
			.then(data => {
				const { valid_options_for_attributes } = data;
				this.set_item_found_status(data);

				for (let attribute in valid_options_for_attributes) {
					const valid_options = valid_options_for_attributes[attribute];
					const options = this.dialog.get_field(attribute).df.options;
					const new_options = options.map(o => {
						o.disabled = !valid_options.includes(o.value);
						return o;
					});
					this.dialog.set_df_property(attribute, 'options', new_options);
					this.dialog.get_field(attribute).set_options();
				}
			});
	}

	get_selected_length() {
		const length_field = this.dialog.get_field('Length');
		if (!length_field) return null;
		const val = length_field.get_value() || '';
		const match = val.match(/(\d+)/);
		return match ? parseInt(match[1]) : null;
	}

	update_pack_rate_and_totals() {
		const length = this.get_selected_length();
		const box = this.selected_box_type;
		const pack_rate = get_pack_rate(this.item_name, box, length);
		this._pack_rate = pack_rate;

		const $pack_rate_display = this.dialog.$wrapper.find('.pack-rate-display');

		if (pack_rate) {
			const bunches_per_box = Math.floor(pack_rate / BUNCH_SIZE);
			$pack_rate_display.html(`
				<small style="color:var(--gray-600);">
					<strong>${pack_rate} stems/box</strong>
					= ${bunches_per_box} bunches × ${BUNCH_SIZE} stems per bunch
				</small>
			`);
		} else if (box && length) {
			$pack_rate_display.html(`
				<small style="color:var(--gray-500);">
					No pack rate data for this combination
				</small>
			`);
		} else {
			$pack_rate_display.html('');
		}

		this.recalculate_totals();
	}

	recalculate_totals() {
		const num_boxes = parseInt(this.$num_boxes_input ? this.$num_boxes_input.val() : 1) || 1;
		const pack_rate = this._pack_rate;

		if (!pack_rate) {
			if (this.$total_stems_display) this.$total_stems_display.val(0);
			if (this.$bunches_display) this.$bunches_display.val(0);
			this.update_price_display();
			return;
		}

		const total_stems = num_boxes * pack_rate;
		const num_bunches = Math.floor(total_stems / BUNCH_SIZE);

		if (this.$total_stems_display) this.$total_stems_display.val(total_stems);
		if (this.$bunch_size_input) this.$bunch_size_input.val(BUNCH_SIZE);
		if (this.$bunches_display) this.$bunches_display.val(num_bunches);

		this.validate_moq(total_stems);
		this.update_price_display();
	}

	validate_moq(total_stems) {
		const $msg = this.dialog.$wrapper.find('.stems-validation-msg');
		const moq = this._moq;

		if (total_stems > 0 && total_stems < moq) {
			const boxes_needed = Math.ceil(moq / (this._pack_rate || moq));
			$msg.html(`
				<small style="color:#e8a000; font-weight:500;">
					⚠️ Minimum order is ${moq} stems (${this._flower_type || ''} roses).
					You need at least <strong>${boxes_needed} box${boxes_needed > 1 ? 'es' : ''}</strong> to meet MOQ.
				</small>
			`);
		} else {
			$msg.html('');
		}
	}

	show_range_input_for_all_fields() {
		this.dialog.fields.forEach(f => {
			if (!["Section Break", "Coulmn Break"].includes(f.fieldtype)) {
				this.show_range_input_if_applicable(f.fieldname);
			}
		});
	}

	show_range_input_if_applicable(fieldname) {
		const changed_field = this.dialog.get_field(fieldname);
		const changed_value = changed_field.get_value();
		if (changed_value && changed_value.includes(' to ')) {
			let numbers = changed_value.split(' to ').map(n => parseFloat(n));
			if (!numbers.some(n => isNaN(n))) {
				numbers.sort((a, b) => a - b);
				if (changed_field.$input_wrapper.find('.range-selector').length) return;
				const parent = $('<div class="range-selector">')
					.insertBefore(changed_field.$input_wrapper.find('.help-box'));
				const control = frappe.ui.form.make_control({
					df: {
						fieldtype: 'Int',
						label: __('Enter value betweeen {0} and {1}', [numbers[0], numbers[1]]),
						change: () => {
							const value = control.get_value();
							if (value < numbers[0] || value > numbers[1]) {
								control.$wrapper.addClass('was-validated');
								control.set_description(__('Value must be between {0} and {1}', [numbers[0], numbers[1]]));
								control.$input[0].setCustomValidity('error');
							} else {
								control.$wrapper.removeClass('was-validated');
								control.set_description('');
								control.$input[0].setCustomValidity('');
								this.update_range_values(fieldname, value);
							}
						}
					},
					render_input: true,
					parent
				});
				control.$wrapper.addClass('mt-3');
			}
		}
	}

	update_range_values(attribute, range_value) {
		this.range_values = this.range_values || {};
		this.range_values[attribute] = range_value;
	}

	set_loading_status() {
		this.dialog.$status_area.html(`
			<div class="alert alert-warning d-flex justify-content-between align-items-center" role="alert">
				${__('Loading...')}
			</div>
		`);
	}

	set_item_found_status(data) {
		const html = this.get_html_for_item_found(data);
		this.dialog.$status_area.html(html);

		const { exact_match } = data;
		if (exact_match && exact_match.length === 1) {
			frappe.call({
				method: 'upande_webshop.upande_webshop.shopping_cart.cart.get_item_price_for_configure',
				args: { item_code: exact_match[0] },
				callback: (r) => {
					if (r.message) {
						this._per_stem_rate = r.message.price_list_rate;
						this._currency = r.message.currency || '€';
						this.update_price_display();
					}
				}
			});
		} else {
			this._per_stem_rate = null;
			this.update_price_display();
		}
	}

	clear_status() {
		this.dialog.$status_area.empty();
		this._per_stem_rate = null;
		this.update_price_display();
	}

	get_html_for_item_found({ filtered_items_count, filtered_items, exact_match, product_info }) {
		const one_item = exact_match.length === 1
			? exact_match[0]
			: filtered_items_count === 1 ? filtered_items[0] : '';

		const item_add_to_cart = one_item ? `
			<button data-item-code="${one_item}"
				class="btn btn-primary btn-add-to-cart w-100 mt-2"
				data-action="btn_add_to_cart">
				<span class="mr-2">${frappe.utils.icon('assets', 'md')}</span>
				${__("Add to Cart")}
			</button>
		` : '';

		const items_found = filtered_items_count === 1
			? __('{0} item found.', [filtered_items_count])
			: __('{0} items found.', [filtered_items_count]);

		const item_found_status = exact_match.length === 1
			? `<div class="alert alert-success d-flex justify-content-between align-items-center" role="alert">
				<div>
					${one_item}
					${product_info && product_info.price && !$.isEmptyObject(product_info.price)
						? '(' + product_info.price.formatted_price_sales_uom + ')' : ''}
				</div>
				<a href data-action="btn_clear_values" data-item-code="${one_item}">${__('Clear Values')}</a>
			</div>`
			: `<div class="alert alert-warning d-flex justify-content-between align-items-center" role="alert">
				<span>${items_found}</span>
				<a href data-action="btn_clear_values">${__('Clear values')}</a>
			</div>`;

		return `${item_found_status}${item_add_to_cart}`;
	}

	update_price_display() {
		if (!this.$price_display) return;
		const stems = parseInt(this.$total_stems_display ? this.$total_stems_display.val() : 0) || 0;
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
		} else if (this._per_stem_rate === null) {
			this.$price_display.html(`<span style="color:var(--gray-500); font-size:13px;">Select a variant to see price</span>`);
		} else {
			this.$price_display.html(`<span style="color:var(--gray-500); font-size:13px;">Select length and box to see total</span>`);
		}
	}

	btn_add_to_cart(e) {
		if (frappe.session.user !== 'Guest') {
			localStorage.removeItem(this.get_cache_key());
		}
		const item_code = $(e.currentTarget).data('item-code');
		const box_type = this.selected_box_type || '';
		const num_boxes = parseInt(this.$num_boxes_input ? this.$num_boxes_input.val() : 1) || 1;
		const total_stems = parseInt(this.$total_stems_display ? this.$total_stems_display.val() : 0) || 0;
		const num_bunches = parseInt(this.$bunches_display ? this.$bunches_display.val() : 0) || 0;
		const custom_length = this.dialog.get_value('Length') || '';
		const pack_rate = this._pack_rate || 0;

		// Collect specs from product page
		const specs = [];
		$(".item-website-specification table tr").each(function() {
			const label = $(this).find(".spec-label").text().trim();
			const val = $(this).find(".spec-content").text().trim();
			if (label && val) specs.push(`${label}: ${val}`);
		});

		const additional_notes = [
			box_type ? `Box: ${box_type}` : '',
			`No. of Boxes: ${num_boxes}`,
			pack_rate ? `Pack Rate: ${pack_rate} stems/box` : '',
			`Total Stems: ${total_stems} (${num_bunches} bunches × ${BUNCH_SIZE} stems)`,
			specs.length ? `Specs: ${specs.join(", ")}` : '',
		].filter(Boolean).join(' | ');

		webshop.webshop.shopping_cart.update_cart({
			item_code,
			qty: total_stems,
			additional_notes,
			custom_length,
			box_type,
		});
		this.dialog.hide();
	}

	btn_clear_values() {
		this.dialog.fields_list.forEach(f => {
			if (f.df?.options) {
				f.df.options = f.df.options.map(o => ({ ...o, disabled: false }));
			}
		});
		this.dialog.clear();
		this.selected_box_type = '';
		this._pack_rate = null;
		this.dialog.$wrapper.find('.box-type-select').val('');
		this.dialog.$wrapper.find('.num-boxes-input').val(1);
		this.dialog.$wrapper.find('.bunch-size-input').val(BUNCH_SIZE);
		this.dialog.$wrapper.find('.bunches-display').val(0);
		this.dialog.$wrapper.find('.total-stems-display').val(0);
		this.dialog.$wrapper.find('.pack-rate-display').html('');
		this.dialog.$wrapper.find('.stems-validation-msg').html('');
		this._per_stem_rate = null;
		this.update_price_display();
		this.on_attribute_selection();
	}

	append_status_area() {
		const moq_label = this._moq
			? `MOQ: ${this._moq} stems${this._flower_type ? ` (${this._flower_type})` : ''}`
			: '';

		const box_html = `
			<!-- Box Type -->
			<div class="box-selector mb-3 mt-2">
				<label class="d-block mb-2" style="font-weight:600; font-size:13px; color:var(--gray-700);">
					${__('Box Type')}
				</label>
				<select class="form-control box-type-select" style="font-size:13px;">
					<option value="">-- ${__('Select Box')} --</option>
				</select>
			</div>

			<!-- Pack rate info (auto-filled when length + box selected) -->
			<div class="pack-rate-display mb-3" style="min-height:20px;"></div>

			<!-- No. of Boxes (customer fills this) -->
			<div class="mb-3">
				<label class="d-block mb-2" style="font-weight:600; font-size:13px; color:var(--gray-700);">
					${__('No. of Boxes')}
					${moq_label ? `<span style="font-weight:400; color:var(--gray-500); font-size:11px;"> — ${moq_label}</span>` : ''}
				</label>
				<input type="number" class="form-control num-boxes-input" min="1" value="1"
					style="max-width:110px; font-size:15px; font-weight:500;">
			</div>

			<!-- Bunch size × No. of bunches = Total Stems (all read-only, auto-calculated) -->
			<div class="d-flex mb-1" style="gap:12px; flex-wrap:wrap; align-items:flex-end;">
				<div>
					<label class="d-block mb-2" style="font-weight:600; font-size:13px; color:var(--gray-700);">
						${__('Bunch Size')}
					</label>
					<input type="number" class="form-control bunch-size-input" value="${BUNCH_SIZE}" readonly
						style="max-width:90px; font-size:15px; background:#f4f5f6;">
				</div>
				<div style="font-size:22px; font-weight:200; padding-bottom:6px;">×</div>
				<div>
					<label class="d-block mb-2" style="font-weight:600; font-size:13px; color:var(--gray-700);">
						${__('No. of Bunches')}
					</label>
					<input type="number" class="form-control bunches-display" value="0" readonly
						style="max-width:100px; font-size:15px; background:#f4f5f6;">
				</div>
				<div style="font-size:22px; font-weight:200; padding-bottom:6px;">=</div>
				<div>
					<label class="d-block mb-2" style="font-weight:600; font-size:13px; color:var(--gray-700);">
						${__('Total Stems')}
					</label>
					<input type="number" class="form-control total-stems-display" value="0" readonly
						style="max-width:100px; font-size:15px; font-weight:700; background:#f4f5f6;">
				</div>
			</div>

			<div class="stems-validation-msg mb-2"></div>
			<div class="price-display mb-3 p-2" style="min-height:28px; border-radius:6px;"></div>
		`;

		const $box_area = $(box_html);
		this.dialog.$wrapper.find('.modal-body').append($box_area);

		this.dialog.$status_area = $('<div class="status-area mt-2">');
		this.dialog.$wrapper.find('.modal-body').append(this.dialog.$status_area);

		// Cache references
		this.$num_boxes_input = this.dialog.$wrapper.find('.num-boxes-input');
		this.$bunch_size_input = this.dialog.$wrapper.find('.bunch-size-input');
		this.$bunches_display = this.dialog.$wrapper.find('.bunches-display');
		this.$total_stems_display = this.dialog.$wrapper.find('.total-stems-display');
		this.$price_display = this.dialog.$wrapper.find('.price-display');

		// Populate box dropdown — customer-specific if logged in, all boxes otherwise
		frappe.call({
			method: 'upande_webshop.upande_webshop.api.get_customer_boxes',
			callback: (r) => {
				if (r.message) {
					const $select = this.dialog.$wrapper.find('.box-type-select');
					r.message.forEach(item => {
						$select.append($('<option>').val(item.item_name).text(item.item_name));
					});
				}
			}
		});

		// Box type change — update pack rate and recalculate
		this.dialog.$wrapper.on('change', '.box-type-select', (e) => {
			this.selected_box_type = $(e.currentTarget).val();
			this.update_pack_rate_and_totals();
		});

		// No. of boxes change — recalculate totals
		this.dialog.$wrapper.on('input', '.num-boxes-input', () => {
			this.recalculate_totals();
		});

		// Action buttons (Add to Cart, Clear Values)
		this.dialog.$wrapper.on('click', '[data-action]', (e) => {
			e.preventDefault();
			const action = $(e.currentTarget).data('action');
			if (typeof this[action] === 'function') this[action].call(this, e);
		});

		this.dialog.$wrapper.addClass('item-configurator-dialog');
		this.update_price_display();
	}

	get_next_attribute_and_values(selected_attributes) {
		return this.call('upande_webshop.upande_webshop.variant_selector.utils.get_next_attribute_and_values', {
			item_code: this.item_code,
			selected_attributes
		});
	}

	get_attributes_and_values() {
		return this.call('upande_webshop.upande_webshop.variant_selector.utils.get_attributes_and_values', {
			item_code: this.item_code
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

function set_continue_configuration() {
	const $btn_configure = $('.btn-configure');
	const { itemCode } = $btn_configure.data();
	$btn_configure.text(
		localStorage.getItem(`configure:${itemCode}`)
			? __('Continue Selection')
			: __('Select Variant')
	);
}

frappe.ready(() => {
	const $btn_configure = $('.btn-configure');
	if (!$btn_configure.length) return;
	const { itemCode, itemName } = $btn_configure.data();

	set_continue_configuration();

	$btn_configure.on('click', () => {
		$btn_configure.prop('disabled', true);
		new ItemConfigure(itemCode, itemName);
	});
});