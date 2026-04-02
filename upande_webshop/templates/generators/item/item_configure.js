// ============================================================
// Kaitet / Karen Roses — Item Configurator
// Pack rates fetched live from ERPNext Packrate doctype
// Flower type derived from item_group on Item doctype:
//   'Spray Roses'    → MOQ 1000 stems
//   'Standard Roses' → MOQ 1500 stems
// Head size + bud count shown from Item doctype
// Layout: Length → Box Type → Pack Rate → No. of Boxes
//         → No. of Boxes × Pack Rate = Total Stems
//         → Bunch Size × No. of Bunches = Total Stems (same value, shown for clarity)
// ============================================================

const BUNCH_SIZE = 10; // stems per bunch — confirm with Kaitet

const BOX_TYPES = ['Small', 'Standard', 'Large', 'Flower Pack Pro'];

class ItemConfigure {
	constructor(item_code, item_name) {
		this.item_code          = item_code;
		this.item_name          = item_name;
		this.selected_box_type  = '';
		this.selected_pack_rate = null;
		this._per_stem_rate     = null;
		this._currency          = '€';
		this._flower_type       = null;
		this._moq               = 1000;
		this._headsize          = null;
		this._budcount          = null;
		this._box_pack_rates    = {};

		// Step 1: fetch item_group, headsize, budcount from Item doctype
		frappe.call({
			method: 'frappe.client.get_value',
			args: {
				doctype: 'Item',
				filters: { name: this.item_code },
				fieldname: ['item_group', 'custom_headsize_cm', 'custom_budcount']
			},
			callback: (r) => {
				if (r.message) {
					this._flower_type = r.message.item_group;
					this._moq         = (r.message.item_group === 'Spray Roses') ? 1000 : 1500;
					this._headsize    = r.message.custom_headsize_cm || null;
					this._budcount    = r.message.custom_budcount || null;
				}
				// Step 2: fetch pack rates grouped by box type
				this.load_pack_rates().then(() => {
					// Step 3: fetch variant attributes and show dialog
					this.get_attributes_and_values().then(attribute_data => {
						this.attribute_data = attribute_data;
						this.show_configure_dialog();
					});
				});
			}
		});
	}

	load_pack_rates() {
		return new Promise((resolve) => {
			frappe.call({
				method: 'frappe.client.get_list',
				args: {
					doctype: 'Packrate',
					fields: ['packrate', 'box_type'],
					limit_page_length: 500,
					order_by: 'packrate asc'
				},
				callback: (r) => {
					this._box_pack_rates = {};
					if (r.message) {
						r.message.forEach(rec => {
							const box  = rec.box_type;
							const rate = parseInt(rec.packrate);
							if (!this._box_pack_rates[box]) this._box_pack_rates[box] = [];
							if (!this._box_pack_rates[box].includes(rate)) {
								this._box_pack_rates[box].push(rate);
							}
						});
						Object.keys(this._box_pack_rates).forEach(box => {
							this._box_pack_rates[box].sort((a, b) => a - b);
						});
					}
					resolve();
				}
			});
		});
	}

	show_configure_dialog() {
		const fields = this.attribute_data.map(a => ({
			fieldtype: 'Select',
			label: a.attribute,
			fieldname: a.attribute,
			options: a.values.map(v => ({ label: v, value: v })),
			change: (e) => { this.on_attribute_selection(e); }
		}));

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

		this.get_next_attribute_and_values(values).then(data => {
			const { valid_options_for_attributes } = data;
			this.set_item_found_status(data);

			for (let attribute in valid_options_for_attributes) {
				const valid_options = valid_options_for_attributes[attribute];
				const options       = this.dialog.get_field(attribute).df.options;
				const new_options   = options.map(o => {
					o.disabled = !valid_options.includes(o.value);
					return o;
				});
				this.dialog.set_df_property(attribute, 'options', new_options);
				this.dialog.get_field(attribute).set_options();
			}
		});
	}

	// Box type selected → populate pack rate dropdown + show capacity hint
	on_box_type_change(box_name) {
		this.selected_box_type  = box_name;
		this.selected_pack_rate = null;

		const $rate_select    = this.dialog.$wrapper.find('.pack-rate-select');
		const $rate_row       = this.dialog.$wrapper.find('.pack-rate-row');
		const $capacity_hint  = this.dialog.$wrapper.find('.capacity-hint');

		$rate_select.html(`<option value="">-- ${__('Select Pack Rate')} --</option>`);
		$capacity_hint.html('');

		if (!box_name) {
			$rate_row.hide();
			this.recalculate_totals();
			return;
		}

		const rates = this._box_pack_rates[box_name] || [];
		if (rates.length === 0) {
			$rate_select.append(`<option disabled>${__('No pack rates found for this box')}</option>`);
		} else {
			rates.forEach(r => {
				$rate_select.append($('<option>').val(r).text(`${r} stems`));
			});
		}
		$rate_row.show();
		this.recalculate_totals();
	}

