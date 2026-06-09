// Non-variant product page: multi-select stem lengths.
// Each selected length gets its own bunches input and its own
// Quotation Item row (one update_cart call per length).
//
// Box type, pack-rate, and MOQ are NOT chosen here — they belong on the cart
// page. This page only picks stem lengths, bunch size, and qty.

const _nv_bunch_size_cache = {};
const _nv_length_price_cache = {};
const _nv_item_uoms_cache = {};

function nv_fetch_item_uoms(item_code) {
	// Returns { uoms: [{uom, bunch_size}], default_uom } — the global Bunch UOM
	// set. Drives the per-length Bunch Size dropdown (mirrors the variant flow).
	if (!item_code) return Promise.resolve({ uoms: [], default_uom: null });
	if (_nv_item_uoms_cache[item_code] !== undefined) {
		return Promise.resolve(_nv_item_uoms_cache[item_code]);
	}
	return new Promise((resolve) => {
		frappe.call({
			method: 'upande_webshop.upande_webshop.doctype.box_type.box_type.get_item_uoms',
			args: { item_code },
			callback: (r) => {
				const result = (r && r.message) || { uoms: [], default_uom: null };
				_nv_item_uoms_cache[item_code] = result;
				resolve(result);
			},
			error: () => resolve({ uoms: [], default_uom: null }),
		});
	});
}

