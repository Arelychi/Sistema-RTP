(() => {
  const body = document.body;
  const sidebar = document.querySelector('.sidebar, .admin-sidebar');
  const toggle = document.querySelector('#sidebar-toggle');
  if (!sidebar || !toggle) return;

  const storageKey = sidebar.classList.contains('admin-sidebar')
    ? 'admin-sidebar-collapsed'
    : 'module-sidebar-collapsed';
  const savedState = localStorage.getItem(storageKey)
    ?? (!sidebar.classList.contains('admin-sidebar') ? localStorage.getItem('rol-sidebar-collapsed') : null);

  const setCollapsed = (collapsed) => {
    body.classList.toggle('sidebar-collapsed', collapsed);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.setAttribute('aria-label', `${collapsed ? 'Abrir' : 'Cerrar'} menú lateral`);
    toggle.title = `${collapsed ? 'Abrir' : 'Cerrar'} menú lateral`;
    const icon = toggle.querySelector('[data-sidebar-icon]');
    if (icon) icon.textContent = collapsed ? '￫' : '￩';
    localStorage.setItem(storageKey, String(collapsed));
  };

  setCollapsed(savedState === 'true');
  toggle.addEventListener('click', () => setCollapsed(!body.classList.contains('sidebar-collapsed')));
})();