	// Pack rate selected → show capacity hint and recalculate
	on_pack_rate_change(rate) {
		this.selected_pack_rate = rate ? parseInt(rate) : null;
		const $capacity_hint    = this.dialog.$wrapper.find('.capacity-hint');

		if (this.selected_pack_rate) {
			const bunches = Math.floor(this.selected_pack_rate / BUNCH_SIZE);
			$capacity_hint.html(`
				<small style="color:var(--gray-600);">
					Max capacity: <strong>${this.selected_pack_rate} stems</strong> per box
					&nbsp;·&nbsp; ${bunches} bunches × ${BUNCH_SIZE} stems
				</small>
			`);
		} else {
			$capacity_hint.html('');
		}

		this.recalculate_totals();
	}

	recalculate_totals() {
		const num_boxes = parseInt(this.$num_boxes_input ? this.$num_boxes_input.val() : 1) || 1;
		const pack_rate = this.selected_pack_rate;

		if (!pack_rate) {
			this._set_totals(0, 0, 0);
			this.validate_moq(0);
			this.update_price_display();
			return;
		}

		const total_stems  = num_boxes * pack_rate;
		const num_bunches  = Math.floor(total_stems / BUNCH_SIZE);

		this._set_totals(total_stems, num_bunches, num_boxes);
		this.validate_moq(total_stems);
		this.update_price_display();
	}

	_set_totals(total_stems, num_bunches, num_boxes) {
		if (this.$boxes_display)       this.$boxes_display.val(num_boxes || 0);
		if (this.$pack_rate_display)   this.$pack_rate_display.val(this.selected_pack_rate || 0);
		if (this.$stems_result)        this.$stems_result.val(total_stems);
		if (this.$bunch_size_display)  this.$bunch_size_display.val(BUNCH_SIZE);
		if (this.$bunches_display)     this.$bunches_display.val(num_bunches);
		if (this.$total_stems_display) this.$total_stems_display.val(total_stems);
	}

	validate_moq(total_stems) {
		const $msg      = this.dialog.$wrapper.find('.stems-validation-msg');
		const moq       = this._moq;
		const pack_rate = this.selected_pack_rate;

		if (total_stems > 0 && total_stems < moq) {
			const boxes_needed = pack_rate ? Math.ceil(moq / pack_rate) : '?';
			const type_label   = this._flower_type ? `(${this._flower_type})` : '';
			$msg.html(`
				<small style="color:#e8a000; font-weight:500;">
					⚠️ Minimum order is ${moq} stems ${type_label}.
					You need at least
					<strong>${boxes_needed} box${boxes_needed !== 1 ? 'es' : ''}</strong>
					to meet the minimum.
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
						this._currency      = r.message.currency || '€';
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
				<a href data-action="btn_clear_values" data-item-code="${one_item}">
					${__('Clear Values')}
				</a>
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
				<span style="font-size:14px; color:var(--gray-700);">
					${this._currency} ${this._per_stem_rate.toFixed(3)} / stem
					&nbsp;×&nbsp; ${stems} stems
					&nbsp;=&nbsp;
					<strong style="font-size:16px;">${this._currency} ${total}</strong>
				</span>
			`);
		} else if (this._per_stem_rate === null) {
			this.$price_display.html(
				`<span style="color:var(--gray-500); font-size:13px;">Select a variant to see price</span>`
			);
		} else {
			this.$price_display.html(
				`<span style="color:var(--gray-500); font-size:13px;">Select box and pack rate to see total</span>`
			);
		}
	}

