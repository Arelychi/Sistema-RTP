document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-admin-toolbar]').forEach(function (toolbar) {
    const group = toolbar.closest('.admin-module-group');
    const search = toolbar.querySelector('[data-admin-search]');
    const sharedFilter = toolbar.querySelector('[data-admin-shared-filter]');
    const statusFilter = toolbar.querySelector('[data-admin-status-filter]');
    const typeFilter = toolbar.querySelector('[data-admin-type-filter]');
    const ignoreModuleFilter = toolbar.hasAttribute('data-admin-ignore-module-filter');
    const clearButton = toolbar.querySelector('[data-admin-search-clear]');
    const pagination = group?.querySelector('[data-admin-pagination]');
    const pageSummary = pagination?.querySelector('[data-admin-pagination-summary]');
    const pageStatus = pagination?.querySelector('[data-admin-page-status]');
    const previousPageButton = pagination?.querySelector('[data-admin-page-prev]');
    const nextPageButton = pagination?.querySelector('[data-admin-page-next]');
    const routeFilterPanel = toolbar.querySelector('[data-route-filter-panel]');
    const routeFilterToggle = toolbar.querySelector('[data-route-filter-toggle]');
    const routeFilterCount = toolbar.querySelector('[data-route-filter-count]');
    const routeFilterOptions = routeFilterPanel?.querySelectorAll('[data-route-filter-option]') || [];
    const routeFilterClear = routeFilterPanel?.querySelector('[data-route-filter-clear]');
    const visibleCount = toolbar.dataset.adminVisibleCountTarget
      ? document.getElementById(toolbar.dataset.adminVisibleCountTarget)
      : group?.querySelector('[data-admin-visible-count]');
    const rows = group ? group.querySelectorAll('[data-admin-filter-row]') : [];
    const queryModule = new URLSearchParams(window.location.search).get('module_number');
    let activeModule = queryModule || localStorage.getItem('adminSelectedModule') || '';
    const userModulePanel = toolbar.closest('[data-user-module-count]');
    const userView = toolbar.closest('.admin-user-view');
    let activeUserModule = queryModule
      || localStorage.getItem('adminSelectedModule')
      || document.querySelector('[data-user-module-count]')?.dataset.adminModulePanel
      || '';
    const pageSize = 10;
    let currentPage = 1;

    function updatePagination(resetPage) {
      if (!pagination) return;
      if (resetPage) currentPage = 1;
      const matchingRows = Array.from(rows).filter((row) => row.dataset.adminFilterMatch !== 'false');
      const pageCount = Math.max(1, Math.ceil(matchingRows.length / pageSize));
      currentPage = Math.min(currentPage, pageCount);
      const startIndex = (currentPage - 1) * pageSize;
      const visibleRows = new Set(matchingRows.slice(startIndex, startIndex + pageSize));

      rows.forEach((row) => {
        row.hidden = !visibleRows.has(row);
      });
      if (pageSummary) {
        const firstVisible = matchingRows.length ? startIndex + 1 : 0;
        const lastVisible = Math.min(startIndex + pageSize, matchingRows.length);
        pageSummary.textContent = `Mostrando ${firstVisible}-${lastVisible} de ${matchingRows.length}`;
      }
      if (pageStatus) pageStatus.textContent = `Página ${currentPage} de ${pageCount}`;
      if (previousPageButton) previousPageButton.disabled = currentPage <= 1;
      if (nextPageButton) nextPageButton.disabled = currentPage >= pageCount;
    }

    function filterRows() {
      const query = search?.value.trim().toLowerCase() || '';
      const shared = sharedFilter?.value || 'Todos';
      const status = statusFilter?.value || 'Todos';
      const type = typeFilter?.value || 'Todos';
      const selectedRouteFilters = { status: [], category: [], service: [], type: [], turnoType: [], userType: [] };
      routeFilterOptions.forEach(function (option) {
        if (option.checked) selectedRouteFilters[option.dataset.routeFilterOption].push(option.value);
      });

      if (clearButton) clearButton.hidden = !query;
      let matchingRowCount = 0;
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
        const matchesRouteFilters = !routeFilterPanel
          || (
            (!selectedRouteFilters.status.length || selectedRouteFilters.status.includes(row.dataset.filterStatus))
            && (!selectedRouteFilters.category.length || selectedRouteFilters.category.includes(row.dataset.filterShared))
            && (!selectedRouteFilters.service.length || selectedRouteFilters.service.includes(row.dataset.filterService))
            && (!selectedRouteFilters.type.length || selectedRouteFilters.type.includes(row.dataset.filterRouteType))
            && (!selectedRouteFilters.turnoType.length || selectedRouteFilters.turnoType.includes(row.dataset.filterTurnoType))
            && (!selectedRouteFilters.userType.length || selectedRouteFilters.userType.includes(row.dataset.filterType))
          );
        const matchesFilters = matchesQuery && matchesShared && matchesStatus && matchesType && matchesModule && matchesRouteFilters;
        row.dataset.adminFilterMatch = String(matchesFilters);
        if (!pagination) row.hidden = !matchesFilters;
        if (matchesFilters) matchingRowCount += 1;
      });
      updatePagination(true);
      if (routeFilterCount) {
        const selectedCount = Object.values(selectedRouteFilters).reduce((total, values) => total + values.length, 0);
        routeFilterCount.textContent = String(selectedCount);
        routeFilterCount.hidden = selectedCount === 0;
        routeFilterToggle?.classList.toggle('is-active', selectedCount > 0);
      }
      const visibleCountIsCurrent = (!userView || userView.classList.contains('active'))
        && (!userModulePanel || userModulePanel.dataset.adminModulePanel === activeUserModule);
      if (visibleCount && visibleCountIsCurrent) {
        visibleCount.textContent = String(matchingRowCount);
      }
      if (toolbar.hasAttribute('data-admin-route-filters')) {
        toolbar.dispatchEvent(new CustomEvent('admin-filters-updated', { bubbles: true }));
      }
    }

    search?.addEventListener('input', filterRows);
    sharedFilter?.addEventListener('change', filterRows);
    statusFilter?.addEventListener('change', filterRows);
    typeFilter?.addEventListener('change', filterRows);
    routeFilterOptions.forEach(function (option) {
      option.addEventListener('change', filterRows);
    });
    previousPageButton?.addEventListener('click', function () {
      if (currentPage <= 1) return;
      currentPage -= 1;
      updatePagination(false);
    });
    nextPageButton?.addEventListener('click', function () {
      currentPage += 1;
      updatePagination(false);
    });
    routeFilterToggle?.addEventListener('click', function () {
      const isExpanded = routeFilterToggle.getAttribute('aria-expanded') === 'true';
      routeFilterToggle.setAttribute('aria-expanded', String(!isExpanded));
      if (routeFilterPanel) routeFilterPanel.hidden = isExpanded;
    });
    routeFilterClear?.addEventListener('click', function () {
      routeFilterOptions.forEach(function (option) {
        option.checked = false;
      });
      filterRows();
    });
    if (routeFilterPanel && routeFilterToggle) {
      document.addEventListener('click', function (event) {
        if (!toolbar.contains(event.target)) {
          routeFilterPanel.hidden = true;
          routeFilterToggle.setAttribute('aria-expanded', 'false');
        }
      });
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !routeFilterPanel.hidden) {
          routeFilterPanel.hidden = true;
          routeFilterToggle.setAttribute('aria-expanded', 'false');
          routeFilterToggle.focus();
        }
      });
    }
    document.addEventListener('admin-module-changed', function (event) {
      activeModule = String(event.detail?.moduleId || '');
      if (userModulePanel) activeUserModule = activeModule;
      filterRows();
    });
    document.addEventListener('admin-user-view-changed', filterRows);
    clearButton?.addEventListener('click', function () {
      if (!search) return;
      search.value = '';
      filterRows('');
      search.focus();
    });
    filterRows();
  });
});
