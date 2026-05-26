// Non-variant product page: multi-select stem lengths.
// Each selected length gets its own bunches input and its own
// Quotation Item row (one update_cart call per length).

const _nv_pack_rate_cache = {};
const _nv_bunch_size_cache = {};
const _nv_length_price_cache = {};

function nv_fetch_bunch_size(item_code) {
	if (!item_code) return Promise.resolve({ size: 1, uom: null });
	if (_nv_bunch_size_cache[item_code] !== undefined) {
		return Promise.resolve(_nv_bunch_size_cache[item_code]);
	}
	return new Promise((resolve) => {
		frappe.call({
			method: 'upande_webshop.api.pack_rate.get_item_bunch_size',
			args: { item_code },
			callback: (r) => {
				const msg = (r && r.message) || {};
				const result = { size: msg.bunch_size || 1, uom: msg.sales_uom || null };
				_nv_bunch_size_cache[item_code] = result;
				resolve(result);
			},
			error: () => resolve({ size: 1, uom: null }),
		});
	});
}

function nv_fetch_pack_rate(box_name, length_cm) {
	if (!box_name || !length_cm) return Promise.resolve({ pack_rate: null });
	const key = `${box_name}|${length_cm}`;
	if (_nv_pack_rate_cache[key] !== undefined) {
		return Promise.resolve(_nv_pack_rate_cache[key]);
	}
	return new Promise((resolve) => {
		frappe.call({
			method: 'upande_webshop.api.pack_rate.get_pack_rate',
			args: { box_name, length_cm },
			callback: (r) => {
				const result = (r && r.message) || { pack_rate: null };
				_nv_pack_rate_cache[key] = result;
				resolve(result);
			},
			error: () => resolve({ pack_rate: null }),
		});
	});
}

function nv_fetch_length_price(item_code, length, currency, price_list) {
	const key = `${item_code}|${length}|${currency || ''}|${price_list || ''}`;
	if (_nv_length_price_cache[key] !== undefined) {
		return Promise.resolve(_nv_length_price_cache[key]);
	}
	return new Promise((resolve) => {
		frappe.call({
			method: 'upande_webshop.upande_webshop.doctype.webshop_item_prices.webshop_item_prices.get_item_length_price',
			args: { item_code, length, currency, price_list },
			callback: (r) => {
				const result = (r && r.message) || {};
				_nv_length_price_cache[key] = result;
				resolve(result);
			},
			error: () => resolve({}),
		});
	});
}

class InlineNonVariantSelector {
	constructor($root, item_code, item_name) {
		this.$root = $root;
		this.item_code = item_code;
		this.item_name = item_name;

		const meta = document.getElementById('product-meta');
		this._currency_code = (meta && meta.dataset.currency) || 'USD';
		this._price_list = (meta && meta.dataset.priceList) || '';
		const symbols = { USD: '$', EUR: '€', GBP: '£', KES: 'KSh' };
		this._currency = symbols[this._currency_code] || (this._currency_code + ' ');

		// Map<length, { stock_qty, per_stem_rate, num_bunches, pack_rate }>
		this.length_state = new Map();
		this.selected_box_type = '';
		this.bunch_size = 1;
		this.bunch_uom = null;
		this._on_backorder = false;

		this.$stem_toggle = $root.find('.stem-length-toggle');
		this.$box_area = $root.find('.box-type-area');
		this.$box_toggle = $root.find('.box-type-toggle');
		this.$pack_rate_display = $root.find('.pack-rate-display');
		this.$totals_area = $root.find('.totals-area');
		this.$length_rows = $root.find('.length-rows');
		this.$grand_totals = $root.find('.grand-totals');
		this.$grand_bunches = $root.find('.grand-bunches');
		this.$grand_stems = $root.find('.grand-stems');
		this.$price_display = $root.find('.price-display');
		this.$status_area = $root.find('.status-area');
		this.$variant_label_area = $root.find('.variant-label-area');
		this.$add_to_cart = $root.find('.btn-add-to-cart-non-variant');
		this.$moq_label = $root.find('.moq-label');

		nv_fetch_bunch_size(this.item_code).then((info) => {
			this.bunch_size = Math.max(parseInt(info.size) || 1, 1);
			this.bunch_uom = info.uom || null;
			this.length_state.forEach((_, length) => this.autofill_bunches_for(length));
			this.refresh_all_rows();
		});

		this.load_box_types();
		this.bind_events();
		this.restore_from_cache();
		this.update_addable_state();
	}

	get selected_lengths() {
		return Array.from(this.length_state.keys());
	}

	get_stock_qty(length) {
		const $btn = this.$stem_toggle.find(
			`.stem-length-btn[data-value="${$.escapeSelector(String(length))}"]`
		);
		return $btn.length ? Number($btn.data('stock-qty')) || 0 : 0;
	}

