document.addEventListener('DOMContentLoaded', function () {
  const loader = document.querySelector('[data-admin-save-loader]');
  const loaderLabel = loader?.querySelector('[data-admin-save-loader-label]');
  const storageKey = 'adminPendingSaveFeedback';
  const routeLinkStorageKey = 'adminPendingRouteLinkFeedback';
  const forms = document.querySelectorAll('[data-admin-save-form]');

  function showLoader(label) {
    if (!loader) return;
    if (loaderLabel) loaderLabel.textContent = label;
    loader.hidden = false;
  }

  document.addEventListener('admin-operation-start', function (event) {
    showLoader(event.detail?.label || 'Procesando cambios...');
  });

  forms.forEach(function (form) {
    form.addEventListener('submit', function () {
      const fields = (form.dataset.adminSaveFields || form.dataset.adminSaveField || '')
        .split(',')
        .map((field) => field.trim())
        .filter(Boolean);
      const formData = new FormData(form);
      const values = fields.map((field) => String(formData.get(field) || '').trim());
      const scopeField = form.dataset.adminSaveScopeField;
      const scope = scopeField ? String(formData.get(scopeField) || '').trim() : '';

      if (fields.length && values.every(Boolean)) {
        try {
          sessionStorage.setItem(storageKey, JSON.stringify({
            fields,
            values,
            scope,
            path: window.location.pathname,
            selector: form.dataset.adminSaveSelector || '[data-admin-save-row]',
            createdAt: Date.now()
          }));
        } catch (error) {
          console.error('No se pudo guardar el contexto del registro enviado.', error);
        }
      }
      showLoader(form.dataset.adminSaveLabel || 'Guardando cambios...');
    });
  });

  let pendingSave;
  let pendingRouteLink;
  try {
    pendingSave = sessionStorage.getItem(storageKey);
    if (pendingSave) sessionStorage.removeItem(storageKey);
    pendingRouteLink = sessionStorage.getItem(routeLinkStorageKey);
    if (pendingRouteLink) sessionStorage.removeItem(routeLinkStorageKey);
  } catch (error) {
    console.error('No se pudo recuperar el resultado del guardado anterior.', error);
    return;
  }

  window.requestAnimationFrame(function () {
    const successAlert = document.querySelector('.admin-alert-success');
    if (!successAlert) return;

    function highlightRow(row) {
      row.classList.remove('admin-save-row-highlight');
      void row.offsetWidth;
      row.classList.add('admin-save-row-highlight');
      window.setTimeout(() => row.classList.remove('admin-save-row-highlight'), 3200);
    }

    function scrollRowIntoView(row, moduleId) {
      const modulePanel = row.closest('[data-admin-module-panel]');
      if (modulePanel?.hidden || (moduleId && modulePanel?.dataset.adminModulePanel !== moduleId)) {
        const moduleTab = Array.from(document.querySelectorAll('[data-admin-module]'))
          .find((tab) => tab.dataset.adminModule === moduleId);
        moduleTab?.click();
      }

      const paginationScope = modulePanel || row.closest('.admin-module-group');
      const nextPageButton = paginationScope?.querySelector('[data-route-page-next], [data-admin-page-next]');
      const paginatedRows = paginationScope?.querySelectorAll('tbody tr[data-admin-filter-row]') || [];
      let attempts = 0;
      while (row.hidden && nextPageButton && !nextPageButton.disabled && attempts < paginatedRows.length) {
        nextPageButton.click();
        attempts += 1;
      }

      if (row.hidden) return;
      row.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
    }

    if (pendingRouteLink) {
      let linkedRoutes;
      try {
        linkedRoutes = JSON.parse(pendingRouteLink);
      } catch (error) {
        console.error('No se pudo leer el vínculo de rutas pendiente.', error);
      }
      if (
        linkedRoutes
        && Array.isArray(linkedRoutes.routeIds)
        && linkedRoutes.routeIds.length
        && linkedRoutes.moduleId
        && linkedRoutes.path === window.location.pathname
        && Date.now() - linkedRoutes.createdAt <= 60000
      ) {
        const targetPanel = Array.from(document.querySelectorAll('[data-admin-module-panel]'))
          .find((panel) => panel.dataset.adminModulePanel === linkedRoutes.moduleId);
        const linkedIdSet = new Set(linkedRoutes.routeIds.map(String));
        const linkedRows = Array.from(targetPanel?.querySelectorAll('tr[data-route-id][data-route-original="false"]') || [])
          .filter((row) => linkedIdSet.has(row.dataset.routeId));
        linkedRows.forEach(highlightRow);
        if (linkedRows.length) scrollRowIntoView(linkedRows[0], linkedRoutes.moduleId);
      }
    }

    if (!pendingSave) return;

    let savedRecord;
    try {
      savedRecord = JSON.parse(pendingSave);
    } catch (error) {
      console.error('No se pudo leer el resultado del guardado pendiente.', error);
      return;
    }
    if (
      !Array.isArray(savedRecord.fields)
      || !Array.isArray(savedRecord.values)
      || savedRecord.fields.length !== savedRecord.values.length
      || savedRecord.values.some((value) => !value)
      || savedRecord.path !== window.location.pathname
      || Date.now() - savedRecord.createdAt > 60000
    ) return;

    let rows;
    try {
      rows = document.querySelectorAll(savedRecord.selector);
    } catch (error) {
      console.error('El selector de la fila guardada no es válido.', error);
      return;
    }
    const normalize = (value) => String(value || '').trim().toLocaleLowerCase();
    const toDatasetKey = (field) => field.replace(/[_-]([a-z])/g, (_, letter) => letter.toUpperCase());
    const row = Array.from(rows).find(function (candidate) {
      if (savedRecord.scope) {
        const panelModule = candidate.closest('[data-admin-module-panel]')?.dataset.adminModulePanel;
        if (panelModule && panelModule !== savedRecord.scope) return false;
      }

      return savedRecord.fields.every(function (field, index) {
        const datasetField = toDatasetKey(field);
        const dataField = `adminSave${datasetField.charAt(0).toUpperCase()}${datasetField.slice(1)}`;
        const rowValue = candidate.dataset[dataField] ?? (
          savedRecord.fields.length === 1 ? candidate.dataset.adminSaveRow : undefined
        );
        return normalize(rowValue) === normalize(savedRecord.values[index]);
      });
    });
    if (!row) return;

    highlightRow(row);
    scrollRowIntoView(row, savedRecord.scope);
  });
});
