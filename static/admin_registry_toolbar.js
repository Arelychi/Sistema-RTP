document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-admin-toolbar]').forEach(function (toolbar) {
    const group = toolbar.closest('.admin-module-group');
    const search = toolbar.querySelector('[data-admin-search]');
    const sharedFilter = toolbar.querySelector('[data-admin-shared-filter]');
    const statusFilter = toolbar.querySelector('[data-admin-status-filter]');
    const typeFilter = toolbar.querySelector('[data-admin-type-filter]');
    const ignoreModuleFilter = toolbar.hasAttribute('data-admin-ignore-module-filter');
    const clearButton = toolbar.querySelector('[data-admin-search-clear]');
    const visibleCount = toolbar.dataset.adminVisibleCountTarget
      ? document.getElementById(toolbar.dataset.adminVisibleCountTarget)
      : group?.querySelector('[data-admin-visible-count]');
    const rows = group ? group.querySelectorAll('[data-admin-filter-row]') : [];
    const queryModule = new URLSearchParams(window.location.search).get('module_number');
    let activeModule = queryModule || localStorage.getItem('adminSelectedModule') || '';

    function filterRows() {
      const query = search?.value.trim().toLowerCase() || '';
      const shared = sharedFilter?.value || 'Todos';
      const status = statusFilter?.value || 'Todos';
      const type = typeFilter?.value || 'Todos';

      if (clearButton) clearButton.hidden = !query;
      rows.forEach(function (row) {
        const matchesQuery = row.textContent.toLowerCase().includes(query);
        const matchesShared = shared === 'Todos' || row.dataset.filterShared === shared;
        let moduleStatuses = {};
        try {
          moduleStatuses = JSON.parse(row.dataset.filterModuleStatuses || '{}');
        } catch (error) {
          moduleStatuses = {};
        }
        const moduleStatus = activeModule ? moduleStatuses[activeModule] : undefined;
        const matchesStatus = status === 'Todos'
          || (moduleStatus !== undefined
            ? (moduleStatus === (status === 'Activo'))
            : row.dataset.filterStatus === status);
        const matchesType = type === 'Todos' || row.dataset.filterType === type;
        const assignedModules = row.dataset.filterModules
          ? row.dataset.filterModules.split(',').filter(Boolean)
          : [];
        const matchesModule = ignoreModuleFilter
          || !activeModule
          || assignedModules.length === 0
          || assignedModules.includes(activeModule);
        row.hidden = !matchesQuery || !matchesShared || !matchesStatus || !matchesType || !matchesModule;
      });
      if (visibleCount) {
        visibleCount.textContent = String(Array.from(rows).filter((row) => !row.hidden).length);
      }
    }

    search?.addEventListener('input', filterRows);
    sharedFilter?.addEventListener('change', filterRows);
    statusFilter?.addEventListener('change', filterRows);
    typeFilter?.addEventListener('change', filterRows);
    document.addEventListener('admin-module-changed', function (event) {
      activeModule = String(event.detail?.moduleId || '');
      filterRows();
    });
    clearButton?.addEventListener('click', function () {
      if (!search) return;
      search.value = '';
      filterRows('');
      search.focus();
    });
    filterRows();
  });
});
