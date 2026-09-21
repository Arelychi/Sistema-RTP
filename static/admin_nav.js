document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-admin-nav-toggle]').forEach(function (toggle) {
    toggle.addEventListener('click', function () {
      const panel = document.getElementById(`admin-nav-${this.dataset.adminNavToggle}`);
      if (!panel) return;

      const expanded = this.getAttribute('aria-expanded') === 'true';
      this.setAttribute('aria-expanded', String(!expanded));
      panel.classList.toggle('is-collapsed', expanded);
    });
  });
});
