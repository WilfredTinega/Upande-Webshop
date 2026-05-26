frappe.pages["bulk-publish-items"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Bulk Publish Items"),
		single_column: true,
	});

	new BulkPublishItems(page);
};

class BulkPublishItems {
	constructor(page) {
		this.page = page;
		this.start = 0;
		this.page_length = 50;
		this.total = 0;
		this.selected = new Set();
		this.items = [];
		this.in_progress = false;

		this.make_filters();
		this.make_layout();
		this.bind_progress();
		this.refresh();
	}

	make_filters() {
		this.item_group_field = this.page.add_field({
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
			change: () => this.reset_and_refresh(),
		});

		this.brand_field = this.page.add_field({
			fieldname: "brand",
			label: __("Brand"),
			fieldtype: "Link",
			options: "Brand",
			change: () => this.reset_and_refresh(),
		});

		this.search_field = this.page.add_field({
			fieldname: "search",
			label: __("Search Item Code / Name"),
			fieldtype: "Data",
			change: () => this.reset_and_refresh(),
		});

		this.hide_published_field = this.page.add_field({
			fieldname: "hide_published",
			label: __("Hide already-published"),
			fieldtype: "Check",
			default: 1,
			change: () => this.reset_and_refresh(),
		});

		this.publish_btn = this.page.set_primary_action(
			__("Publish Selected"),
			() => this.publish_selected(),
			"check"
		);
		this.publish_btn.prop("disabled", true);
	}

	make_layout() {
		this.$body = $(`
			<div class="bulk-publish-wrapper">
				<div class="bulk-publish-summary text-muted" style="margin: 10px 0;"></div>
				<div class="bulk-publish-table-wrap">
					<table class="table table-bordered table-hover" style="background: var(--card-bg);">
						<thead>
							<tr>
								<th style="width: 36px;"><input type="checkbox" class="select-all-checkbox" /></th>
								<th>${__("Item Code")}</th>
								<th>${__("Item Name")}</th>
								<th>${__("Item Group")}</th>
								<th>${__("Brand")}</th>
								<th style="width: 140px;">${__("Status")}</th>
							</tr>
						</thead>
						<tbody class="bulk-publish-rows"></tbody>
					</table>
				</div>
				<div class="bulk-publish-pagination" style="display:flex; gap:8px; align-items:center; margin-top: 10px;">
					<button class="btn btn-default btn-sm prev-btn">${__("Previous")}</button>
					<button class="btn btn-default btn-sm next-btn">${__("Next")}</button>
					<span class="page-info text-muted"></span>
				</div>
			</div>
		`).appendTo(this.page.main);

		this.$summary = this.$body.find(".bulk-publish-summary");
		this.$rows = this.$body.find(".bulk-publish-rows");
		this.$selectAll = this.$body.find(".select-all-checkbox");
		this.$prev = this.$body.find(".prev-btn");
		this.$next = this.$body.find(".next-btn");
		this.$pageInfo = this.$body.find(".page-info");

		this.$selectAll.on("change", (e) => this.toggle_all($(e.target).is(":checked")));
		this.$prev.on("click", () => this.go_prev());
		this.$next.on("click", () => this.go_next());

		this.$rows.on("change", ".row-checkbox", (e) => {
			const $cb = $(e.target);
			const code = $cb.data("item-code");
			if ($cb.is(":checked")) this.selected.add(code);
			else this.selected.delete(code);
			this.update_publish_button();
		});
	}

	bind_progress() {
		frappe.realtime.on("webshop_bulk_publish_progress", (data) => {
			this.last_event_at = Date.now();
			if (!this.progress_dialog) return;
			const pct = Math.max(1, Math.min(100, Number(data.progress) || 0));
			this.set_progress(pct, data.message || "");
		});

		frappe.realtime.on("webshop_bulk_publish_done", (data) => {
			this.last_event_at = Date.now();
			this.finish_progress({
				succeeded: data.succeeded,
				skipped: data.skipped,
				failed: data.failed,
				errors: data.errors,
			});
		});
	}

