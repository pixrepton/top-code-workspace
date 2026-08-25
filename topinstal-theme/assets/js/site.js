(function () {
	const header = document.querySelector('[data-site-header]');
	const toggle = document.querySelector('[data-menu-toggle]');
	const nav = document.querySelector('[data-primary-nav]');

	if (!header || !toggle || !nav) {
		return;
	}

	toggle.addEventListener('click', function () {
		const isOpen = header.classList.toggle('is-open');
		toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
	});

	nav.addEventListener('click', function (event) {
		if (event.target instanceof HTMLAnchorElement) {
			header.classList.remove('is-open');
			toggle.setAttribute('aria-expanded', 'false');
		}
	});
}());

