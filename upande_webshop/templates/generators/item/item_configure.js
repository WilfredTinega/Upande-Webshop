class ItemConfigure {
	constructor(item_code, item_name) {
		this.item_code = item_code;
		this.item_name = item_name;

		this.get_attributes_and_values()
			.then(attribute_data => {
				this.attribute_data = attribute_data;
				this.show_configure_dialog();
			});
	}

	show_configure_dialog() {
		const fields = this.attribute_data.map(a => {
			return {
				fieldtype: 'Select',
				label: a.attribute,
				fieldname: a.attribute,
				options: a.values.map(v => {
					return { label: v, value: v };
				}),
				change: (e) => {
					this.on_attribute_selection(e);
				}
			};
		});

		fields.push({ fieldtype: 'Section Break', label: __('Order Details') });

		fields.push({
			fieldtype: 'Select',
			label: __('Bunch Size'),
			fieldname: 'bunch_size',
			options: [
				{ label: __('Select bunch size...'), value: '' },
				{ label: '10 Stems', value: '10' },
				{ label: '20 Stems', value: '20' },
				{ label: '25 Stems', value: '25' }
			]
		});

		fields.push({ fieldtype: 'Column Break' });

		fields.push({
			fieldtype: 'Select',
			label: __('Box Type'),
			fieldname: 'box_type',
			options: [
				{ label: __('Select box type...'), value: '' },
				{ label: 'QB (Quarter Box)', value: 'QB' },
				{ label: 'HB (Half Box)', value: 'HB' },
				{ label: 'FB (Full Box)', value: 'FB' }
			]
		});

		fields.push({ fieldtype: 'Column Break' });

		fields.push({
			fieldtype: 'Data',
			label: __('Quantity (Bunches)'),
			fieldname: 'order_qty',
			default: '1'
		});

		this.dialog = new frappe.ui.Dialog({
			title: __('Select Variant for {0}', [this.item_name]),
			fields,
			on_hide: () => {
				set_continue_configuration();
			}
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

		const cached = JSON.parse(localStorage.getItem(this.get_cache_key()));
		if (cached) {
			const attribute_names = this.attribute_data.map(a => a.attribute);
			for (let key in cached) {
				if (attribute_names.includes(key)) {
					this.dialog.set_value(key, cached[key]);
				}
			}
		}

		$('.btn-configure').prop('disabled', false);
	}

	on_attribute_selection(e) {
		if (e) {
			const changed_fieldname = $(e.target).data('fieldname');
			this.show_range_input_if_applicable(changed_fieldname);
		} else {
			this.show_range_input_for_all_fields();
		}

		const values = {};
		this.attribute_data.forEach(a => {
			const val = this.dialog.get_value(a.attribute);
			if (val) values[a.attribute] = val;
		});

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
					const field = this.dialog.get_field(attribute);
					if (!field) continue;
					const options = field.df.options;
					const new_options = options.map(o => {
						o.disabled = !valid_options.includes(o.value);
						return o;
					});

					this.dialog.set_df_property(attribute, 'options', new_options);
					this.dialog.get_field(attribute).set_options();
				}
			});
	}

	show_range_input_for_all_fields() {
		const attribute_names = this.attribute_data.map(a => a.attribute);
		this.dialog.fields.forEach(f => {
			if (attribute_names.includes(f.fieldname)) {
				this.show_range_input_if_applicable(f.fieldname);
			}
		});
	}

	show_range_input_if_applicable(fieldname) {
		const changed_field = this.dialog.get_field(fieldname);
		if (!changed_field) return;
		const changed_value = changed_field.get_value();
		if (changed_value && typeof changed_value === 'string' && changed_value.includes(' to ')) {
			let numbers = changed_value.split(' to ');
			numbers = numbers.map(number => parseFloat(number));

			if (!numbers.some(n => isNaN(n))) {
				numbers.sort((a, b) => a - b);
				if (changed_field.$input_wrapper && changed_field.$input_wrapper.find('.range-selector').length) {
					return;
				}
				const parent = $('<div class="range-selector">')
					.insertBefore(changed_field.$input_wrapper.find('.help-box'));
				const control = frappe.ui.form.make_control({
					df: {
						fieldtype: 'Data',
						label: __('Enter value betweeen {0} and {1}', [numbers[0], numbers[1]]),
						change: () => {
							const value = parseInt(control.get_value()) || 0;
							if (value < numbers[0] || value > numbers[1]) {
								control.$wrapper.addClass('was-validated');
								control.set_description(
									__('Value must be between {0} and {1}', [numbers[0], numbers[1]]));
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

	show_remaining_optional_attributes() {
		const unselected_attributes = this.dialog.fields.filter(df => {
			const value_selected = this.dialog.get_value(df.fieldname);
			return !value_selected;
		});
		const is_optional_attribute = df => {
			const optional_attributes = this.attribute_data
				.filter(a => a.optional).map(a => a.attribute);
			return optional_attributes.includes(df.fieldname);
		};
		if (unselected_attributes.every(is_optional_attribute)) {
			unselected_attributes.forEach(df => {
				this.dialog.fields_dict[df.fieldname].$wrapper.show();
			});
		}
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
	}

	clear_status() {
		this.dialog.$status_area.empty();
	}

	get_html_for_item_found({ filtered_items_count, filtered_items, exact_match, product_info }) {
		const one_item = exact_match.length === 1
			? exact_match[0]
			: filtered_items_count === 1
				? filtered_items[0]
				: '';

		const item_add_to_cart = one_item ? `
			<button data-item-code="${one_item}"
				class="btn btn-primary btn-add-to-cart w-100"
				data-action="btn_add_to_cart"
			>
				<span class="mr-2">
					${frappe.utils.icon('assets', 'md')}
				</span>
				${__("Add to Cart")}
			</button>
		` : '';

		const items_found = filtered_items_count === 1 ?
			__('{0} item found.', [filtered_items_count]) :
			__('{0} items found.', [filtered_items_count]);

		const item_found_status = exact_match.length === 1
			? `<div class="alert alert-success d-flex justify-content-between align-items-center" role="alert">
				<div><div>
					${one_item}
					${product_info && product_info.price && !$.isEmptyObject(product_info.price)
						? '(' + product_info.price.formatted_price_sales_uom + ')'
						: ''
					}
				</div></div>
				<a href data-action="btn_clear_values" data-item-code="${one_item}">
					${__('Clear Values')}
				</a>
			</div>`
			: `<div class="alert alert-warning d-flex justify-content-between align-items-center" role="alert">
					<span>
						${items_found}
					</span>
					<a href data-action="btn_clear_values">
						${__('Clear values')}
					</a>
			</div>`;

		return `
			${item_found_status}
			${item_add_to_cart}
		`;
	}

	btn_add_to_cart(e) {
		const bunchSize = this.dialog.get_value('bunch_size');
		const boxType = this.dialog.get_value('box_type');
		const orderQty = parseInt(this.dialog.get_value('order_qty')) || 0;

		let missing = [];
		if (!bunchSize) missing.push(__('Bunch Size'));
		if (!boxType) missing.push(__('Box Type'));
		if (!orderQty || orderQty < 1) missing.push(__('Quantity'));

		if (missing.length) {
			frappe.show_alert({
				message: __('Please fill in: ') + missing.join(', '),
				indicator: 'red'
			}, 5);
			this.dialog.$wrapper.find('.modal-body').animate({
				scrollTop: this.dialog.$wrapper.find('.modal-body')[0].scrollHeight
			}, 300);
			return;
		}

		if (frappe.session.user !== 'Guest') {
			localStorage.removeItem(this.get_cache_key());
		}

		const item_code = $(e.currentTarget).data('item-code');

		const stemsPerBunch = parseInt(bunchSize) || 1;
		const totalStems = stemsPerBunch * orderQty;

		const notes_parts = [];

		if (this.range_values) {
			Object.keys(this.range_values).forEach(attribute => {
				notes_parts.push(`${attribute}: ${this.range_values[attribute]}`);
			});
		}

		const bunchField = this.dialog.get_field('bunch_size');
		const boxField = this.dialog.get_field('box_type');
		const bunchText = bunchField ? bunchField.$input.find('option:selected').text().trim() : bunchSize;
		const boxText = boxField ? boxField.$input.find('option:selected').text().trim() : boxType;

		notes_parts.push(`Bunch Size: ${bunchText}`);
		notes_parts.push(`Box Type: ${boxText}`);
		notes_parts.push(`Bunches: ${orderQty}`);
		notes_parts.push(`Total Stems: ${totalStems}`);

		const additional_notes = notes_parts.join('\n');

		frappe.call({
			method: 'upande_webshop.upande_webshop.shopping_cart.cart.update_cart',
			args: {
				item_code: item_code,
				qty: totalStems,
				additional_notes: additional_notes,
				with_items: true
			},
			callback: (r) => {
				if (r.message) {
					frappe.show_alert({
						message: __('Added to cart: {0} × {1} stems ({2} bunches of {3}, {4})', 
							[item_code, totalStems, orderQty, bunchText, boxText]),
						indicator: 'green'
					}, 5);
					// Update cart indicator in header
					$('.cart-badge, .shopping-cart-header .badge').text(
						r.message.doc && r.message.doc.items ? r.message.doc.items.length : ''
					);
				}
			}
		});
		this.dialog.hide();
	}

	btn_clear_values() {
		this.dialog.fields_list.forEach(f => {
			if (f.df?.options) {
				f.df.options = f.df.options.map(option => {
					option.disabled = false;
					return option;
				});
			}
		});
		this.dialog.clear();
		this.dialog.set_value('order_qty', '1');
		this.on_attribute_selection();
	}

	append_status_area() {
		this.dialog.$status_area = $('<div class="status-area mt-5">');
		this.dialog.$wrapper.find('.modal-body').append(this.dialog.$status_area);
		this.dialog.$wrapper.on('click', '[data-action]', (e) => {
			e.preventDefault();
			const $target = $(e.currentTarget);
			const action = $target.data('action');
			const method = this[action];
			method.call(this, e);
		});
		this.dialog.$wrapper.addClass('item-configurator-dialog');
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

	if (localStorage.getItem(`configure:${itemCode}`)) {
		$btn_configure.text(__('Continue Selection'));
	} else {
		$btn_configure.text(__('Select Variant'));
	}
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
