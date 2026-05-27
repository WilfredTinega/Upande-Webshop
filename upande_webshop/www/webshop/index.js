$(() => {
	class ProductListing {
		constructor() {
			let me = this;
			let is_item_group_page = $(".item-group-content").data("item-group");
			this.item_group = is_item_group_page || null;

			let view_type = localStorage.getItem("product_view") || "List View";

			// Render Product Views, Filters & Search
			new webshop.ProductView({
				view_type: view_type,
				products_section: $('#product-listing'),
				item_group: me.item_group
			});

			this.bind_card_actions();
		}

		bind_card_actions() {
			upande_webshop.upande_webshop.shopping_cart.bind_add_to_cart_action();
			upande_webshop.upande_webshop.wishlist.bind_wishlist_action();

			// Inner interactive elements live inside the card-wrapping <a>. Stop the
			// click from triggering link navigation, but let the event keep bubbling
			// so the delegated wishlist / cart handlers (bound on .page_content) still
			// fire.
			$('#product-listing').on('click', '.go-to-cart, .go-to-cart-grid, .like-action, .like-action-list, .btn-add-to-cart-list', (e) => {
				e.preventDefault();
			});
		}
	}

	new ProductListing();
});
