document.addEventListener('DOMContentLoaded', function () {
  const panels = document.querySelectorAll('[data-admin-form-panel]');
  if (!panels.length) return;

  function setPanelCollapsed(panel, collapsed) {
    const toggle = panel.querySelector('[data-admin-form-toggle]');
    panel.classList.toggle('is-collapsed', collapsed);
    if (!toggle) return;
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.setAttribute('aria-label', collapsed ? 'Mostrar formulario' : 'Ocultar formulario');
    toggle.title = collapsed ? 'Mostrar formulario' : 'Ocultar formulario';
    const icon = toggle.querySelector('.admin-form-toggle-icon');
    if (icon) icon.textContent = collapsed ? '🠋' : '🠉';
    const text = toggle.querySelector('.schedule-grid-toggle-text');
    if (text) text.textContent = collapsed ? 'Mostrar fomulario' : 'Ocultar formulario';
  }

  function openPanel(panel, scrollToPanel) {
    setPanelCollapsed(panel, false);
    if (scrollToPanel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  panels.forEach(function (panel) {
    const toggle = panel.querySelector('[data-admin-form-toggle]');
    toggle?.addEventListener('click', function () {
      setPanelCollapsed(panel, !panel.classList.contains('is-collapsed'));
    });

    panel.querySelectorAll('[data-admin-edit-trigger]').forEach(function (trigger) {
      trigger.addEventListener('click', function () {
        openPanel(panel, true);
      });
    });

    setPanelCollapsed(panel, false);
  });

  if (new URLSearchParams(window.location.search).has('edit_id') || new URLSearchParams(window.location.search).has('edit_user_id')) {
    panels.forEach(function (panel) {
      openPanel(panel, true);
    });
  }
});