	bind_events() {
		this.$root.on('click', '.stem-length-toggle .stem-length-btn', (e) => {
			e.preventDefault();
			const $btn = $(e.currentTarget);
			if ($btn.is(':disabled') || $btn.hasClass('oos')) return;
			const value = String($btn.data('value'));
			if (this.length_state.has(value)) {
				this.length_state.delete(value);
				$btn.removeClass('active');
			} else {
				this.length_state.set(value, {
					stock_qty: this.get_stock_qty(value),
					per_stem_rate: null,
					num_bunches: 0,
					pack_rate: null,
					user_edited: false,
				});
				$btn.addClass('active');
				this.fetch_per_stem_rate_for(value);
				this.fetch_pack_rate_for(value);
			}
			this.persist_cache();
			this.render_length_rows();
			this.update_addable_state();
		});

		this.$root.on('click', '.box-type-toggle .box-btn', (e) => {
			e.preventDefault();
			const $btn = $(e.currentTarget);
			const value = String($btn.data('value'));
			if (this.selected_box_type === value) return;
			this.selected_box_type = value;
			$btn.siblings('.box-btn').removeClass('active');
			$btn.addClass('active');
			this.persist_cache();
			this.refresh_moq_for_box().then(() => {
				this.length_state.forEach((_, length) => this.fetch_pack_rate_for(length));
			});
		});

		this.$root.on('input', '.bunches-input', (e) => {
			const $input = $(e.currentTarget);
			const length = String($input.closest('.length-row').data('length'));
			const state = this.length_state.get(length);
			if (!state) return;
			state.num_bunches = Math.max(parseInt($input.val()) || 0, 0);
			state.user_edited = true;
			this.update_row(length);
			this.update_grand_totals();
			this.update_addable_state();
		});

		this.$add_to_cart.on('click', (e) => {
			e.preventDefault();
			this.add_to_cart();
		});
	}

	render_length_rows() {
		this.$length_rows.empty();
		if (!this.length_state.size) {
			this.$totals_area.hide();
			this.$grand_totals.hide();
			return;
		}
		this.$totals_area.css('display', 'block');
		this.$grand_totals.css('display', 'flex');

		const tpl = (length, state) => {
			const stockText = (state.stock_qty != null)
				? `${__('Stock')}: ${Number(state.stock_qty).toLocaleString()}`
				: '';
			return `
				<div class="length-row" data-length="${frappe.utils.escape_html(length)}">
					<div>
						<span class="length-tag">${frappe.utils.escape_html(length)}</span>
						${stockText ? `<span class="length-stock">${frappe.utils.escape_html(stockText)}</span>` : ''}
					</div>
					<div>
						<label class="d-block mb-1" style="font-weight:600; font-size:12px; color:var(--gray-700);">
							${__('Bunch Size')}
						</label>
						<input type="number" class="form-control bunch-size-display" value="${this.bunch_size}" readonly>
					</div>
					<div style="font-size:18px; font-weight:200; padding-bottom:4px;">×</div>
					<div>
						<label class="d-block mb-1" style="font-weight:600; font-size:12px; color:var(--gray-700);">
							${__('No. of Bunches')}
						</label>
						<input type="number" class="form-control bunches-input" value="${state.num_bunches || 0}" min="0">
					</div>
					<div style="font-size:18px; font-weight:200; padding-bottom:4px;">=</div>
					<div>
						<label class="d-block mb-1" style="font-weight:600; font-size:12px; color:var(--gray-700);">
							${__('Total Stems')}
						</label>
						<input type="number" class="form-control total-stems" value="0" readonly>
					</div>
					<div class="row-line-price ml-auto" style="font-size:13px; color:var(--gray-700); align-self:center;"></div>
					<div class="row-msg"></div>
				</div>
			`;
		};

		this.length_state.forEach((state, length) => {
			this.$length_rows.append(tpl(length, state));
		});

		// Re-render derived fields for each row.
		this.length_state.forEach((_, length) => this.update_row(length));
		this.update_grand_totals();
	}

	refresh_all_rows() {
		this.render_length_rows();
	}