function nv_fetch_bunch_size(item_code) {
	if (!item_code) return Promise.resolve({ size: 1, uom: null });
	if (_nv_bunch_size_cache[item_code] !== undefined) {
		return Promise.resolve(_nv_bunch_size_cache[item_code]);
	}
	return new Promise((resolve) => {
		frappe.call({
			method: 'upande_webshop.upande_webshop.doctype.box_type.box_type.get_item_bunch_size',
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

		// Map<length, { stock_qty, per_stem_rate, num_stems, num_bunches,
		//   bunch_size, bunch_uom, user_edited }>
		// bunch_size/bunch_uom are per-length so each row's Bunch Size dropdown
		// can be set independently (mirrors the variant flow).
		this.length_state = new Map();
		this.bunch_size = 1;
		this.bunch_uom = null;
		// Global Bunch UOM options for the per-row dropdown.
		this.bunch_uoms = [];
		this._on_backorder = false;

		this.$stem_toggle = $root.find('.stem-length-toggle');
		this.$totals_area = $root.find('.totals-area');
		this.$length_rows = $root.find('.length-rows');
		this.$grand_totals = $root.find('.grand-totals');
		this.$grand_bunches = $root.find('.grand-bunches');
		this.$grand_stems = $root.find('.grand-stems');
		this.$price_display = $root.find('.price-display');
		this.$status_area = $root.find('.status-area');
		this.$variant_label_area = $root.find('.variant-label-area');
		this.$add_to_cart = $root.find('.btn-add-to-cart-non-variant');

		// Compact mode (wishlist): pick a length and it's staged automatically at
		// qty 1 as a read-only green summary line — no per-length editing block.
		// Add to Cart posts each staged length, then drops the item from the
		// wishlist. Mirrors the variant selector's compact flow.
		this.compact = $root.attr('data-compact') === '1';

		nv_fetch_bunch_size(this.item_code).then((info) => {
			this.bunch_size = Math.max(parseInt(info.size) || 1, 1);
			this.bunch_uom = info.uom || null;
			// Seed any rows staged before this resolved (e.g. from cache) with the
			// default bunch size/uom; don't clobber a user's dropdown choice.
			this.length_state.forEach((state) => {
				if (!state.bunch_size) state.bunch_size = this.bunch_size;
				if (!state.bunch_uom) state.bunch_uom = this.bunch_uom;
			});
			this.refresh_all_rows();
		});

		nv_fetch_item_uoms(this.item_code).then((info) => {
			this.bunch_uoms = (info && info.uoms) || [];
			const default_uom = (info && info.default_uom)
				|| (this.bunch_uoms[0] && this.bunch_uoms[0].uom) || null;
			// If the bunch-size lookup hasn't set a default uom yet, take the
			// smallest bunch from the dropdown options.
			if (!this.bunch_uom && default_uom) {
				this.bunch_uom = default_uom;
				this.bunch_size = Math.max(parseInt(this.bunch_uoms[0].bunch_size) || 1, 1);
			}
			// Reconcile each staged row's uom against the loaded options so the
			// rendered dropdown selection and state.bunch_size stay in sync. A
			// user who already changed a row hasn't — their choice came from these
			// same options, so it's always present here.
			this.length_state.forEach((state) => {
				const match = this.bunch_uoms.find((u) => u.uom === state.bunch_uom);
				if (!match && default_uom) {
					state.bunch_uom = default_uom;
				}
				const sel = this.bunch_uoms.find((u) => u.uom === state.bunch_uom);
				if (sel) state.bunch_size = Math.max(parseInt(sel.bunch_size) || 1, 1);
			});
			this.refresh_all_rows();
		});

		this.bind_events();
		// Wishlist cards don't persist a selection across loads — only the detail
		// page restores from localStorage.
		if (!this.compact) this.restore_from_cache();
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
					num_stems: 0,
					num_bunches: 1,
					user_edited: false,
					bunch_size: this.bunch_size,
					bunch_uom: this.bunch_uom,
				});
				$btn.addClass('active');
				this.fetch_per_stem_rate_for(value);
			}
			this.persist_cache();
			this.render_length_rows();
			this.update_addable_state();
		});

		this.$root.on('input', '.bunches-input', (e) => {
			const $input = $(e.currentTarget);
			const length = String($input.closest('.length-row').data('length'));
			const state = this.length_state.get(length);
			if (!state) return;
			let raw = Math.max(parseInt($input.val()) || 0, 0);
			// Clamp at per-length stock cap. data-max-bunches is set on render from
			// floor(stock / bunch_size); enforce both the spinner-click path and
			// typed/pasted values here.
			const maxAttr = parseInt($input.attr('data-max-bunches'));
			if (!isNaN(maxAttr) && maxAttr >= 0 && raw > maxAttr) {
				raw = maxAttr;
				$input.val(raw);
			}
			state.num_bunches = raw;
			state.user_edited = true;
			this.update_row(length);
			this.update_grand_totals();
			this.update_addable_state();
		});

		this.$root.on('change', '.length-row .bunch-uom-select', (e) => {
			const $sel = $(e.currentTarget);
			const length = String($sel.closest('.length-row').data('length'));
			const state = this.length_state.get(length);
			if (!state) return;
			state.bunch_uom = $sel.val();
			state.bunch_size = Math.max(
				parseInt($sel.find('option:selected').data('bunch-size')) || 1, 1
			);
			// Re-render so the stems cap and Total Stems recompute against the
			// new bunch size for this length.
			this.render_length_rows();
			this.update_grand_totals();
			this.update_addable_state();
		});

		this.$add_to_cart.on('click', (e) => {
			e.preventDefault();
			this.add_to_cart();
		});
	}

	render_length_rows() {
		// Compact mode (wishlist): one green summary line per staged length,
		// no qty/bunch editing block.
		if (this.compact) {
			this.render_compact_rows();
			return;
		}
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
			// User enters bunches (Qty); stems = qty × bunch_size. Cap qty so total
			// stems never exceed stock. 0 = no cap (stock unknown or not tracked).
			// Click-time enforcement lives in the `input` handler — `max` alone
			// doesn't block browser spinner clicks.
			const bunchSize = state.bunch_size || this.bunch_size || 1;
			const maxBunches = state.stock_qty != null && state.stock_qty >= 0
				? Math.floor(Number(state.stock_qty) / bunchSize)
				: '';
			const maxAttr = maxBunches !== '' ? `max="${maxBunches}"` : '';
			const dataMaxAttr = maxBunches !== '' ? `data-max-bunches="${maxBunches}"` : '';
			const numBunches = state.num_bunches || 0;
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
						${(() => {
							const opts = (this.bunch_uoms && this.bunch_uoms.length)
								? this.bunch_uoms
								: (state.bunch_uom ? [{ uom: state.bunch_uom, bunch_size: bunchSize }] : []);
							if (!opts.length) {
								return `<input type="text" class="form-control bunch-size-display" value="${frappe.utils.escape_html(state.bunch_uom || bunchSize)}" readonly>`;
							}
							const options = opts.map((u) => {
								const sel = u.uom === state.bunch_uom ? 'selected' : '';
								return `<option value="${frappe.utils.escape_html(u.uom)}" data-bunch-size="${u.bunch_size || 1}" ${sel}>${frappe.utils.escape_html(u.uom)}</option>`;
							}).join('');
							return `<select class="form-control bunch-uom-select">${options}</select>`;
						})()}
					</div>
					<div style="font-size:18px; font-weight:200; padding-bottom:4px;">×</div>
					<div>
						<label class="d-block mb-1" style="font-weight:600; font-size:12px; color:var(--gray-700);">
							${__('Qty')}
						</label>
						<input type="number" class="form-control bunches-input" value="${numBunches}" min="0" ${maxAttr} ${dataMaxAttr}>
					</div>
					<div style="font-size:18px; font-weight:200; padding-bottom:4px;">=</div>
					<div>
						<label class="d-block mb-1" style="font-weight:600; font-size:12px; color:var(--gray-700);">
							${__('Stems')}
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

	render_compact_rows() {
		// Wishlist: one green line per staged length showing total stems and price
		// — no editing block, no grand totals. Each length is staged at qty 1
		// (its default), so stems = bunch_size. Add to Cart posts each at that qty.
		this.$length_rows.empty();
		this.$grand_totals.hide();
		if (!this.length_state.size) {
			this.$totals_area.hide();
			return;
		}
		this.$totals_area.css('display', 'block');

		this.length_state.forEach((state, length) => {
			const bunchSize = state.bunch_size || this.bunch_size || 1;
			const num_bunches = state.num_bunches || 1;
			const stems = num_bunches * bunchSize;
			state.num_stems = stems;
			const total = state.per_stem_rate
				? `${this._currency} ${(state.per_stem_rate * stems).toFixed(2)}`
				: __('No price configured');
			this.$length_rows.append(`
				<div class="length-compact-row" data-length="${frappe.utils.escape_html(length)}"
					style="color:var(--green-600); font-weight:500; font-size:11px;
						line-height:1.4; padding:3px 0; white-space:nowrap;
						overflow:hidden; text-overflow:ellipsis;">
					${frappe.utils.escape_html(length)}
					— ${stems.toLocaleString()} ${__('stems')} · ${frappe.utils.escape_html(total)}
				</div>
			`);
		});
	}

	update_row(length) {
		const state = this.length_state.get(length);
		const $row = this.$length_rows.find(
			`.length-row[data-length="${$.escapeSelector(length)}"]`
		);
		if (!state || !$row.length) return;

		// Refresh the stock cap on the qty (bunches) input. Stock may have changed
		// since render. Cap = floor(stock / bunch_size) so total stems fit stock.
		const $bunches = $row.find('.bunches-input');
		const bunchSize = state.bunch_size || this.bunch_size || 1;
		if (state.stock_qty != null && state.stock_qty >= 0) {
			const maxBunches = Math.floor(Number(state.stock_qty) / bunchSize);
			$bunches.attr('max', maxBunches);
			$bunches.attr('data-max-bunches', maxBunches);
			if ((state.num_bunches || 0) > maxBunches) {
				state.num_bunches = maxBunches;
				$bunches.val(maxBunches);
			}
		} else {
			$bunches.removeAttr('max');
			$bunches.removeAttr('data-max-bunches');
		}

		// Calculate stems from bunches: stems = bunches × bunch_size
		const total_bunches = state.num_bunches || 0;
		const total_stems = total_bunches * bunchSize;
		state.num_stems = total_stems;
		$row.find('.total-stems').val(total_stems);

		const $msg = $row.find('.row-msg');
		const $line_price = $row.find('.row-line-price');
		const stock_qty = (state.stock_qty != null) ? Number(state.stock_qty) : null;

		let msg = '';
		if (total_stems > 0 && stock_qty != null && stock_qty >= 0 && total_stems > stock_qty) {
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
		// Compact mode shows per-length green lines only — no grand totals footer.
		if (this.compact) return;
		let bunches = 0;
		let stems = 0;
		let grand_price = 0;
		this.length_state.forEach((state) => {
			const bs = state.bunch_size || this.bunch_size || 1;
			const nb = state.num_bunches || 0;
			const ns = nb * bs;
			bunches += nb;
			stems += ns;
			if (state.per_stem_rate) grand_price += state.per_stem_rate * ns;
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
			if (result.currency) this._currency = result.currency;
			// Compact rows have no editable DOM — re-render to fill the price line;
			// the detail page updates the row in place.
			if (this.compact) this.render_compact_rows();
			else this.update_row(length);
			this.update_grand_totals();
			this.update_addable_state();
		});
	}

	length_to_cm(length) {
		const match = String(length).match(/(\d+)/);
		return match ? parseInt(match[1]) : null;
	}

	update_addable_state() {
		if (!this.length_state.size) {
			this.$add_to_cart.prop('disabled', true);
			return;
		}
		let ok = false;
		let blocked = false;
		this.length_state.forEach((state) => {
			const bunches = state.num_bunches || 0;
			if (bunches <= 0) return;
			const bunchSize = state.bunch_size || this.bunch_size || 1;
			const stems = bunches * bunchSize;
			const stock_qty = (state.stock_qty != null) ? Number(state.stock_qty) : null;
			const within_stock = (stock_qty == null) || stems <= stock_qty;
			if (within_stock) ok = true;
			else blocked = true;
		});
		this.$add_to_cart.prop('disabled', !ok || blocked);
	}

	persist_cache() {
		const state = {
			lengths: Array.from(this.length_state.keys()),
		};
		if (state.lengths.length === 0) {
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
					num_stems: 0,
					num_bunches: 1,
					user_edited: false,
					bunch_size: this.bunch_size,
					bunch_uom: this.bunch_uom,
				});
				$btn.addClass('active');
				this.fetch_per_stem_rate_for(String(length));
			});
			this.render_length_rows();
			this.update_addable_state();
		} catch (e) {
			// ignore corrupt cache
		}
	}

	add_to_cart() {
		const entries = [];
		this.length_state.forEach((state, length) => {
			const bs = state.bunch_size || this.bunch_size || 1;
			const nb = state.num_bunches || 0;
			const stems = nb * bs;
			if (nb <= 0) return;
			const stock_qty = (state.stock_qty != null) ? Number(state.stock_qty) : null;
			if (stock_qty != null && stems > stock_qty) return;
			entries.push({
				length, num_bunches: nb, stems,
				bunch_size: bs, bunch_uom: state.bunch_uom || this.bunch_uom || null,
			});
		});

		if (!entries.length) {
			frappe.msgprint({
				title: __('Enter quantity'),
				message: __('Enter the number of stems for at least one stem length.'),
				indicator: 'orange',
			});
			return;
		}

		const specs = [];
		$('.item-website-specification table tr').each(function () {
			const label = $(this).find('.spec-label').text().trim();
			const val = $(this).find('.spec-content').text().trim();
			if (label && val) specs.push(`${label}: ${val}`);
		});

		// Guest detection: frappe.session is undefined on web pages, so use the
		// body attribute Frappe sets in base.html.
		const is_guest = document.body.getAttribute('frappe-session-status') === 'logged-out';
		if (is_guest) {
			const payload = entries.map((entry) => ({
				item_code: this.item_code,
				qty: entry.num_bunches,
				uom: entry.bunch_uom || null,
				additional_notes: [
					`Total Bunches: ${entry.stems} (${entry.num_bunches} bunches × ${entry.bunch_size} stems)`,
					specs.length ? `Specs: ${specs.join(', ')}` : '',
				].filter(Boolean).join(' | '),
				custom_length: entry.length,
			}));
			this.$add_to_cart.prop('disabled', true);
			frappe.call({
				method: 'upande_webshop.upande_webshop.shopping_cart.pending_cart.stash',
				args: { entries: payload },
				callback: () => {
					window.location.href = '/login?redirect-to=/cart';
				},
			});
			return;
		}

		this.$add_to_cart.prop('disabled', true);

		const post_one = (entry) => new Promise((resolve) => {
			const additional_notes = [
				`Total Bunches: ${entry.stems} (${entry.num_bunches} bunches × ${entry.bunch_size} stems)`,
				specs.length ? `Specs: ${specs.join(', ')}` : '',
			].filter(Boolean).join(' | ');

			upande_webshop.upande_webshop.shopping_cart.update_cart({
				item_code: this.item_code,
				qty: entry.num_bunches,
				uom: entry.bunch_uom || undefined,
				additional_notes,
				custom_length: entry.length,
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
				// Wishlist: once a wished item is in the cart, drop it from the
				// wishlist and remove the card (same as the variant compact flow).
				if (this.compact) this.remove_from_wishlist_after_add();
			}
		};
		run();
	}

	remove_from_wishlist_after_add() {
		// Mirrors InlineVariantSelector.remove_from_wishlist_after_add — the
		// wishlist module hangs off window.upande_webshop.upande_webshop.wishlist.
		const wishlist = (window.upande_webshop
			&& window.upande_webshop.upande_webshop
			&& window.upande_webshop.upande_webshop.wishlist) || null;
		const $card = this.$root.closest('.wishlist-card');
		frappe.call({
			method: 'upande_webshop.upande_webshop.doctype.wishlist.wishlist.remove_from_wishlist',
			args: { item_code: this.item_code },
			callback: (r) => {
				const new_count = (r && r.message && r.message.wish_count);
				if (wishlist && wishlist.set_wishlist_count) {
					wishlist.set_wishlist_count(false, new_count);
				}
				$card.fadeOut(300, () => {
					$card.remove();
					if (wishlist && parseInt(new_count || 0) === 0 && wishlist.render_empty_state) {
						$('.page_content').empty();
						wishlist.render_empty_state();
					}
				});
			},
		});
	}

	get_cache_key() {
		return `configure:${this.item_code}`;
	}
}

// Expose the selector + a mount helper globally so other pages (e.g. the
// wishlist) can reuse the exact same machinery. Mounting is idempotent: a root
// already initialized is skipped, so calling mount again is safe.
window.upande_webshop = window.upande_webshop || {};
window.upande_webshop.InlineNonVariantSelector = InlineNonVariantSelector;
window.upande_webshop.mount_non_variant_selectors = function (scope) {
	const $scope = scope ? $(scope) : $(document);
	$scope.find('.inline-non-variant-selector').each(function () {
		const $root = $(this);
		if ($root.attr('data-nvsel-mounted')) return;
		const { itemCode, itemName } = $root.data();
		if (!itemCode) return;
		$root.attr('data-nvsel-mounted', '1');
		new InlineNonVariantSelector($root, itemCode, itemName);
	});
};

frappe.ready(() => {
	window.upande_webshop.mount_non_variant_selectors(document);
});
