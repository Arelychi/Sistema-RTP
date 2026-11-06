document.addEventListener('DOMContentLoaded', function () {
  const loader = document.querySelector('[data-admin-save-loader]');
  const loaderLabel = loader?.querySelector('[data-admin-save-loader-label]');
  const storageKey = 'adminPendingSaveFeedback';
  const forms = document.querySelectorAll('[data-admin-save-form]');

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
      if (loader) {
        if (loaderLabel) loaderLabel.textContent = form.dataset.adminSaveLabel || 'Guardando cambios...';
        loader.hidden = false;
      }
    });
  });

  const successAlert = document.querySelector('.admin-alert-success');
  let pendingSave;
  try {
    pendingSave = sessionStorage.getItem(storageKey);
    if (pendingSave) sessionStorage.removeItem(storageKey);
  } catch (error) {
    console.error('No se pudo recuperar el resultado del guardado anterior.', error);
    return;
  }
  if (!pendingSave) return;

  if (!successAlert) return;

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

  row.classList.remove('admin-save-row-highlight');
  void row.offsetWidth;
  row.classList.add('admin-save-row-highlight');
  row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  window.setTimeout(() => row.classList.remove('admin-save-row-highlight'), 3200);
});