	update_row(length) {
		const state = this.length_state.get(length);
		const $row = this.$length_rows.find(
			`.length-row[data-length="${$.escapeSelector(length)}"]`
		);
		if (!state || !$row.length) return;

		const total_stems = (state.num_bunches || 0) * (this.bunch_size || 1);
		$row.find('.total-stems').val(total_stems);
		$row.find('.bunch-size-display').val(this.bunch_size);

		const $msg = $row.find('.row-msg');
		const $line_price = $row.find('.row-line-price');
		const stock_qty = (state.stock_qty != null) ? Number(state.stock_qty) : null;
		const moq_bunches = this._moq_bunches || 0;

		let msg = '';
		if (total_stems > 0 && moq_bunches > 0 && state.num_bunches < moq_bunches) {
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
			$line_price.html(`<strong>${this._currency} ${total}</strong>`);
		} else if (state.per_stem_rate === null && total_stems > 0) {
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
		this.length_state.forEach((state) => {
			const nb = state.num_bunches || 0;
			const ts = nb * (this.bunch_size || 1);
			bunches += nb;
			stems += ts;
			if (state.per_stem_rate) grand_price += state.per_stem_rate * ts;
		});
		this.$grand_bunches.text(bunches.toLocaleString());
		this.$grand_stems.text(stems.toLocaleString());
		if (grand_price > 0) {
			this.$price_display.html(
				`<div style="font-size:14px; color:var(--gray-700);">
					${__('Order total')}: <strong style="font-size:16px;">${this._currency} ${grand_price.toFixed(2)}</strong>
				</div>`
			);
		} else {
			this.$price_display.empty();
		}
	}

	fetch_per_stem_rate_for(length) {
		nv_fetch_length_price(this.item_code, length, this._currency_code, this._price_list).then((result) => {
			const state = this.length_state.get(length);
			if (!state) return;
			const rate = parseFloat(result.price_list_rate);
			state.per_stem_rate = (!isNaN(rate) && rate > 0) ? rate : null;
			this.update_row(length);
			this.update_grand_totals();
			this.update_addable_state();
		});
	}

	fetch_pack_rate_for(length) {
		const cm = this.length_to_cm(length);
		if (!cm || !this.selected_box_type) return;
		nv_fetch_pack_rate(this.selected_box_type, cm).then((result) => {
			const state = this.length_state.get(length);
			if (!state) return;
			state.pack_rate = result.pack_rate;
			this.autofill_bunches_for(length);
			this.update_pack_rate_display();
			this.update_row(length);
			this.update_grand_totals();
			this.update_addable_state();
		});
	}

	autofill_bunches_for(length) {
		// One box's worth of bunches = pack_rate / bunch_size.
		// Don't overwrite a value the user has already typed.
		const state = this.length_state.get(length);
		if (!state || state.user_edited) return;
		if (!state.pack_rate || !this.bunch_size) return;
		const bunches = Math.floor(state.pack_rate / this.bunch_size);
		if (bunches > 0) {
			state.num_bunches = bunches;
			const $input = this.$length_rows.find(
				`.length-row[data-length="${$.escapeSelector(String(length))}"] .bunches-input`
			);
			if ($input.length) $input.val(bunches);
		}
	}

	update_pack_rate_display() {
		if (!this.selected_box_type) {
			this.$pack_rate_display.empty();
			return;
		}
		const parts = [];
		this.length_state.forEach((state, length) => {
			if (state.pack_rate) {
				parts.push(`${frappe.utils.escape_html(length)}: <strong>${state.pack_rate} stems/box</strong>`);
			}
		});
		this.$pack_rate_display.html(
			parts.length
				? `<small style="color:var(--gray-600);">${parts.join(' · ')}</small>`
				: ''
		);
	}

	length_to_cm(length) {
		const match = String(length).match(/(\d+)/);
		return match ? parseInt(match[1]) : null;
	}

	load_box_types() {
		if (!this.$box_area.length) return;
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
				this.apply_cached_box_selection();
			},
			error: () => this.$box_area.hide(),
		});
	}

	apply_cached_box_selection() {
		if (!this.selected_box_type) return;
		const $btn = this.$box_toggle.find(
			`.box-btn[data-value="${$.escapeSelector(this.selected_box_type)}"]`
		);
		if (!$btn.length) {
			this.selected_box_type = '';
			return;
		}
		$btn.addClass('active');
		this.refresh_moq_for_box().then(() => {
			this.length_state.forEach((_, length) => this.fetch_pack_rate_for(length));
		});
	}

	refresh_moq_for_box() {
		const box = this.selected_box_type;
		if (!box) {
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
					this.$moq_label.text(
						bunches ? ` — MOQ: ${bunches} bunch${bunches > 1 ? 'es' : ''}` : ''
					);
					// Seed any rows that haven't been touched yet (pack-rate auto-fill takes precedence and runs after).
					if (bunches) {
						this.length_state.forEach((state) => {
							if (!state.num_bunches && !state.user_edited) state.num_bunches = bunches;
						});
						this.render_length_rows();
						this.update_grand_totals();
						this.update_addable_state();
					}
					resolve();
				},
				error: () => {
					this._moq_bunches = 0;
					this.$moq_label.text('');
					resolve();
				}
			});
		});
	}

	update_addable_state() {
		if (!this.length_state.size) {
			this.$add_to_cart.prop('disabled', true);
			return;
		}
		let ok = false;
		let blocked = false;
		this.length_state.forEach((state) => {
			const stems = (state.num_bunches || 0) * (this.bunch_size || 1);
			if (stems <= 0) return;
			const stock_qty = (state.stock_qty != null) ? Number(state.stock_qty) : null;
			const within_stock = (stock_qty == null) || stems <= stock_qty;
			const meets_moq = !this._moq_bunches || state.num_bunches >= this._moq_bunches;
			if (within_stock && meets_moq) ok = true;
			else blocked = true;
		});
		this.$add_to_cart.prop('disabled', !ok || blocked);
	}

	persist_cache() {
		const state = {
			lengths: Array.from(this.length_state.keys()),
		};
		if (this.selected_box_type) state.box_type = this.selected_box_type;
		if (state.lengths.length === 0 && !state.box_type) {
			localStorage.removeItem(this.get_cache_key());
		} else {
			localStorage.setItem(this.get_cache_key(), JSON.stringify(state));
		}
	}

	restore_from_cache() {
		try {
			const raw = localStorage.getItem(this.get_cache_key());
			if (!raw) return;
			const saved = JSON.parse(raw) || {};
			const cached_lengths = Array.isArray(saved.lengths)
				? saved.lengths
				: (saved.stem_length ? [saved.stem_length] : []);
			cached_lengths.forEach((length) => {
				const $btn = this.$stem_toggle.find(
					`.stem-length-btn[data-value="${$.escapeSelector(String(length))}"]`
				);
				if (!$btn.length || $btn.is(':disabled') || $btn.hasClass('oos')) return;
				this.length_state.set(String(length), {
					stock_qty: this.get_stock_qty(length),
					per_stem_rate: null,
					num_bunches: 0,
					pack_rate: null,
					user_edited: false,
				});
				$btn.addClass('active');
				this.fetch_per_stem_rate_for(String(length));
			});
			if (saved.box_type) {
				this.selected_box_type = String(saved.box_type);
			}
			this.render_length_rows();
			this.update_addable_state();
		} catch (e) {
			// ignore corrupt cache
		}
	}

	add_to_cart() {
		const entries = [];
		this.length_state.forEach((state, length) => {
			const nb = state.num_bunches || 0;
			const stems = nb * (this.bunch_size || 1);
			if (stems <= 0) return;
			const stock_qty = (state.stock_qty != null) ? Number(state.stock_qty) : null;
			if (stock_qty != null && stems > stock_qty) return;
			if (this._moq_bunches && nb < this._moq_bunches) return;
			entries.push({ length, num_bunches: nb, stems, pack_rate: state.pack_rate || 0 });
		});

		if (!entries.length) {
			frappe.msgprint({
				title: __('Enter quantity'),
				message: __('Enter the number of bunches for at least one stem length.'),
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

		const specs = [];
		$('.item-website-specification table tr').each(function () {
			const label = $(this).find('.spec-label').text().trim();
			const val = $(this).find('.spec-content').text().trim();
			if (label && val) specs.push(`${label}: ${val}`);
		});

		this.$add_to_cart.prop('disabled', true);

		const post_one = (entry) => new Promise((resolve) => {
			const additional_notes = [
				this.selected_box_type ? `Box: ${this.selected_box_type}` : '',
				entry.pack_rate ? `Pack Rate: ${entry.pack_rate} stems/box` : '',
				`Total Stems: ${entry.stems} (${entry.num_bunches} bunches × ${this.bunch_size} stems)`,
				specs.length ? `Specs: ${specs.join(', ')}` : '',
			].filter(Boolean).join(' | ');

			upande_webshop.upande_webshop.shopping_cart.update_cart({
				item_code: this.item_code,
				qty: entry.num_bunches,
				uom: this.bunch_uom || undefined,
				additional_notes,
				custom_length: entry.length,
				custom_box_type: this.selected_box_type || undefined,
				callback: (r) => resolve(!(r && r.exc)),
			});
		});

		const run = async () => {
			let ok_count = 0;
			for (const entry of entries) {
				const ok = await post_one(entry);
				if (ok) ok_count += 1;
			}
			this.update_addable_state();
			if (ok_count) {
				frappe.show_alert({
					message: __('Added {0} stem length{1} to your cart.', [ok_count, ok_count === 1 ? '' : 's']),
					indicator: 'green',
				});
				$('.btn-view-in-cart').removeClass('hidden');
			}
		};
		run();
	}

	get_cache_key() {
		return `configure:${this.item_code}`;
	}
}

frappe.ready(() => {
	const $root = $('.inline-non-variant-selector');
	if (!$root.length) return;
	const { itemCode, itemName } = $root.data();
	new InlineNonVariantSelector($root, itemCode, itemName);
});
