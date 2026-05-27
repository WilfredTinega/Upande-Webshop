if (!window.webshop) window.webshop = {}
if (!window.upande_webshop) window.upande_webshop = {}
if (!frappe.boot) frappe.boot = {}

// Show the logged-in user's profile photo in the navbar avatar dropdown.
// Frappe's website.js renders the avatar from the `user_image` cookie, which
// only updates at login; webshop_user_image is injected live on every page
// (see shopping_cart/utils.update_website_context) so a freshly-uploaded photo
// appears immediately.
(function applyNavbarUserImage() {
	function setAvatarImage() {
		var imageUrl = window.webshop_user_image;
		if (!imageUrl) return;

		var selectors = [".user-image-wrapper", ".user-image-sidebar", ".user-image-myaccount"];
		selectors.forEach(function (selector) {
			document.querySelectorAll(selector).forEach(function (wrapper) {
				var frame = wrapper.querySelector(".avatar-frame");
				if (frame) {
					// Replace the initial-letter avatar with the actual image.
					frame.classList.remove("standard-image");
					frame.textContent = "";
					frame.style.backgroundImage = 'url("' + imageUrl + '")';
				}
			});
		});
	}

	if (window.frappe && frappe.ready) {
		frappe.ready(function () {
			// website.js renders the avatar on ready; run just after it.
			setTimeout(setAvatarImage, 0);
		});
	} else {
		document.addEventListener("DOMContentLoaded", function () {
			setTimeout(setAvatarImage, 0);
		});
	}
})();