	btn_add_to_cart(e) {
		if (frappe.session.user !== 'Guest') {
			localStorage.removeItem(this.get_cache_key());
		}
		const item_code     = $(e.currentTarget).data('item-code');
		const box_type      = this.selected_box_type || '';
		const pack_rate     = this.selected_pack_rate || 0;
		const num_boxes     = parseInt(this.$num_boxes_input ? this.$num_boxes_input.val() : 1) || 1;
		const total_stems   = parseInt(this.$total_stems_display ? this.$total_stems_display.val() : 0) || 0;
		const num_bunches   = parseInt(this.$bunches_display ? this.$bunches_display.val() : 0) || 0;
		const custom_length = this.dialog.get_value('Length') || '';

		const specs = [];
		$(".item-website-specification table tr").each(function () {
			const label = $(this).find(".spec-label").text().trim();
			const val   = $(this).find(".spec-content").text().trim();
			if (label && val) specs.push(`${label}: ${val}`);
		});

		const additional_notes = [
			box_type  ? `Box: ${box_type}`                                          : '',
			pack_rate ? `Pack rate: ${pack_rate} stems/box`                         : '',
			`Boxes: ${num_boxes}`,
			`Total Stems: ${total_stems} (${num_bunches} bunches × ${BUNCH_SIZE})`,
			specs.length ? `Specs: ${specs.join(', ')}`                             : '',
		].filter(Boolean).join(' | ');

		upande_webshop.upande_webshop.shopping_cart.update_cart({
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
		this.selected_box_type  = '';
		this.selected_pack_rate = null;
		this._per_stem_rate     = null;

		this.dialog.$wrapper.find('.box-type-select').val('');
		this.dialog.$wrapper.find('.pack-rate-row').hide();
		this.dialog.$wrapper.find('.pack-rate-select').html(
			`<option value="">-- ${__('Select Pack Rate')} --</option>`
		);
		this.dialog.$wrapper.find('.capacity-hint').html('');
		this.dialog.$wrapper.find('.num-boxes-input').val(1);

		// Reset all read-only displays
		this.dialog.$wrapper.find('.boxes-display').val(0);
		this.dialog.$wrapper.find('.pack-rate-display').val(0);
		this.dialog.$wrapper.find('.stems-result').val(0);
		this.dialog.$wrapper.find('.bunch-size-display').val(BUNCH_SIZE);
		this.dialog.$wrapper.find('.bunches-display').val(0);
		this.dialog.$wrapper.find('.total-stems-display').val(0);
		this.dialog.$wrapper.find('.stems-validation-msg').html('');

		this.update_price_display();
		this.on_attribute_selection();
	}

	append_status_area() {
		const is_spray  = this._flower_type === 'Spray Roses';
		const moq_label = `MOQ: ${this._moq} stems (${is_spray ? 'Spray' : 'Standard'})`;

		// Head size / bud count hint
		const spec_parts = [];
		if (this._headsize) spec_parts.push(`Head size: ${this._headsize}cm`);
		if (this._budcount) spec_parts.push(`Buds per stem: ${this._budcount}`);
		const spec_hint = spec_parts.length
			? `<div style="font-size:11px; color:var(--gray-500); margin-bottom:10px;">
				${spec_parts.join(' &nbsp;·&nbsp; ')}
			   </div>`
			: '';

		const box_html = `
			${spec_hint}

			<!-- Box Type -->
			<div class="mb-3 mt-2">
				<label class="d-block mb-1" style="font-weight:600; font-size:13px; color:var(--gray-700);">
					${__('Box Type')}
				</label>
				<select class="form-control box-type-select" style="font-size:13px;">
					<option value="">-- ${__('Select Box')} --</option>
					${BOX_TYPES.map(b => `<option value="${b}">${b}</option>`).join('')}
				</select>
			</div>

			<!-- Pack Rate — revealed once box is selected -->
			<div class="pack-rate-row mb-1" style="display:none;">
				<label class="d-block mb-1" style="font-weight:600; font-size:13px; color:var(--gray-700);">
					${__('Pack Rate')}
					<span style="font-weight:400; color:var(--gray-500); font-size:11px;">
						— stems per box for this variety
					</span>
				</label>
				<select class="form-control pack-rate-select" style="font-size:13px;">
					<option value="">-- ${__('Select Pack Rate')} --</option>
				</select>
				<!-- Capacity hint appears here after pack rate is selected -->
				<div class="capacity-hint mt-1 mb-3" style="min-height:18px;"></div>
			</div>

			<!-- No. of Boxes (editable) -->
			<div class="mb-3">
				<label class="d-block mb-1" style="font-weight:600; font-size:13px; color:var(--gray-700);">
					${__('No. of Boxes')}
					<span style="font-weight:400; color:var(--gray-500); font-size:11px;">
						&nbsp;— ${moq_label}
					</span>
				</label>
				<input type="number" class="form-control num-boxes-input" min="1" value="1"
					style="max-width:110px; font-size:15px; font-weight:500;">
			</div>

			<!-- Row 1: No. of Boxes × Pack Rate = Stems subtotal -->
			<label style="font-weight:600; font-size:13px; color:var(--gray-700); display:block; margin-bottom:6px;">
				${__('Calculation')}
			</label>
			<div class="d-flex mb-2" style="gap:10px; flex-wrap:wrap; align-items:flex-end;">
				<div>
					<label class="d-block mb-1" style="font-size:11px; color:var(--gray-500);">${__('Boxes')}</label>
					<input type="number" class="form-control boxes-display" value="0" readonly
						style="max-width:90px; font-size:14px; font-weight:500; background:#f4f5f6;">
				</div>
				<div style="font-size:18px; font-weight:300; padding-bottom:6px;">×</div>
				<div>
					<label class="d-block mb-1" style="font-size:11px; color:var(--gray-500);">${__('Pack Rate')}</label>
					<input type="number" class="form-control pack-rate-display" value="0" readonly
						style="max-width:90px; font-size:14px; font-weight:500; background:#f4f5f6;">
				</div>
				<div style="font-size:18px; font-weight:300; padding-bottom:6px;">=</div>
				<div>
					<label class="d-block mb-1" style="font-size:11px; color:var(--gray-500);">${__('Stems')}</label>
					<input type="number" class="form-control stems-result" value="0" readonly
						style="max-width:90px; font-size:14px; font-weight:600; background:#f4f5f6;">
				</div>
			</div>

			<!-- Row 2: Bunch Size × No. of Bunches = Total Stems -->
			<div class="d-flex mb-2" style="gap:10px; flex-wrap:wrap; align-items:flex-end;">
				<div>
					<label class="d-block mb-1" style="font-size:11px; color:var(--gray-500);">${__('Bunch Size')}</label>
					<input type="number" class="form-control bunch-size-display" value="${BUNCH_SIZE}" readonly
						style="max-width:90px; font-size:14px; font-weight:500; background:#f4f5f6;">
				</div>
				<div style="font-size:18px; font-weight:300; padding-bottom:6px;">×</div>
				<div>
					<label class="d-block mb-1" style="font-size:11px; color:var(--gray-500);">${__('Bunches')}</label>
					<input type="number" class="form-control bunches-display" value="0" readonly
						style="max-width:90px; font-size:14px; font-weight:500; background:#f4f5f6;">
				</div>
				<div style="font-size:18px; font-weight:300; padding-bottom:6px;">=</div>
				<div>
					<label class="d-block mb-1" style="font-weight:600; font-size:13px; color:var(--gray-700);">
						${__('Total Stems')}
						<span style="font-weight:400; color:var(--gray-500); font-size:11px;">— ${moq_label}</span>
					</label>
					<input type="number" class="form-control total-stems-display" value="0" readonly
						style="max-width:110px; font-size:15px; font-weight:700; background:#f4f5f6;">
				</div>
			</div>

			<div class="stems-validation-msg mb-2"></div>
			<div class="price-display mb-3 p-2" style="min-height:28px; border-radius:6px;"></div>
		`;

		const $box_area = $(box_html);
		this.dialog.$wrapper.find('.modal-body').append($box_area);

		this.dialog.$status_area = $('<div class="status-area mt-2">');
		this.dialog.$wrapper.find('.modal-body').append(this.dialog.$status_area);

		// Cache input references
		this.$num_boxes_input     = this.dialog.$wrapper.find('.num-boxes-input');
		this.$boxes_display       = this.dialog.$wrapper.find('.boxes-display');
		this.$pack_rate_display   = this.dialog.$wrapper.find('.pack-rate-display');
		this.$stems_result        = this.dialog.$wrapper.find('.stems-result');
		this.$bunch_size_display  = this.dialog.$wrapper.find('.bunch-size-display');
		this.$bunches_display     = this.dialog.$wrapper.find('.bunches-display');
		this.$total_stems_display = this.dialog.$wrapper.find('.total-stems-display');
		this.$price_display       = this.dialog.$wrapper.find('.price-display');

		// Box type → populate pack rate dropdown
		this.dialog.$wrapper.on('change', '.box-type-select', (e) => {
			this.on_box_type_change($(e.currentTarget).val());
		});

		// Pack rate → show capacity hint + recalculate
		this.dialog.$wrapper.on('change', '.pack-rate-select', (e) => {
			this.on_pack_rate_change($(e.currentTarget).val());
		});

		// No. of boxes → recalculate
		this.dialog.$wrapper.on('input', '.num-boxes-input', () => {
			this.recalculate_totals();
		});

		// Action buttons
		this.dialog.$wrapper.on('click', '[data-action]', (e) => {
			e.preventDefault();
			const action = $(e.currentTarget).data('action');
			if (typeof this[action] === 'function') this[action].call(this, e);
		});

		this.dialog.$wrapper.addClass('item-configurator-dialog');
		this.update_price_display();
	}

	get_next_attribute_and_values(selected_attributes) {
		return this.call(
			'upande_webshop.upande_webshop.variant_selector.utils.get_next_attribute_and_values',
			{ item_code: this.item_code, selected_attributes }
		);
	}

	get_attributes_and_values() {
		return this.call(
			'upande_webshop.upande_webshop.variant_selector.utils.get_attributes_and_values',
			{ item_code: this.item_code }
		);
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
	const { itemCode }   = $btn_configure.data();
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