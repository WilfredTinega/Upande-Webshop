$(() => {
	const RESERVE_API = "upande_webshop.upande_webshop.api.reserve_stems_for_customer";
	const ADD_TO_CART_API = "upande_webshop.upande_webshop.api.add_to_cart_for_customer";
	const MATRIX_API = "upande_webshop.upande_webshop.api.get_product_overview_matrix";
	const PORTAL_CUSTOMERS_API = "upande_webshop.upande_webshop.api.get_portal_customers";
	const CART_COUNT_API = "upande_webshop.upande_webshop.api.get_product_overview_cart_count";

	// Cart badge in the toolbar — refreshed on load and after each add-to-cart.
	function refreshCartCount() {
		frappe.call({
			method: CART_COUNT_API,
			callback: (r) => {
				const n = (r && r.message && r.message.count) || 0;
				const $badge = $("#po-cart-count");
				if (n > 0) {
					$badge.text(n).show();
				} else {
					$badge.hide();
				}
			},
		});
	}

	const warehouses = window.po_display_warehouses || [];
	let allItems = [];

	// The card matrix shows ALL day buckets at once (columns = stem length × day
	// 0/1/2/3/4+). The top "Days" buttons don't refetch — they RE-SORT the grid
	// by the picked day's stock (most-available variety first) and HIGHLIGHT the
	// matching day column across every card. "" / "All" = no sort change, no
	// highlight.
	//   currentAge === ""  → server's biggest-total order, no column highlighted
	//   currentAge === 0..4 → cards sorted by that day's stock; column highlighted
	const DAY_BUCKETS = [
		{ key: 0, label: __("Day 0") },
		{ key: 1, label: __("Day 1") },
		{ key: 2, label: __("Day 2") },
		{ key: 3, label: __("Day 3") },
		{ key: 4, label: __("Day 4+") },
	];
	let currentAge = "";

	// data-wh-qty for a length's action buttons must align to the GLOBAL
	// `warehouses` array (the modal indexes into it), not the in-stock subset.
	// Value per warehouse = that length's total sellable stems there (sum of its
	// day buckets), 0 where the length isn't stocked in that warehouse.
	function lengthWhQty(item, stemLength) {
		const byWh = (item.cells && item.cells[stemLength]) || {};
		return warehouses.map((w) => {
			const buckets = byWh[w.name];
			return Array.isArray(buckets)
				? buckets.reduce((a, b) => a + (Number(b) || 0), 0)
				: 0;
		});
	}

	function render(items) {
		const $list = $("#po-list").empty().removeClass("po-mode-list po-mode-grid");
		// Stamp the highlighted day so CSS can tint the matching column.
		$list.attr(
			"data-age",
			currentAge === undefined || currentAge === null ? "" : String(currentAge)
		);
		if (!items.length) {
			$list.append(
				`<div class="text-muted text-center py-4">${__("No items found.")}</div>`
			);
			return;
		}
		items.forEach((item) => renderMatrixCard($list, item));
		applyColumnHighlight();
	}

	// One card per variety: a matrix whose columns are (stem length × day bucket
	// 0/1/2/3/4+) and whose rows are warehouses. Only in-stock lengths and
	// warehouses appear. Each length group carries its own Add to Cart / Reserve.
	function renderMatrixCard($list, item) {
		const esc = frappe.utils.escape_html;
		const lengths = item.lengths || [];
		const whs = item.warehouses || [];
		const cells = item.cells || {};

		const bucketsFor = (L, whName) =>
			(cells[L.stem_length] || {})[whName] || [0, 0, 0, 0, 0];

		// Drop any day bucket that is empty for EVERY length+warehouse — only ages
		// that actually hold stock for this variety get a column. Kept columns stay
		// aligned across all lengths.
		const activeDays = DAY_BUCKETS.filter((d) =>
			lengths.some((L) =>
				whs.some((whName) => Number(bucketsFor(L, whName)[d.key]) > 0)
			)
		);
		// Fallback: if somehow nothing is in stock, keep all buckets so the card
		// still renders a coherent (empty) matrix rather than collapsing.
		const days = activeDays.length ? activeDays : DAY_BUCKETS;

		// --- header: two rows. Length spans the active day columns; days under each.
		// Trailing "Total" column (per-warehouse sum across all lengths/days).
		const lengthHeads =
			lengths
				.map(
					(L) =>
						`<th class="po-mx-len-head text-center" colspan="${days.length}">${esc(
							L.label
						)}</th>`
				)
				.join("") + `<th class="po-mx-total-head" rowspan="2">${__("Total")}</th>`;
		const dayHeads = lengths
			.map((L) =>
				days
					.map(
						(d) =>
							`<th class="po-mx-day-head text-center po-mx-day-${d.key}" data-day="${d.key}">${esc(
								d.label
							)}</th>`
					)
					.join("")
			)
			.join("");

		// --- body: one row per warehouse, day cells per length, + row total.
		const bodyRows = whs
			.map((whName) => {
				const wLabel =
					(warehouses.find((w) => w.name === whName) || {}).label || whName;
				let rowTotal = 0;
				const dayCells = lengths
					.map((L) => {
						const buckets = bucketsFor(L, whName);
						return days
							.map((d) => {
								const q = Number(buckets[d.key]) || 0;
								rowTotal += q;
								return `<td class="text-center po-mx-cell po-mx-day-${d.key}"
									data-day="${d.key}">${q}</td>`;
							})
							.join("");
					})
					.join("");
				return `<tr><th class="po-mx-wh">${esc(wLabel)}</th>${dayCells}
					<td class="po-mx-total text-center">${rowTotal}</td></tr>`;
			})
			.join("");

		// --- grand-total row: one total PER active age column (sum across
		// warehouses for that length + day bucket), then the overall total.
		// Skipped when there's only one warehouse — the single body row already IS
		// the total, so a separate Total row would just repeat it.
		let grandTotal = 0;
		const lengthTotals = lengths
			.map((L) =>
				days
					.map((d) => {
						let t = 0;
						whs.forEach((whName) => {
							t += Number(bucketsFor(L, whName)[d.key]) || 0;
						});
						grandTotal += t;
						return `<td class="po-mx-total text-center po-mx-day-${d.key}"
							data-day="${d.key}">${t}</td>`;
					})
					.join("")
			)
			.join("");
		const totalRow =
			whs.length > 1
				? `<tr class="po-mx-total-row">
			<th class="po-mx-wh">${__("Total")}</th>
			${lengthTotals}
			<td class="po-mx-total po-mx-grand-total text-center">${grandTotal}</td>
		</tr>`
				: "";

		// --- ONE Add to Cart + Reserve per variety (card footer). The buttons carry
		// every in-stock length with its per-warehouse stems, so the modal offers a
		// stem-length picker and recomputes warehouse caps when the length changes.
		const lengthsPayload = lengths.map((L) => ({
			stem_length: L.stem_length,
			label: L.label,
			whQty: lengthWhQty(item, L.stem_length),
		}));
		const actionAttrs = `
			data-item-code="${esc(item.item_code)}"
			data-variety="${esc(item.variety)}"
			data-sales-uom="${esc(item.sales_uom || "")}"
			data-stems-per-bunch="${item.stems_per_bunch || 1}"
			data-lengths="${esc(JSON.stringify(lengthsPayload))}"
		`;

		// Variety name lives in the top-left corner cell (spans both header rows),
		// not as a heading above the table. Display-only: drop a leading "Princess"
		// (these varieties are all "Princess <name>"; the prefix is noise on the
		// card). The full name is still kept for search and the modal/cart.
		const displayName = item.variety.replace(/^Princess\s+/i, "");
		const varietyHtml = item.route
			? `<a href="/${esc(item.route)}" class="po-variety-link">${esc(displayName)}</a>`
			: esc(displayName);

		$list.append(`
			<div class="po-variety card mb-4" data-item-code="${esc(item.item_code)}">
				<div class="card-body">
					<div class="table-responsive">
						<table class="table table-sm mb-0 po-mx-table">
							<thead>
								<tr>
									<th class="po-mx-corner po-mx-variety" rowspan="2">${varietyHtml}</th>
									${lengthHeads}
								</tr>
								<tr>${dayHeads}</tr>
							</thead>
							<tbody>${bodyRows}</tbody>
							<tfoot>${totalRow}</tfoot>
						</table>
					</div>
					<div class="po-mx-actions-bar mt-2">
						<button type="button" class="btn btn-sm btn-primary po-add-to-cart-btn" ${actionAttrs}>
							${__("Add to Cart")}
						</button>
						<button type="button" class="btn btn-sm po-reserve-btn" ${actionAttrs}>
							${__("Reserve")}
						</button>
					</div>
				</div>
			</div>
		`);
	}

	// Tint the day column matching the selected top "Days" button. "" = none.
	function applyColumnHighlight() {
		const $list = $("#po-list");
		$list.find(".po-mx-active-col").removeClass("po-mx-active-col");
		if (currentAge === "" || currentAge === undefined || currentAge === null) {
			return;
		}
		$list
			.find(`[data-day="${String(currentAge)}"]`)
			.addClass("po-mx-active-col");
	}

	// Sum a variety's sellable stems for one day bucket (0..4), across every
	// length + warehouse. age === "" / null means "All" → the variety's full
	// total. Used to order the grid by the selected day's availability.
	function dayBucketStock(item, age) {
		const cells = item.cells || {};
		let total = 0;
		Object.keys(cells).forEach((stemLength) => {
			const byWh = cells[stemLength] || {};
			Object.keys(byWh).forEach((wh) => {
				const buckets = byWh[wh];
				if (!Array.isArray(buckets)) return;
				if (age === "" || age === undefined || age === null) {
					total += buckets.reduce((a, b) => a + (Number(b) || 0), 0);
				} else {
					total += Number(buckets[Number(age)]) || 0;
				}
			});
		});
		return total;
	}

	function filteredItems() {
		// selectedVariety (set by picking from the dropdown) isolates one card.
		// Otherwise the trimmed search term does a name/code contains-filter.
		let items;
		if (selectedVariety) {
			items = allItems.filter((item) => item.variety === selectedVariety);
		} else {
			const term = ($("#po-search-input").val() || "").trim().toLowerCase();
			items = !term
				? allItems.slice()
				: allItems.filter(
						(item) =>
							item.variety.toLowerCase().includes(term) ||
							item.item_code.toLowerCase().includes(term)
				  );
		}
		// Picking a day ("Day's Pick"/1/2/3/4+) drops every variety with no stock at
		// that harvest age, then sorts the rest most-available-first (ties by name)
		// and highlights the matching column (see applyColumnHighlight). "All" keeps
		// every variety in the server's biggest-total order.
		if (currentAge !== "" && currentAge !== undefined && currentAge !== null) {
			items = items
				.filter((item) => dayBucketStock(item, currentAge) > 0)
				.sort(
					(a, b) =>
						dayBucketStock(b, currentAge) - dayBucketStock(a, currentAge) ||
						a.variety.toLowerCase().localeCompare(b.variety.toLowerCase())
				);
		}
		return items;
	}

	function applySearch() {
		render(filteredItems());
	}

	function load() {
		frappe.call({
			method: MATRIX_API,
			freeze: true,
			freeze_message: __("Loading stock…"),
			callback: (r) => {
				allItems = (r && r.message) || [];
				// Sync currentAge to the button pre-marked active in the HTML (Day 4+),
				// so the default render highlights the matching column.
				const $active = $("#po-global-age .po-age-btn.active");
				if ($active.length) currentAge = $active.data("age");
				applySearch();
			},
		});
	}

	// ---- Search-as-dropdown ----------------------------------------------
	// The search box is a combobox: focusing it lists every variety (stock-
	// sorted), typing filters the list, and picking one isolates that card.
	// Clearing the box restores the full grid.
	let selectedVariety = "";
	const $searchCombo = $("#po-search-combo");
	const $searchInput = $("#po-search-input");
	const $searchMenu = $("#po-search-menu");
	const $searchClear = $("#po-search-clear");
	let searchActiveIdx = -1;
	let searchOptions = [];

	// Show the × only when there's something to clear.
	function toggleSearchClear() {
		$searchClear.prop("hidden", !($searchInput.val() || "").length);
	}

	function searchMatches() {
		const term = ($searchInput.val() || "").trim().toLowerCase();
		const names = allItems.map((i) => i.variety);
		if (!term) return names;
		return names.filter((n) => n.toLowerCase().includes(term));
	}

	function renderSearchMenu() {
		const esc = frappe.utils.escape_html;
		searchOptions = searchMatches();
		if (!searchOptions.length) {
			$searchMenu.html(`<div class="po-combo-empty">${__("No matches")}</div>`);
		} else {
			$searchMenu.html(
				searchOptions
					.map(
						(n, i) =>
							`<div class="po-combo-option${i === searchActiveIdx ? " active" : ""}" data-idx="${i}">${esc(n)}</div>`
					)
					.join("")
			);
		}
		$searchMenu.addClass("show");
	}

	function hideSearchMenu() {
		$searchMenu.removeClass("show");
		searchActiveIdx = -1;
	}

	function chooseVariety(name) {
		selectedVariety = name;
		$searchInput.val(name);
		toggleSearchClear();
		hideSearchMenu();
		applySearch();
	}

	// Reset search in one click: clear text, selection and menu, restore grid.
	function clearSearch() {
		$searchInput.val("");
		selectedVariety = "";
		toggleSearchClear();
		hideSearchMenu();
		applySearch();
		$searchInput.trigger("focus");
	}
	$searchClear.on("click", clearSearch);

	$searchInput.on("focus click", () => {
		searchActiveIdx = -1;
		renderSearchMenu();
	});
	$searchInput.on("input", () => toggleSearchClear());
	$searchInput.on(
		"input",
		frappe.utils.debounce(() => {
			// Free typing clears any locked-in selection and live-filters.
			selectedVariety = "";
			searchActiveIdx = -1;
			renderSearchMenu();
			applySearch();
		}, 150)
	);
	$searchInput.on("keydown", function (e) {
		if (!$searchMenu.hasClass("show")) return;
		if (e.key === "ArrowDown") {
			e.preventDefault();
			searchActiveIdx = Math.min(searchActiveIdx + 1, searchOptions.length - 1);
			renderSearchMenu();
		} else if (e.key === "ArrowUp") {
			e.preventDefault();
			searchActiveIdx = Math.max(searchActiveIdx - 1, 0);
			renderSearchMenu();
		} else if (e.key === "Enter") {
			if (searchActiveIdx >= 0 && searchOptions[searchActiveIdx]) {
				e.preventDefault();
				chooseVariety(searchOptions[searchActiveIdx]);
			}
		} else if (e.key === "Escape") {
			hideSearchMenu();
		}
	});
	$searchMenu.on("mousedown", ".po-combo-option", function (e) {
		e.preventDefault();
		chooseVariety(searchOptions[$(this).data("idx")]);
	});
	$(document).on("mousedown", (e) => {
		if (!$searchCombo[0].contains(e.target)) hideSearchMenu();
	});

	// Global "Days" filter — every card already shows all day columns, so this
	// just highlights the matching column across the grid (no refetch).
	$("#po-global-age").on("click", ".po-age-btn", function () {
		const $btn = $(this);
		const age = $btn.data("age");
		$("#po-global-age .po-age-btn").removeClass("active");
		$btn.addClass("active");
		currentAge = age;

		let title;
		let titleClass = "";
		if (age === "" || age === undefined) {
			title = __("All Age Stock");
		} else if (String(age) === "0") {
			title = __("Day's Pick");
			titleClass = "po-age-title-0";
		} else if (String(age) === "4") {
			title = __("Day 4+ Stock");
			titleClass = "po-age-title-4";
		} else {
			title = __("Day {0} Stock", [age]);
			titleClass = "po-age-title-" + age;
		}
		$("#po-age-title")
			.removeClass(
				"po-age-title-0 po-age-title-1 po-age-title-2 po-age-title-3 po-age-title-4"
			)
			.addClass(titleClass)
			.text(title);

		$("#po-list").attr(
			"data-age",
			age === undefined || age === null ? "" : String(age)
		);
		// Re-render so cards re-sort by the selected day's stock (filteredItems
		// reads currentAge); applySearch ends in applyColumnHighlight to tint the
		// matching column.
		applySearch();
	});

	$(document).on("click", ".po-add-to-cart-btn", function (e) {
		e.preventDefault();
		e.stopPropagation();
		try {
			openActionDialog("cart", readBtn($(this)));
		} catch (err) {
			console.error("Add to Cart dialog failed", err);
			frappe.msgprint(__("Could not open dialog: {0}", [err.message || err]));
		}
	});
	$(document).on("click", ".po-reserve-btn", function (e) {
		e.preventDefault();
		e.stopPropagation();
		try {
			openActionDialog("reserve", readBtn($(this)));
		} catch (err) {
			console.error("Reserve dialog failed", err);
			frappe.msgprint(__("Could not open dialog: {0}", [err.message || err]));
		}
	});

	function readBtn($btn) {
		// One button per variety carries every in-stock length with its
		// per-warehouse sellable stems (aligned to the global `warehouses` order).
		// Parsed defensively; falls back to an empty list.
		let lengths = [];
		try {
			lengths = JSON.parse($btn.attr("data-lengths") || "[]");
		} catch (e) {
			lengths = [];
		}
		return {
			itemCode: $btn.data("item-code"),
			variety: $btn.data("variety"),
			salesUom: $btn.data("sales-uom") || "",
			stemsPerBunch: parseFloat($btn.data("stems-per-bunch")) || 1,
			lengths: Array.isArray(lengths) ? lengths : [],
		};
	}

	// ---- Custom in-modal combobox -------------------------------------------
	// Native <datalist> renders a browser popup that escapes the modal bounds.
	// This builds a typeahead whose menu is positioned inside the modal.
	//   $field  — the wrapping .po-combo element (input + menu)
	//   fetch   — (term) => Promise<string[]>  resolves to option labels
	//   onPick  — (value) => void  called when an option is chosen
	function setupCombo($field, fetch, onPick) {
		const $input = $field.find("input");
		const $menu = $field.find(".po-combo-menu");
		const esc = frappe.utils.escape_html;
		let activeIdx = -1;
		let options = [];

		function renderMenu() {
			if (!options.length) {
				$menu.html(`<div class="po-combo-empty">${__("No matches")}</div>`);
			} else {
				$menu.html(
					options
						.map(
							(o, i) =>
								`<div class="po-combo-option${i === activeIdx ? " active" : ""}" data-idx="${i}">${esc(o)}</div>`
						)
						.join("")
				);
			}
			$menu.addClass("show");
		}

		function hideMenu() {
			$menu.removeClass("show");
			activeIdx = -1;
		}

		function choose(value) {
			$input.val(value);
			hideMenu();
			if (onPick) onPick(value);
		}

		const refresh = frappe.utils.debounce(() => {
			Promise.resolve(fetch(($input.val() || "").trim())).then((opts) => {
				options = opts || [];
				activeIdx = -1;
				renderMenu();
			});
		}, 250);

		$input.on("input focus", refresh);
		$input.on("keydown", function (e) {
			if (!$menu.hasClass("show")) return;
			if (e.key === "ArrowDown") {
				e.preventDefault();
				activeIdx = Math.min(activeIdx + 1, options.length - 1);
				renderMenu();
			} else if (e.key === "ArrowUp") {
				e.preventDefault();
				activeIdx = Math.max(activeIdx - 1, 0);
				renderMenu();
			} else if (e.key === "Enter") {
				if (activeIdx >= 0 && options[activeIdx]) {
					e.preventDefault();
					choose(options[activeIdx]);
				}
			} else if (e.key === "Escape") {
				hideMenu();
			}
		});
		$menu.on("mousedown", ".po-combo-option", function (e) {
			e.preventDefault();
			choose(options[$(this).data("idx")]);
		});
		$input.on("blur", () => setTimeout(hideMenu, 150));

		return { refresh };
	}

	function openActionDialog(
		mode,
		{ itemCode, variety, salesUom, stemsPerBunch, lengths }
	) {
		const isReserve = mode === "reserve";
		const dialogId = "po-dlg-" + Math.random().toString(36).slice(2, 9);
		const esc = frappe.utils.escape_html;
		const submitLabel = isReserve ? __("Reserve") : __("Add to Cart");
		const title = isReserve ? __("Reserve") : __("Add to Cart");
		const perBunch = stemsPerBunch || 1;
		const qtyLabel = salesUom || __("Bunches");

		const lengthList = Array.isArray(lengths) ? lengths : [];
		if (!lengthList.length) {
			frappe.msgprint(__("This variety has no stock to order."));
			return;
		}
		// Per (length, warehouse) cap, in whole bunches: floor(stems / perBunch).
		// The client-side cap; the backend enforces the same limit (source of truth).
		function capFor(li, wi) {
			const L = lengthList[li];
			const stems = Number((L && L.whQty && L.whQty[wi]) || 0);
			return Math.floor(stems / perBunch);
		}
		const lengthInStock = (L) =>
			(Array.isArray(L.whQty) ? L.whQty : []).some((q) => (Number(q) || 0) > 0);

		// Multiple lengths can be selected at once (like the product detail page).
		// selectedSet holds the chosen length indices; start with the first in-stock
		// length selected so the modal opens ready to use.
		const selectedSet = new Set();
		const firstStockIdx = lengthList.findIndex(lengthInStock);
		if (firstStockIdx >= 0) selectedSet.add(firstStockIdx);

		// Stem-length control: multi-select toggle pills. A length with no stock in
		// any warehouse is struck out and disabled.
		const lengthControl = `<div class="po-length-toggle">
			${lengthList
				.map((L, i) => {
					const oos = !lengthInStock(L);
					const active = selectedSet.has(i);
					return `<button type="button"
						class="btn btn-sm po-length-btn${active ? " active" : ""}${oos ? " oos" : ""}"
						data-idx="${i}"${oos ? ' disabled aria-disabled="true"' : ""}
						title="${oos ? __("Out of stock") : esc(L.label)}">${esc(L.label)}</button>`;
				})
				.join("")}
		</div>`;

		// Plain-HTML modal — does NOT use frappe.ui.Dialog, because portal pages
		// don't load frappe.ui.form.make_control (required even for HTML fields).
		// One warehouse block per selected length; each lists only that length's
		// in-stock warehouses. Cells are keyed by data-li (length) + data-idx (wh).
		function whListHtml() {
			const blocks = [];
			Array.from(selectedSet)
				.sort((a, b) => a - b)
				.forEach((li) => {
					const L = lengthList[li];
					const rows = warehouses
						.map((w, wi) => {
							const cap = capFor(li, wi);
							if (cap <= 0) return "";
							// Available column shows stems; cap is in whole bunches
							// (the qty input's unit), so stems = cap × perBunch.
							const availStems = cap * perBunch;
							return `
						<div class="po-wh-row" data-warehouse="${esc(w.name)}">
							<label class="po-wh-check">
								<input type="checkbox" class="po-f-wh-sel" data-li="${li}" data-idx="${wi}">
								<span class="po-wh-name">${esc(w.label || w.name)}</span>
							</label>
							<span class="po-wh-avail small" title="${__("Available stems")}"
								data-li="${li}" data-idx="${wi}" data-avail-stems="${availStems}">${availStems}</span>
							<input type="number" min="0" step="1" max="${cap}" disabled
								class="form-control form-control-sm po-f-wh-qty" data-li="${li}" data-idx="${wi}"
								placeholder="0">
							<span class="text-muted small po-wh-hint" data-li="${li}" data-idx="${wi}"></span>
						</div>`;
						})
						.join("");
					if (rows) {
						blocks.push(
							`<div class="po-wh-block" data-li="${li}">
								<div class="po-wh-block-title">${esc(L.label)}</div>
								<div class="po-wh-row po-wh-head">
									<span class="po-wh-check po-wh-name">${__("Warehouse")}</span>
									<span class="po-wh-avail small">${__("Avail.")}</span>
									<span class="po-f-wh-qty-head">${__("Qty")}</span>
									<span class="po-wh-hint"></span>
								</div>
								${rows}
							</div>`
						);
					}
				});
			return (
				blocks.join("") ||
				`<div class="po-wh-empty text-muted small">${__(
					"Select a stem length with stock."
				)}</div>`
			);
		}

		const $modal = $(`
			<div class="po-modal-backdrop" id="${dialogId}" role="dialog" aria-modal="true">
				<div class="po-modal">
					<div class="po-modal-header">
						<h5 class="po-modal-title">${esc(title)}</h5>
						<button type="button" class="po-modal-close" aria-label="${__("Close")}">&times;</button>
					</div>
					<form class="po-modal-body po-action-form">
						<div class="mb-3">
							<strong>${esc(variety)}</strong>
							<span class="text-muted">— ${esc(itemCode)}</span>
						</div>
						<div class="form-group po-combo po-combo-customer">
							<label class="control-label">${__("Customer")} <span class="text-danger">*</span></label>
							<input type="text" class="form-control form-control-sm po-f-customer"
								autocomplete="off" required>
							<div class="po-combo-menu"></div>
						</div>
						<div class="form-group">
							<label class="control-label">${__("Stem Length")} <span class="text-danger">*</span>
								<span class="text-muted">— ${__("select one or more")}</span>
							</label>
							${lengthControl}
						</div>
						<div class="form-group">
							<label class="control-label">${__("Warehouses")} <span class="text-danger">*</span>
								<span class="text-muted">(${esc(qtyLabel)})</span>
							</label>
							<div class="po-wh-list">${whListHtml()}</div>
							<div class="text-muted small mt-1 po-qty-total"></div>
						</div>
					</form>
					<div class="po-modal-footer">
						<button type="button" class="btn btn-sm btn-default po-modal-cancel">${__("Cancel")}</button>
						<button type="button" class="btn btn-sm btn-primary po-modal-submit">${esc(submitLabel)}</button>
					</div>
				</div>
			</div>
		`);

		const close = () => {
			$modal.remove();
			$(document).off(`keydown.${dialogId}`);
		};

		$modal.on("click", ".po-modal-close, .po-modal-cancel", close);
		$modal.on("click", function (e) {
			if (e.target === this) close();
		});
		$(document).on(`keydown.${dialogId}`, function (e) {
			if (e.key === "Escape") close();
		});
		$modal.find("form").on("submit", function (e) {
			e.preventDefault();
			$modal.find(".po-modal-submit").trigger("click");
		});

		$modal.on("click", ".po-modal-submit", function () {
			const customer = ($modal.find(".po-f-customer").val() || "").trim();

			if (!customer) {
				frappe.msgprint(__("Customer is required."));
				return;
			}

			// Collect every checked (length, warehouse) cell with a positive qty,
			// re-clamped to its in-stock cap as a final guard (covers paste/
			// programmatic entry that skipped the input handler). The backend
			// enforces the same limit and surfaces any residual over-stock per line.
			const lines = [];
			let cappedAny = false;
			$modal.find(".po-f-wh-sel:checked").each(function () {
				const li = $(this).data("li");
				const wi = $(this).data("idx");
				const wh = warehouses[wi];
				const L = lengthList[li];
				const $q = $modal.find(
					`.po-f-wh-qty[data-li="${li}"][data-idx="${wi}"]`
				);
				const raw = parseFloat($q.val()) || 0;
				const qty = clampQty(li, wi);
				if (qty < raw) cappedAny = true;
				if (wh && L && qty > 0) {
					lines.push({
						stem_length: L.stem_length,
						lengthLabel: L.label,
						warehouse: wh.name,
						qty,
					});
				}
			});

			if (!lines.length) {
				frappe.msgprint(__("Select at least one warehouse and enter a quantity greater than zero."));
				return;
			}
			if (cappedAny) {
				// A line was trimmed to the available stock — show the corrected qty
				// and let the user confirm rather than silently submitting less.
				updateTotals();
				frappe.msgprint(
					__("Quantity reduced to the available stock. Review and submit again.")
				);
				return;
			}

			const method = isReserve ? RESERVE_API : ADD_TO_CART_API;
			const $submit = $modal.find(".po-modal-submit").prop("disabled", true);
			frappe.dom.freeze(isReserve ? __("Reserving…") : __("Adding…"));

			// One API call per (length, warehouse) line (sequential, so the shared
			// draft Sales Order cart isn't created twice in a race). Report once.
			const sosCreated = [];
			const carts = new Set();
			const errors = [];

			function runLine(i) {
				if (i >= lines.length) return finish();
				const { stem_length, lengthLabel, warehouse, qty } = lines[i];
				const whLabel =
					(warehouses.find((w) => w.name === warehouse) || {}).label || warehouse;
				const lineLabel = `${lengthLabel} · ${whLabel}`;
				frappe.call({
					method,
					args: {
						item_code: itemCode,
						stem_length,
						warehouse,
						qty,
						customer,
					},
					// Don't pop Frappe's default red error dialog; we collect the
					// server message (e.g. "Not enough stock") and report once.
					freeze: false,
					callback: (r) => {
						const msg = r && r.message;
						// Reserve submits a Sales Order; Add to Cart appends to one
						// draft Sales Order cart (returns it under `cart`).
						if (isReserve && msg && msg.sales_order) sosCreated.push(msg.sales_order);
						if (!isReserve && msg && msg.cart) carts.add(msg.cart);
						runLine(i + 1);
					},
					error: (r) => {
						// Pull the server's thrown message (the _ServerMessages JSON).
						let detail = "";
						try {
							const m = JSON.parse((r && r._server_messages) || "[]");
							if (m.length) detail = JSON.parse(m[0]).message || "";
						} catch (e) {
							detail = "";
						}
						errors.push(detail ? `${lineLabel}: ${detail}` : lineLabel);
						runLine(i + 1);
					},
				});
			}

			function finish() {
				frappe.dom.unfreeze();
				$submit.prop("disabled", false);
				if (isReserve && sosCreated.length) {
					frappe.show_alert(
						{
							message: __("Sales Order(s) created: {0}", [sosCreated.join(", ")]),
							indicator: "green",
						},
						8
					);
				} else if (!isReserve && carts.size) {
					frappe.show_alert(
						{
							message:
								__("Added to cart.") +
								` <a href="/cart" style="text-decoration:underline">${__("View cart")}</a>`,
							indicator: "green",
						},
						10
					);
					refreshCartCount();
				}
				if (errors.length) {
					frappe.msgprint({
						title: __("Some lines could not be added"),
						message: errors.join("<br>"),
						indicator: "orange",
					});
				}
				// Keep the dialog open when nothing succeeded so the user can fix
				// the qty; close it once at least one line went through.
				if (sosCreated.length || carts.size) {
					close();
				}
				load();
			}

			runLine(0);
		});

		$("body").append($modal);
		setTimeout(() => $modal.find(".po-f-customer").trigger("focus"), 50);

		// ---- Per (length, warehouse) rows: checkbox toggles its qty input; qty is
		// capped at that cell's in-stock bunches; per-row hints show the cap and the
		// stem equivalent (qty is in bunches). Cells keyed by data-li + data-idx. ----
		const cellSel = (li, wi) => `[data-li="${li}"][data-idx="${wi}"]`;
		function rowQty(li, wi) {
			const $sel = $modal.find(`.po-f-wh-sel${cellSel(li, wi)}`);
			const $q = $modal.find(`.po-f-wh-qty${cellSel(li, wi)}`);
			return $sel.is(":checked") ? parseFloat($q.val()) || 0 : 0;
		}
		// Clamp a cell's qty to its in-stock cap (and to >= 0); write it back.
		function clampQty(li, wi) {
			const $q = $modal.find(`.po-f-wh-qty${cellSel(li, wi)}`);
			const cap = capFor(li, wi);
			let v = parseFloat($q.val());
			if (isNaN(v)) return 0;
			if (v < 0) v = 0;
			if (v > cap) v = cap;
			if (String(v) !== $q.val()) $q.val(v);
			return v;
		}
		function updateTotals() {
			let total = 0;
			$modal.find(".po-f-wh-qty").each(function () {
				const li = $(this).data("li");
				const wi = $(this).data("idx");
				const bunches = rowQty(li, wi);
				total += bunches;
				// Available column counts DOWN as qty is entered: remaining stems =
				// full cap (stems) − entered stems. Capped at 0, floored to a whole
				// number. data-avail-stems holds the cell's full available stems.
				const $avail = $modal.find(`.po-wh-avail${cellSel(li, wi)}`);
				const fullStems = parseFloat($avail.attr("data-avail-stems")) || 0;
				const remaining = Math.max(0, fullStems - bunches * perBunch);
				$avail.text(remaining);
				// The trailing hint shows the stem equivalent of the entered qty
				// (blank until a qty is entered).
				const $hint = $modal.find(`.po-wh-hint${cellSel(li, wi)}`);
				if (bunches > 0 && perBunch > 1) {
					$hint.text(__("= {0} stems", [bunches * perBunch]));
				} else {
					$hint.text("");
				}
			});
			const $tot = $modal.find(".po-qty-total");
			$tot.text(
				total > 0
					? perBunch > 1
						? __("Total: {0} stems", [total * perBunch])
						: __("Total: {0}", [total])
					: ""
			);
		}
		$modal.on("change", ".po-f-wh-sel", function () {
			const li = $(this).data("li");
			const wi = $(this).data("idx");
			const $q = $modal.find(`.po-f-wh-qty${cellSel(li, wi)}`);
			const on = $(this).is(":checked");
			$q.prop("disabled", !on);
			if (on) {
				if (!parseFloat($q.val())) $q.val(1);
				clampQty(li, wi);
				$q.trigger("focus");
			}
			updateTotals();
		});
		$modal.on("input", ".po-f-wh-qty", function () {
			clampQty($(this).data("li"), $(this).data("idx"));
			updateTotals();
		});
		// Length pills are multi-select: clicking toggles that length in/out of the
		// selection and rebuilds the warehouse blocks. Out-of-stock pills are
		// disabled and ignored. At least one length must stay selected.
		$modal.on("click", ".po-length-btn:not(:disabled)", function () {
			const i = parseInt($(this).data("idx"), 10);
			if (selectedSet.has(i)) {
				if (selectedSet.size <= 1) return; // keep at least one
				selectedSet.delete(i);
				$(this).removeClass("active");
			} else {
				selectedSet.add(i);
				$(this).addClass("active");
			}
			$modal.find(".po-wh-list").html(whListHtml());
			updateTotals();
		});
		updateTotals();

		// Customer list is scoped server-side to the logged-in user's portal
		// customers (Customer.portal_users); internal staff still see all.
		setupCombo($modal.find(".po-combo-customer"), (term) =>
			new Promise((resolve) => {
				frappe.call({
					method: PORTAL_CUSTOMERS_API,
					args: { term: term || "" },
					callback: (r) => resolve((r && r.message) || []),
				});
			})
		);
	}

	load();
});