	set_progress(pct, message) {
		if (!this.progress_dialog) return;
		this.$progress_bar
			.css("width", `${pct}%`)
			.attr("aria-valuenow", pct)
			.text(`${pct}%`);
		if (message) this.$progress_msg.text(message);
	}

	finish_progress({ succeeded, skipped, failed, errors }) {
		this.in_progress = false;
		this.stop_polling();
		if (this.progress_dialog) {
			this.set_progress(100, __("Done. Published: {0}, Skipped: {1}, Failed: {2}", [
				succeeded || 0,
				skipped || 0,
				failed || 0,
			]));
			this.progress_dialog.set_primary_action(__("Close"), () => {
				this.progress_dialog.hide();
				this.progress_dialog = null;
				this.selected.clear();
				this.reset_and_refresh();
			});
		}
		if (errors && errors.length) {
			frappe.msgprint({
				title: __("Some items failed"),
				message: errors.map(frappe.utils.escape_html).join("<br>"),
				indicator: "orange",
			});
		}
	}

	start_polling(codes) {
		this.stop_polling();
		this.poll_codes = codes;
		this.poll_total = codes.length;
		this.poll_started_at = Date.now();
		this.last_event_at = Date.now();
		this.poll_timer = setInterval(() => this.poll_status(), 4000);
	}

	stop_polling() {
		if (this.poll_timer) {
			clearInterval(this.poll_timer);
			this.poll_timer = null;
		}
	}

	async poll_status() {
		if (!this.progress_dialog) {
			this.stop_polling();
			return;
		}
		try {
			const r = await frappe.call({
				method:
					"upande_webshop.upande_webshop.page.bulk_publish_items.bulk_publish_items.get_publish_status",
				args: { item_codes: this.poll_codes },
			});
			const total = (r.message && r.message.total) || this.poll_total || 1;
			const published = (r.message && r.message.published) || 0;
			const pct = Math.max(1, Math.min(99, Math.round((published / total) * 100)));
			// Only nudge the bar forward if realtime hasn't updated it past this point.
			const current = parseInt(this.$progress_bar.attr("aria-valuenow"), 10) || 0;
			if (pct > current) {
				this.set_progress(pct, __("Publishing {0} of {1}...", [published, total]));
			}
			const idle_ms = Date.now() - (this.last_event_at || this.poll_started_at);
			if (published >= total && idle_ms > 5000) {
				this.finish_progress({
					succeeded: published,
					skipped: 0,
					failed: Math.max(0, total - published),
					errors: [],
				});
			}
		} catch (e) {
			// transient errors are fine — keep polling
		}
	}

	get_filters() {
		return {
			item_group: this.item_group_field.get_value() || null,
			brand: this.brand_field.get_value() || null,
			search: this.search_field.get_value() || null,
			hide_published: this.hide_published_field.get_value() ? 1 : 0,
		};
	}

	reset_and_refresh() {
		this.start = 0;
		this.selected.clear();
		this.refresh();
	}

	async refresh() {
		const args = Object.assign(
			{ start: this.start, page_length: this.page_length },
			this.get_filters()
		);
		const r = await frappe.call({
			method:
				"upande_webshop.upande_webshop.page.bulk_publish_items.bulk_publish_items.get_items",
			args,
		});
		this.items = (r.message && r.message.items) || [];
		this.total = (r.message && r.message.total) || 0;
		this.render_rows();
		this.render_pagination();
		this.update_publish_button();
	}

	render_rows() {
		this.$rows.empty();
		if (!this.items.length) {
			this.$rows.append(`
				<tr><td colspan="6" class="text-muted text-center" style="padding: 20px;">
					${__("No items match the current filters.")}
				</td></tr>
			`);
			this.$selectAll.prop("checked", false).prop("disabled", true);
			return;
		}
		this.$selectAll.prop("disabled", false);

		for (const item of this.items) {
			const checked = this.selected.has(item.item_code) ? "checked" : "";
			const disabled = item.already_published ? "disabled" : "";
			const status = item.already_published
				? `<span class="indicator-pill green">${__("Published")}</span>`
				: `<span class="indicator-pill gray">${__("Not Published")}</span>`;
			const $tr = $(`
				<tr>
					<td><input type="checkbox" class="row-checkbox" data-item-code="${frappe.utils.escape_html(item.item_code)}" ${checked} ${disabled} /></td>
					<td>${frappe.utils.escape_html(item.item_code)}</td>
					<td>${frappe.utils.escape_html(item.item_name || "")}</td>
					<td>${frappe.utils.escape_html(item.item_group || "")}</td>
					<td>${frappe.utils.escape_html(item.brand || "")}</td>
					<td>${status}</td>
				</tr>
			`);
			this.$rows.append($tr);
		}

		this.$selectAll.prop(
			"checked",
			this.items
				.filter((i) => !i.already_published)
				.every((i) => this.selected.has(i.item_code)) &&
				this.items.some((i) => !i.already_published)
		);
	}

	render_pagination() {
		const from = this.total === 0 ? 0 : this.start + 1;
		const to = Math.min(this.start + this.page_length, this.total);
		this.$pageInfo.text(__("Showing {0}-{1} of {2}", [from, to, this.total]));
		this.$prev.prop("disabled", this.start <= 0);
		this.$next.prop("disabled", to >= this.total);
		this.$summary.text(
			__("{0} item(s) selected", [this.selected.size])
		);
	}

	toggle_all(checked) {
		for (const item of this.items) {
			if (item.already_published) continue;
			if (checked) this.selected.add(item.item_code);
			else this.selected.delete(item.item_code);
		}
		this.$rows.find(".row-checkbox:not(:disabled)").prop("checked", checked);
		this.update_publish_button();
		this.render_pagination();
	}

	update_publish_button() {
		this.publish_btn.prop("disabled", this.selected.size === 0 || this.in_progress);
		this.$summary.text(__("{0} item(s) selected", [this.selected.size]));
	}

	go_prev() {
		if (this.start <= 0) return;
		this.start = Math.max(0, this.start - this.page_length);
		this.refresh();
	}

	go_next() {
		if (this.start + this.page_length >= this.total) return;
		this.start += this.page_length;
		this.refresh();
	}

	publish_selected() {
		if (!this.selected.size) return;
		const codes = Array.from(this.selected);

		frappe.confirm(
			__("Publish {0} item(s) on the webshop?", [codes.length]),
			() => this.run_publish(codes)
		);
	}

	async run_publish(codes) {
		this.in_progress = true;
		this.update_publish_button();

		this.progress_dialog = new frappe.ui.Dialog({
			title: __("Publishing Items"),
			no_cancel: true,
		});
		this.progress_dialog.$body.html(`
			<div class="bulk-publish-progress-msg text-muted" style="margin-bottom: 10px;">
				${__("Starting...")}
			</div>
			<div class="progress" style="height: 20px;">
				<div class="progress-bar bulk-publish-progress-bar"
					role="progressbar" aria-valuenow="1"
					aria-valuemin="0" aria-valuemax="100" style="width: 1%;">1%</div>
			</div>
		`);
		this.$progress_bar = this.progress_dialog.$body.find(".bulk-publish-progress-bar");
		this.$progress_msg = this.progress_dialog.$body.find(".bulk-publish-progress-msg");
		this.progress_dialog.show();

		try {
			await frappe.call({
				method:
					"upande_webshop.upande_webshop.page.bulk_publish_items.bulk_publish_items.publish_items",
				args: { item_codes: codes },
			});
			this.start_polling(codes);
		} catch (e) {
			this.in_progress = false;
			this.stop_polling();
			this.update_publish_button();
			if (this.progress_dialog) {
				this.progress_dialog.hide();
				this.progress_dialog = null;
			}
		}
	}
}
