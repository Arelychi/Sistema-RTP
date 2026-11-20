const body = document.body;
let activeModuleNumber = String(body.dataset.module || '');
let moduleLoadVersion = 0;
let initializedModuleNumber = '';
let specialStatesLoaded = false;
let specialStatesLoadPromise = null;
const state = { year: Number(body.dataset.year), month: Number(body.dataset.month), monthActivated: false, calendarEditingEnabled: true, savingRecord: false, mode: 'work', work: new Set(), rest: new Set(), vacation: new Set(), special: {}, specialStates: [], assignments: {}, dailyDetails: {}, editedDays: new Set(), lastEditedDay: null, editedTimer: null, selectedRecord: null, editingDays: new Set(), editingSnapshots: new Map(), monthRecords: [], controllerCatalog: [], pendingCodeTransfers: [], codeConflictDecisions: new Map() };
const todayPeriod = Number(body.dataset.todayYear) * 12 + Number(body.dataset.todayMonth);
const months = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
const weekdays = ['L','M','M','J','V','S','D'];
const $ = (selector) => document.querySelector(selector);
const form = $('#schedule-form');
const controllerSearch = $('#controller-search');
const controllerSearchMenu = $('#controller-search-menu');
const controllerName = $('#controller-name');
const controllerCredential = $('#controller-credential');
const routeSelect = $('#route-select');
const routeNomenclature = $('#route-nomenclature');
const shiftSelect = $('#shift-select');
const dayEditActions = $('#day-edit-actions');
const editingDayLabel = $('#editing-day-label');
const formMessage = $('#form-message');
const saveAssignmentButton = document.querySelector('.schedule-assignment-actions .primary-button, .record-form-actions .primary-button');
const cancelEditButton = $('#cancel-edit-button');
const saveAllRecordsButton = $('#save-all-records');
const scheduleRecordFilter = $('#schedule-record-filter');
const scheduleStatusFilter = $('#schedule-status-filter');
const scheduleRecordCount = $('#record-count');
const monthlyRoleCount = $('#monthly-role-count');
const clearScheduleFilter = $('#clear-schedule-filter');
const scheduleGrid = $('#schedule-grid');
const scheduleGridToggle = $('#toggle-schedule-grid');
const scheduleTableCard = document.querySelector('.schedule-table-card');
const scheduleAssignmentModal = $('#schedule-assignment-modal');
const openScheduleAssignmentButton = $('#open-schedule-assignment');
const scheduleAssignmentCancelButton = $('#schedule-assignment-cancel');
const scheduleFeedback = $('#schedule-feedback');
const clearDaysButton = $('#clear-days');
let clearDaysSnapshot = null;
let scheduleFeedbackTimeout = null;
const loadingOverlay = $('#loadingOverlay');
const loadingText = $('#loadingText');
const scheduleFormDisabledState = new Map();
const routeOptions = [];
let shiftOptions = [];
const calendarTabs = document.querySelectorAll('.calendar-tab');
const calendarPanels = document.querySelectorAll('.calendar-panel');
const codeConflictDialog = $('#code-conflict-dialog');
const codeConflictCode = codeConflictDialog?.querySelector('[data-conflict-code]');
const codeConflictController = codeConflictDialog?.querySelector('[data-conflict-controller]');
const codeConflictCredential = codeConflictDialog?.querySelector('[data-conflict-credential]');
const codeConflictDay = codeConflictDialog?.querySelector('[data-conflict-day]');
const codeConflictExistingController = codeConflictDialog?.querySelector('[data-conflict-existing-controller]');
const codeConflictExistingCredential = codeConflictDialog?.querySelector('[data-conflict-existing-credential]');
const codeConflictIncomingInitials = codeConflictDialog?.querySelector('[data-conflict-incoming-initials]');
const codeConflictExistingInitials = codeConflictDialog?.querySelector('[data-conflict-existing-initials]');
const codeConflictTransferDescription = codeConflictDialog?.querySelector('[data-conflict-transfer-description]');
const codeConflictDuplicateDescription = codeConflictDialog?.querySelector('[data-conflict-duplicate-description]');
const codeConflictImpactText = codeConflictDialog?.querySelector('[data-conflict-impact-text]');
let resolveCodeConflict = null;
let controllerMenuOpen = false;
function showScheduleMessage(message, isError = false) {
  if (!scheduleFeedback) return;
  scheduleFeedback.textContent = message;
  scheduleFeedback.classList.toggle('is-error', isError);
  scheduleFeedback.classList.add('is-visible');
  if (scheduleFeedbackTimeout) window.clearTimeout(scheduleFeedbackTimeout);
  scheduleFeedbackTimeout = window.setTimeout(() => {
    scheduleFeedback.classList.remove('is-visible', 'is-error');
  }, 3200);
}
function setFormMessage(message, isError = false) {
  if (formMessage) {
    formMessage.textContent = message;
    formMessage.classList.toggle('error', isError);
  } else if (isError) {
    showScheduleMessage(message, true);
  }
}
function clearFormMessageError() {
  formMessage?.classList.remove('error');
}
function updateClearDaysButton(canUndo) {
  if (!clearDaysButton) return;
  const label = canUndo ? 'Deshacer' : 'Limpiar';
  clearDaysButton.textContent = label;
  clearDaysButton.setAttribute('aria-label', label);
}
function resetClearDaysUndo() {
  clearDaysSnapshot = null;
  updateClearDaysButton(false);
}
function cloneDayEditSnapshot(snapshot) {
  return {
    ...snapshot,
    detail: snapshot.detail ? { ...snapshot.detail } : snapshot.detail,
    special: [...(snapshot.special || [])]
  };
}
function captureClearDaysSnapshot() {
  return {
    work: new Set(state.work),
    rest: new Set(state.rest),
    vacation: new Set(state.vacation),
    assignments: { ...state.assignments },
    dailyDetails: Object.fromEntries(Object.entries(state.dailyDetails).map(([day, detail]) => [day, detail ? { ...detail } : detail])),
    special: Object.fromEntries(Object.entries(state.special).map(([code, days]) => [code, new Set(days)])),
    editingDays: new Set(state.editingDays),
    editingSnapshots: new Map([...state.editingSnapshots].map(([day, snapshot]) => [day, cloneDayEditSnapshot(snapshot)])),
    dayEditActionsVisible: dayEditActions ? !dayEditActions.hidden : false,
    editingDayLabel: editingDayLabel?.textContent || '',
    recordFieldsEnabled: !controllerSearch.disabled,
    routeFieldsEnabled: !routeSelect.disabled,
    saveDisabled: saveAssignmentButton.disabled,
    cancelEditVisible: Boolean(cancelEditButton && !cancelEditButton.hidden)
  };
}
function restoreClearDaysSnapshot(snapshot) {
  state.work = new Set(snapshot.work);
  state.rest = new Set(snapshot.rest);
  state.vacation = new Set(snapshot.vacation);
  state.assignments = { ...snapshot.assignments };
  state.dailyDetails = Object.fromEntries(Object.entries(snapshot.dailyDetails).map(([day, detail]) => [day, detail ? { ...detail } : detail]));
  Object.entries(state.special).forEach(([code, days]) => {
    days.clear();
    snapshot.special[code]?.forEach((day) => days.add(day));
  });
  state.editingDays = new Set(snapshot.editingDays);
  state.editingSnapshots = new Map([...snapshot.editingSnapshots].map(([day, item]) => [day, cloneDayEditSnapshot(item)]));
  if (dayEditActions) dayEditActions.hidden = !snapshot.dayEditActionsVisible;
  if (editingDayLabel) editingDayLabel.textContent = snapshot.editingDayLabel;
  setRecordFieldsEnabled(snapshot.recordFieldsEnabled);
  setRouteFieldsEnabled(snapshot.routeFieldsEnabled);
  setEditModeActionsVisible(snapshot.cancelEditVisible);
  updateSaveAssignmentButton();
  updateScheduleAssignmentCancelButton();
  saveAssignmentButton.disabled = snapshot.saveDisabled;
  renderCalendar();
  updateCalendarLock();
}
function showLoader(text = 'Procesando...') {
  if (!loadingOverlay) return;
  loadingText.textContent = text;
  loadingOverlay.classList.add('show');
  loadingOverlay.setAttribute('aria-busy', 'true');
}
function hideLoader() {
  if (!loadingOverlay) return;
  loadingOverlay.classList.remove('show');
  loadingOverlay.setAttribute('aria-busy', 'false');
}
function setControllerMenuOpen(open) {
  controllerMenuOpen = open;
  if (controllerSearchMenu) controllerSearchMenu.hidden = !open;
  controllerSearch?.setAttribute('aria-expanded', String(open));
}
function calendarHasController() {
  return Boolean(state.selectedRecord?.credential || controllerCredential.value.trim());
}
function updateCalendarLock() {
  const locked = !calendarHasController() || monthIsClosed() || !state.calendarEditingEnabled || state.savingRecord;
  document.querySelectorAll('#calendar-modes button, #clear-days').forEach((element) => { element.disabled = locked; });
  document.querySelectorAll('#calendar .day:not(.blank)').forEach((element) => { element.disabled = locked; });
  document.querySelector('#calendar-modes')?.classList.toggle('is-locked', locked);
  document.querySelector('#calendar')?.classList.toggle('is-locked', locked);
}
function workAssignmentReady() {
  const routeSelected = Boolean(routeSelect.value.trim());
  const shiftSelected = Boolean(shiftSelect.value.trim());
  if (routeSelected && shiftSelected) return true;
  setFormMessage(!routeSelected && !shiftSelected
    ? 'Selecciona una ruta y un turno antes de asignar un día.'
    : !routeSelected
      ? 'Selecciona una ruta antes de asignar un día.'
      : 'Selecciona un turno antes de asignar un día.', true);
  if (!routeSelected) routeSelect.focus();
  else shiftSelect.focus();
  return false;
}
function askCodeConflict({ code, controller, credential, day, conflictController, conflictCredential }) {
  const incomingName = controller || credential || 'Controlador sin nombre';
  const existingName = conflictController || conflictCredential || 'otro controlador';
  codeConflictCode.textContent = code;
  codeConflictController.textContent = incomingName;
  codeConflictCredential.textContent = credential ? `ID ${credential}` : '';
  codeConflictDay.textContent = String(day);
  codeConflictExistingController.textContent = existingName;
  codeConflictExistingCredential.textContent = conflictCredential
    ? `ID ${conflictCredential}`
    : '';
  codeConflictIncomingInitials.textContent = String(incomingName).trim().slice(0, 2).toLocaleUpperCase('es');
  codeConflictExistingInitials.textContent = String(existingName).trim().slice(0, 2).toLocaleUpperCase('es');
  updateCodeConflictImpact();
  codeConflictDialog.hidden = false;
  document.body.classList.add('dialog-open');
  return new Promise((resolve) => { resolveCodeConflict = resolve; });
}
function updateCodeConflictImpact() {
  const code = codeConflictCode.textContent || '—';
  const day = codeConflictDay.textContent || '—';
  const incomingName = codeConflictController.textContent || 'Controlador sin nombre';
  const existingName = codeConflictExistingController.textContent || 'otro controlador';
  const decision = codeConflictDialog.querySelector('input[name="code-conflict-resolution"]:checked')?.value || 'transfer';
  codeConflictTransferDescription.textContent = `${incomingName} toma ${code} y ${existingName} pasa a descanso (D).`;
  codeConflictDuplicateDescription.textContent = `Ambos conservan ${code} en el Día ${day} con marca de advertencia.`;
  codeConflictImpactText.textContent = decision === 'duplicate'
    ? `Al mantener el duplicado, ambos controladores conservarán el código ${code} el Día ${day} con una marca de advertencia.`
    : `Al reasignar titularidad, ${incomingName} asumirá el código ${code} el Día ${day} y ${existingName} pasará automáticamente a descanso (D).`;
}
function closeCodeConflict(decision) {
  codeConflictDialog.hidden = true;
  document.body.classList.remove('dialog-open');
  if (resolveCodeConflict) resolveCodeConflict(decision);
  resolveCodeConflict = null;
}
function codeForDay(record, day) {
  return record?.daily_details?.[String(day)]?.code || record?.daily_assignments?.[String(day)] || '';
}
function hasDuplicateRouteCode(code, day, credential) {
  const normalizedCode = String(code || '').trim().toUpperCase();
  return /^[A-Z]+\d+$/.test(normalizedCode)
    && state.monthRecords.some((record) => record.credential !== credential && codeForDay(record, day) === normalizedCode);
}
function findCodeConflict(code, day, credential) {
  return state.monthRecords.find((record) => record.credential !== String(credential || '').trim() && codeForDay(record, day) === code);
}
function codeConflictDecisionKey(code, day, credential, conflictCredential) {
  return `${String(credential || '').trim()}|${String(conflictCredential || '').trim()}|${day}|${String(code || '').trim().toUpperCase()}`;
}
function rememberCodeConflictDecision(code, day, credential, conflict, decision) {
  const targetCredential = String(credential || '').trim();
  const key = codeConflictDecisionKey(code, day, targetCredential, conflict.credential);
  state.codeConflictDecisions.set(key, decision);
  state.pendingCodeTransfers = state.pendingCodeTransfers.filter((item) => item.key !== key);
  if (decision === 'transfer') {
    state.pendingCodeTransfers.push({
      key,
      source_credential: conflict.credential,
      target_credential: targetCredential,
      day: Number(day),
      code: String(code).trim().toUpperCase(),
    });
  }
}
function clearPendingCodeConflicts() {
  state.pendingCodeTransfers = [];
  state.codeConflictDecisions.clear();
}
async function confirmCodeConflict(code, day, credential) {
  const conflict = findCodeConflict(code, day, credential);
  if (!conflict) return 'none';
  const key = codeConflictDecisionKey(code, day, credential, conflict.credential);
  if (state.codeConflictDecisions.has(key)) return state.codeConflictDecisions.get(key);
  const currentRecord = state.monthRecords.find((record) => record.credential === credential);
  const decision = await askCodeConflict({
    code,
    controller: controllerName.value.trim() || currentRecord?.name,
    credential,
    day,
    conflictController: conflict.name,
    conflictCredential: conflict.credential,
  });
  if (decision) rememberCodeConflictDecision(code, day, credential, conflict, decision);
  return decision;
}
codeConflictDialog?.querySelector('[data-conflict-accept]')?.addEventListener('click', () => {
  const decision = codeConflictDialog.querySelector('input[name="code-conflict-resolution"]:checked')?.value || 'transfer';
  closeCodeConflict(decision);
});
codeConflictDialog?.querySelectorAll('input[name="code-conflict-resolution"]').forEach((input) => {
  input.addEventListener('change', updateCodeConflictImpact);
});
codeConflictDialog?.querySelectorAll('[data-conflict-cancel]').forEach((element) => element.addEventListener('click', () => closeCodeConflict(null)));
function monthIsClosed() { return state.year * 12 + state.month < todayPeriod && !state.monthActivated; }
function updateMonthEditability() {
  const closed = monthIsClosed();
  document.querySelectorAll('#schedule-form input, #schedule-form select, #schedule-form button, #calendar-modes button, #clear-days, #save-all-records, #create-record, #open-schedule-assignment').forEach((element) => { element.disabled = closed; });
  updateCalendarLock();
  const activateButton = $('#activate-month');
  if (activateButton) { activateButton.hidden = !((state.year * 12 + state.month) < todayPeriod); activateButton.textContent = state.monthActivated ? 'Desactivar Mes' : 'Activar Mes'; activateButton.disabled = false; }
  document.querySelectorAll('.month-closed-notice').forEach((element) => {
    const expired = state.year * 12 + state.month < todayPeriod;
    element.hidden = !expired;
    element.textContent = state.monthActivated
      ? 'Mes activado por el administrador. La edición está habilitada.'
      : 'Mes desactivado por el administrador. El rol mensual está en solo lectura.';
    element.classList.toggle('is-active', state.monthActivated);
  });
}
function setScheduleGridCollapsed(collapsed) {
  scheduleGrid.classList.toggle('is-collapsed', collapsed);
  if (!scheduleGridToggle) return;
  scheduleGridToggle.setAttribute('aria-expanded', String(!collapsed));
  const action = collapsed ? 'Mostrar' : 'Ocultar';
  scheduleGridToggle.setAttribute('aria-label', `${action} formulario`);
  scheduleGridToggle.title = `${action} formulario`;
  scheduleGridToggle.querySelector('.schedule-grid-toggle-icon').textContent = collapsed ? '🠋' : '🠉';
  scheduleGridToggle.querySelector('.schedule-grid-toggle-text').textContent = `${action} formulario`;
}

scheduleGridToggle?.addEventListener('click', () => setScheduleGridCollapsed(!scheduleGrid.classList.contains('is-collapsed')));

function openScheduleAssignment(resetForm = true) {
  if (!scheduleAssignmentModal) return;
  if (scheduleAssignmentModal.parentElement !== document.body) {
    document.body.appendChild(scheduleAssignmentModal);
  }
  scheduleAssignmentModal.hidden = false;
  document.body.classList.add('schedule-assignment-modal-open');
  if (resetForm) createNewRecord();
  setScheduleGridCollapsed(false);
  requestAnimationFrame(() => {
    $('.schedule-assignment-dialog').focus();
    controllerSearch.focus();
  });
}

function closeScheduleAssignment() {
  if (!scheduleAssignmentModal || scheduleAssignmentModal.hidden) return;
  scheduleAssignmentModal.hidden = true;
  document.body.classList.remove('schedule-assignment-modal-open');
  openScheduleAssignmentButton?.focus();
}

openScheduleAssignmentButton?.addEventListener('click', () => openScheduleAssignment());
scheduleAssignmentCancelButton?.addEventListener('click', () => {
  if (state.editingDays.size) {
    cancelDayEdit();
    return;
  }
  closeScheduleAssignment();
});
scheduleAssignmentModal?.querySelectorAll('[data-schedule-modal-close]').forEach((element) => {
  element.addEventListener('click', closeScheduleAssignment);
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && scheduleAssignmentModal && !scheduleAssignmentModal.hidden) {
    closeScheduleAssignment();
  }
});

function setCalendarTab(tabName) {
  calendarTabs.forEach((button) => {
    const isActive = button.dataset.tab === tabName;
    button.classList.toggle('is-active', isActive);
    button.setAttribute('aria-selected', String(isActive));
  });
  calendarPanels.forEach((panel) => {
    const isActive = panel.id === `${tabName}-panel`;
    panel.classList.toggle('is-active', isActive);
  });
}
function renderTurnosList() {
  const list = $('#available-turnos-list');
  if (!list) return;
  const count = shiftOptions.length;
  $('#turnos-count').textContent = `${count} ${count === 1 ? 'turno' : 'turnos'}`;
  list.innerHTML = shiftOptions.length ? shiftOptions.map((turno) => `
    <button class="route-item" type="button" data-turno="${escapeHtml(turno.numero)}">
      <span class="route-code">${escapeHtml(turno.numero)}</span>
      <span class="route-text">
        <strong>Turno ${escapeHtml(turno.numero)}</strong>
        <small>${escapeHtml(turno.hora_inicio)} - ${escapeHtml(turno.hora_fin)}</small>
      </span>
      <span class="route-select-indicator">Usar</span>
    </button>
  `).join('') : '<div class="empty-state">No hay turnos disponibles.</div>';

  list.querySelectorAll('.route-item').forEach((button) => {
    button.addEventListener('click', () => {
      const turno = Number(button.dataset.turno);
      if (!Number.isFinite(turno)) return;
      shiftSelect.value = String(turno);
      $('#code-preview').textContent = `${routeNomenclature.value.trim().toUpperCase() || '—'}${shiftSelect.value || ''}`;
      setCalendarTab('calendar');
    });
  });
}
function renderRouteList() {
  const list = $('#available-routes-list');
  if (!list) return;
  const count = routeOptions.length;
  $('#routes-count').textContent = `${count} ${count === 1 ? 'ruta' : 'rutas'}`;
  list.innerHTML = routeOptions.length ? routeOptions.map((route) => `
    <button class="route-item" type="button" data-route="${escapeHtml(route.ruta)}">
      <span class="route-code">${escapeHtml(route.nomenclatura || 'R')}</span>
      <span class="route-text">
        <strong>${escapeHtml(route.ruta)}</strong>
        <small>${escapeHtml(route.origen)} / ${escapeHtml(route.destino)}</small>
      </span>
      <span class="route-select-indicator">Usar</span>
    </button>
  `).join('') : '<div class="empty-state">No hay rutas disponibles.</div>';

  list.querySelectorAll('.route-item').forEach((button) => {
    button.addEventListener('click', () => {
      const routeName = button.dataset.route;
      const route = routeOptions.find((item) => item.ruta === routeName);
      if (!route) return;
      routeSelect.value = route.ruta;
      routeNomenclature.value = route.nomenclatura || '';
      routeSelect.dispatchEvent(new Event('change'));
      setCalendarTab('calendar');
    });
  });
}
function setLoadingButton(button, isLoading, label) {
  if (!button) return;
  button.disabled = isLoading;
  button.classList.toggle('is-loading', isLoading);
  const nextLabel = isLoading ? `<span class="btn-spinner" aria-hidden="true"></span>${label}` : label;
  button.innerHTML = nextLabel;
}
function normalizeScheduleSearch(value) {
  return String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
}
const scheduleStatusClasses = {
  Trabajo: 'table-work',
  Descanso: 'table-rest',
  Vacaciones: 'table-vacation',
  Falta: 'table-absence',
  Incapacidad: 'table-incapacity',
  Especial: 'table-special'
};
function filterScheduleTable() {
  const query = normalizeScheduleSearch(scheduleRecordFilter?.value);
  const selectedStatus = scheduleStatusFilter?.value || 'Todos';
  const firstDayColumn = body.classList.contains('admin-embedded-role') ? 2 : 3;
  const rows = [...document.querySelectorAll('#schedule-table tbody tr[data-credential]')];
  let visibleCount = 0;
  rows.forEach((row) => {
    const name = row.querySelector('.person-button')?.textContent || '';
    const credential = row.dataset.credential || '';
    const matchesQuery = !query || normalizeScheduleSearch(`${name} ${credential}`).includes(query);
    const dayCells = [...row.querySelectorAll(`td:nth-child(n + ${firstDayColumn})`)];
    const hasAssignment = dayCells.some((cell) => cell.textContent.trim() !== '');
    const matchesStatus = selectedStatus === 'Todos'
      || (selectedStatus === 'Sin asignación' && !hasAssignment)
      || (scheduleStatusClasses[selectedStatus]
        ? dayCells.some((cell) => cell.classList.contains(scheduleStatusClasses[selectedStatus]))
        : false);
    const matches = matchesQuery && matchesStatus;
    row.hidden = !matches;
    if (matches) visibleCount += 1;
  });
  document.querySelector('#schedule-table tbody .schedule-filter-empty')?.remove();
  if ((query || selectedStatus !== 'Todos') && rows.length && visibleCount === 0) {
    $('#schedule-table tbody').insertAdjacentHTML('beforeend', '<tr class="schedule-filter-empty"><td class="empty-state" colspan="40">No hay registros que coincidan con los filtros seleccionados.</td></tr>');
  }
  if (clearScheduleFilter) clearScheduleFilter.hidden = !query;
  if (scheduleRecordCount) {
    if (query || selectedStatus !== 'Todos') {
      scheduleRecordCount.textContent = `${visibleCount} de ${rows.length} registros`;
    } else {
      scheduleRecordCount.textContent = `${rows.length} ${rows.length === 1 ? 'registro' : 'registros'}`;
    }
  }
}
function showScheduleFeedback(message, credential = '') {
  const normalizedCredential = String(credential ?? '').trim();
  const row = normalizedCredential
    ? [...document.querySelectorAll('#schedule-table tbody tr[data-credential]')]
      .find((candidate) => candidate.dataset.credential.trim() === normalizedCredential)
    : null;
  if (row) {
    row.classList.remove('schedule-row-notice');
    void row.offsetWidth;
    row.classList.add('schedule-row-notice');
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => row.classList.remove('schedule-row-notice'), 3200);
  } else {
    scheduleTableCard?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  showScheduleMessage(message);
}
function setScheduleFormLoading(isLoading) {
  state.savingRecord = isLoading;
  document.querySelectorAll('.schedule-form-card input, .schedule-form-card select, .schedule-form-card button, .schedule-assignment-actions button').forEach((element) => {
    if (element.id === 'create-record') return;
    if (isLoading) {
      scheduleFormDisabledState.set(element, element.disabled);
      element.disabled = true;
    } else if (scheduleFormDisabledState.has(element)) {
      element.disabled = scheduleFormDisabledState.get(element);
      scheduleFormDisabledState.delete(element);
    }
  });
  updateCalendarLock();
}
function waitForLoadingPaint() {
  return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}
function updateSaveAssignmentButton() {
  if (!saveAssignmentButton || saveAssignmentButton.classList.contains('is-loading')) return;
  saveAssignmentButton.hidden = Boolean(scheduleAssignmentModal && state.selectedRecord && !state.editingDays.size);
  saveAssignmentButton.textContent = (scheduleAssignmentModal || !state.editingDays.size) ? 'Guardar asignación' : 'Guardar edición';
}
function updateScheduleAssignmentCancelButton() {
  if (scheduleAssignmentCancelButton) {
    scheduleAssignmentCancelButton.textContent = state.editingDays.size ? 'Cancelar edición' : 'Cancelar';
  }
}
function setEditModeActionsVisible(visible) {
  if (cancelEditButton) cancelEditButton.hidden = !visible;
}
function setRecordFieldsEnabled(enabled) { controllerName.disabled = !enabled; controllerCredential.disabled = !enabled; controllerSearch.disabled = !enabled; controllerSearch.setAttribute('aria-readonly', String(!enabled)); if (!enabled) setControllerMenuOpen(false); }
function setRouteFieldsEnabled(enabled) { routeSelect.disabled = !enabled; shiftSelect.disabled = !enabled; routeNomenclature.disabled = true; }
function updateRouteFieldsForMode() { setRouteFieldsEnabled(!state.selectedRecord || state.mode === 'work'); }
function finishDayEdit() { state.editingDays.clear(); state.editingSnapshots.clear(); if (dayEditActions) dayEditActions.hidden = true; if (editingDayLabel) editingDayLabel.textContent = ''; setEditModeActionsVisible(false); setRecordFieldsEnabled(false); setRouteFieldsEnabled(false); updateSaveAssignmentButton(); updateScheduleAssignmentCancelButton(); }
function markDayForEdit(day) {
  if (!state.selectedRecord || state.editingSnapshots.has(day)) return;
  state.editingDays.add(day);
  state.editingSnapshots.set(day, { assignment: state.assignments[String(day)], detail: state.dailyDetails[String(day)], work: state.work.has(day), rest: state.rest.has(day), vacation: state.vacation.has(day), special: state.specialStates.filter((item) => state.special[item.codigo]?.has(day)).map((item) => item.codigo) });
  saveAssignmentButton.disabled = false;
  updateSaveAssignmentButton();
  updateScheduleAssignmentCancelButton();
}
function clearDayAssignment(day) {
  const dayKey = String(day);
  delete state.assignments[dayKey];
  delete state.dailyDetails[dayKey];
  state.work.delete(day);
  state.rest.delete(day);
  state.vacation.delete(day);
  state.specialStates.forEach((item) => state.special[item.codigo]?.delete(day));
}
function markLastEditedDay(day) {
  state.lastEditedDay = day;
  state.editedDays = new Set([day]);
  if (state.editedTimer) clearTimeout(state.editedTimer);
  state.editedTimer = setTimeout(() => {
    state.editedDays = new Set();
    state.lastEditedDay = null;
    renderCalendar();
    loadRecords();
  }, 1400);
}
function dayHasAssignment(day) { return Boolean(state.assignments[String(day)] || state.dailyDetails[String(day)] || state.work.has(day) || state.rest.has(day) || state.vacation.has(day)); }
function detailForDay(day) { return state.dailyDetails[String(day)] || { route: state.selectedRecord?.route || '', shift: state.selectedRecord?.shift || '', nomenclature: state.selectedRecord?.nomenclature || routeNomenclature.value || '', code: state.assignments[String(day)] || '' }; }
function createNewRecord() { clearPendingCodeConflicts(); resetClearDaysUndo(); finishDayEdit(); state.selectedRecord = null; state.calendarEditingEnabled = true; state.work.clear(); state.rest.clear(); state.vacation.clear(); state.assignments = {}; state.dailyDetails = {}; state.editedDays.clear(); state.specialStates.forEach((item) => state.special[item.codigo]?.clear()); form.reset(); controllerName.value = ''; controllerCredential.value = ''; routeSelect.value = ''; shiftSelect.value = ''; routeNomenclature.value = ''; setRecordFieldsEnabled(true); setRouteFieldsEnabled(true); saveAssignmentButton.disabled = false; updateSaveAssignmentButton(); $('#code-preview').textContent = '--'; setFormMessage('Listo para crear un nuevo registro.'); renderCalendar(); controllerName.focus(); }
function clearScheduleEditorAfterSave(message) {
  clearPendingCodeConflicts();
  resetClearDaysUndo();
  finishDayEdit();
  state.selectedRecord = null;
  state.calendarEditingEnabled = false;
  state.work.clear();
  state.rest.clear();
  state.vacation.clear();
  state.assignments = {};
  state.dailyDetails = {};
  state.editedDays.clear();
  state.lastEditedDay = null;
  state.specialStates.forEach((item) => state.special[item.codigo]?.clear());
  form.reset();
  controllerName.value = '';
  controllerCredential.value = '';
  controllerSearch.value = '';
  routeSelect.value = '';
  shiftSelect.value = '';
  routeNomenclature.value = '';
  setRecordFieldsEnabled(false);
  setRouteFieldsEnabled(false);
  saveAssignmentButton.disabled = true;
  updateSaveAssignmentButton();
  $('#code-preview').textContent = '--';
  setFormMessage(message);
  renderCalendar();
  updateCalendarLock();
}
function daysInMonth() { return new Date(state.year, state.month, 0).getDate(); }
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[character]));
function renderControllerOptions() {
  const selectedCredential = controllerCredential.value || state.selectedRecord?.credential || '';
  const usedCredentials = new Set(
    state.monthRecords
      .filter((record) => record.credential !== selectedCredential)
      .map((record) => record.credential)
  );
  const search = (controllerSearch?.value || '').trim().toLowerCase();
  const options = state.controllerCatalog.filter((controller) => {
    const isSelected = controller.credencial === selectedCredential;
    const isAvailable = isSelected || !usedCredentials.has(controller.credencial);
    if (!isAvailable) return false;
    if (!search) return true;
    return `${controller.nombre} ${controller.credencial}`.toLowerCase().includes(search);
  });

  const datalist = document.getElementById('controller-search-options');
  if (datalist) {
    datalist.innerHTML = options.map((item) => `<option value="${escapeHtml(item.nombre)}" data-credential="${escapeHtml(item.credencial)}"></option>`).join('');
  }
  if (controllerSearchMenu) {
    controllerSearchMenu.innerHTML = options.length ? options.map((item) => {
      const initials = item.nombre.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
      return `<button class="combo-option" type="button" role="option" data-name="${escapeHtml(item.nombre)}" data-credential="${escapeHtml(item.credencial)}"><span class="combo-option-avatar" aria-hidden="true">${escapeHtml(initials)}</span><span class="combo-option-copy"><strong>${escapeHtml(item.nombre)}</strong><small>Credencial ${escapeHtml(item.credencial)}</small></span><span class="combo-option-arrow" aria-hidden="true">›</span></button>`;
    }).join('') : '<span class="combo-empty">No hay trabajadores disponibles</span>';
    controllerSearchMenu.hidden = !controllerMenuOpen;
  }

  controllerCredential.innerHTML = '<option value="">Selecciona una credencial</option>' + options.map((item) => `<option value="${escapeHtml(item.credencial)}" data-name="${escapeHtml(item.nombre)}">${escapeHtml(item.credencial)} - ${escapeHtml(item.nombre)}</option>`).join('');

  if (selectedCredential) {
    const matchingController = state.controllerCatalog.find((item) => item.credencial === selectedCredential);
    controllerCredential.value = selectedCredential;
    if (matchingController && (!controllerName.value || controllerName.value === state.selectedRecord?.name)) {
      controllerName.value = matchingController.nombre;
      controllerSearch.value = matchingController.nombre;
    }
  } else if (!controllerName.value) {
    controllerCredential.value = '';
  }
  updateCalendarLock();

  if (controllerSearch.value && !controllerName.value) {
    const matchingController = state.controllerCatalog.find((item) => `${item.nombre} ${item.credencial}`.toLowerCase().includes(controllerSearch.value.toLowerCase()));
    if (matchingController) {
      controllerName.value = matchingController.nombre;
      controllerCredential.value = matchingController.credencial;
    }
  }
}

controllerSearchMenu?.addEventListener('mousedown', (event) => {
  const option = event.target.closest('.combo-option');
  if (!option) return;
  event.preventDefault();
  controllerSearch.value = option.dataset.name;
  controllerName.value = option.dataset.name;
  controllerCredential.value = option.dataset.credential;
  if (!state.selectedRecord) setRouteFieldsEnabled(true);
  updateCalendarLock();
  setControllerMenuOpen(false);
});

async function loadScheduleCatalogs(moduleNumber = activeModuleNumber) {
  const [controllersResponse, routesResponse, shiftsResponse] = await Promise.all([
    fetch(`/api/modulos/${moduleNumber}/controladores`),
    fetch(`/api/modulos/${moduleNumber}/rutas-registradas`),
    fetch(`/api/modulos/${moduleNumber}/turnos`)
  ]);
  if (!controllersResponse.ok || !routesResponse.ok || !shiftsResponse.ok) throw new Error('No se pudieron cargar los catálogos del registro.');
  const [controllers, routes, shifts] = await Promise.all([controllersResponse.json(), routesResponse.json(), shiftsResponse.json()]);
  if (moduleNumber !== activeModuleNumber) return;
  state.controllerCatalog = controllers;
  const activeRoutes = routes.filter((item) => String(item.estado || '').trim().toLowerCase() === 'activo');
  routeOptions.splice(0, routeOptions.length, ...activeRoutes);
  const activeShifts = shifts.filter((item) => item.activo);
  const selectedStorageKey = `selected-shifts-${moduleNumber}`;
  const availableShiftsStorageKey = `available-shifts-${moduleNumber}`;
  const storedAvailableShiftIds = localStorage.getItem(availableShiftsStorageKey);
  let selectedShiftIds = new Set(JSON.parse(localStorage.getItem(selectedStorageKey) || '[]').map(String));
  const knownAvailableShiftIds = new Set(JSON.parse(storedAvailableShiftIds || '[]').map(String));
  const availableShiftIds = new Set(activeShifts.map((item) => String(item.id)));
  if (storedAvailableShiftIds === null) {
    selectedShiftIds = new Set(availableShiftIds);
  } else {
    availableShiftIds.forEach((id) => {
      if (!knownAvailableShiftIds.has(id)) selectedShiftIds.add(id);
    });
  }
  selectedShiftIds = new Set([...selectedShiftIds].filter((id) => availableShiftIds.has(id)));
  localStorage.setItem(selectedStorageKey, JSON.stringify([...selectedShiftIds]));
  localStorage.setItem(availableShiftsStorageKey, JSON.stringify([...availableShiftIds]));
  shiftOptions = activeShifts.filter((item) => selectedShiftIds.has(String(item.id)));
  renderControllerOptions();
  renderRouteList();
  renderTurnosList();
  routeSelect.innerHTML = '<option value="">Selecciona una ruta</option>' + activeRoutes.map((item) => `<option value="${escapeHtml(item.ruta)}" data-nomenclature="${escapeHtml(item.nomenclatura)}">${escapeHtml(item.nomenclatura)} - ${escapeHtml(item.ruta)} (${escapeHtml(item.origen)} / ${escapeHtml(item.destino)})</option>`).join('');
  shiftSelect.innerHTML = '<option value="">Selecciona un turno</option>' + shiftOptions.map((item) => `<option value="${escapeHtml(item.numero)}">${escapeHtml(item.numero)}</option>`).join('');
}
function renderCalendar() {
  const first = (new Date(state.year, state.month - 1, 1).getDay() + 6) % 7;
  const calendar = $('#calendar'); calendar.innerHTML = weekdays.map((day) => `<span class="weekday">${day}</span>`).join('');
  for (let i = 0; i < first; i += 1) calendar.insertAdjacentHTML('beforeend', '<span class="day blank"></span>');
  for (let day = 1; day <= daysInMonth(); day += 1) {
    const specialState = state.specialStates.find((item) => state.special[item.codigo]?.has(day));
    const specialStatus = {
      trabajo: 'work',
      descanso: 'rest',
      falta: 'absence',
      vacaciones: 'vacation',
      incapacidad: 'incapacity',
    }[specialState?.categoria] || 'special';
    const status = state.editingDays.has(day) ? 'editing-day' : specialState ? specialStatus : state.vacation.has(day) ? 'vacation' : state.work.has(day) ? 'work' : state.rest.has(day) ? 'rest' : '';
    const detail = detailForDay(day);
    const assignment = state.assignments[String(day)];
    const assignmentCategory = state.specialStates.find((item) => item.codigo === assignment)?.categoria;
    const label = assignment === 'V' || assignmentCategory === 'vacaciones' ? 'V' : assignment || (specialState ? specialState.codigo : state.vacation.has(day) ? 'V' : state.work.has(day) ? `${detail.nomenclature}${detail.shift}` : state.rest.has(day) ? 'D' : '—');
    const edited = state.editedDays.has(day) ? ' edited-day' : '';
    const currentCredential = String(controllerCredential.value || state.selectedRecord?.credential || '').trim();
    const dayCode = state.dailyDetails[String(day)]?.code || assignment || '';
    const duplicate = hasDuplicateRouteCode(dayCode, day, currentCredential);
    const duplicateClass = duplicate ? ' duplicate-day' : '';
    const title = duplicate ? `Código duplicado ${dayCode}. Haz clic para editar.` : 'Haz clic para asignar, editar o cancelar';
    calendar.insertAdjacentHTML('beforeend', `<button type="button" class="day ${status}${edited}${duplicateClass}" data-day="${day}" title="${escapeHtml(title)}"><b>${day}</b><small>${escapeHtml(label)}</small></button>`);
  }
  updateCalendarLock();
  calendar.querySelectorAll('.day:not(.blank)').forEach((button) => button.addEventListener('click', async () => {
    if (!calendarHasController() || monthIsClosed()) return;
    const selected = Number(button.dataset.day);
    if (state.mode === 'delete') {
      if (dayHasAssignment(selected)) {
        markDayForEdit(selected);
        clearDayAssignment(selected);
        renderCalendar();
      }
      return;
    }
    if (state.mode === 'md') {
      if (state.selectedRecord) markDayForEdit(selected);
      ['rest', 'vacation'].forEach((mode) => state[mode].delete(selected));
      state.specialStates.forEach((item) => state.special[item.codigo]?.delete(selected));
      state.work.add(selected);
      state.assignments[String(selected)] = 'MD';
      delete state.dailyDetails[String(selected)];
      renderCalendar();
      return;
    }
    if (state.mode === 'work' && !workAssignmentReady()) return;
    const hasAssignment = dayHasAssignment(selected);
    const isSpecialMode = Boolean(state.special[state.mode]);

    if (hasAssignment && state.mode !== 'work') {
      markDayForEdit(selected);
      ['work','rest','vacation'].forEach((mode) => state[mode].delete(selected));
      state.specialStates.forEach((item) => state.special[item.codigo]?.delete(selected));
      delete state.assignments[String(selected)];
      delete state.dailyDetails[String(selected)];

      if (isSpecialMode) {
        const selectedState = state.specialStates.find((item) => item.codigo === state.mode);
        if (selectedState.categoria === 'vacaciones') {
          state.vacation.add(selected);
          state.assignments[String(selected)] = 'V';
        } else {
          state.special[state.mode].add(selected);
          state.assignments[String(selected)] = state.mode;
          if (selectedState.categoria === 'trabajo') state.work.add(selected);
          if (selectedState.categoria === 'descanso') state.rest.add(selected);
        }
      } else if (state.mode === 'vacation') {
        state.vacation.add(selected);
        state.assignments[String(selected)] = 'V';
      } else if (state.mode === 'rest') {
        state.rest.add(selected);
      }

      renderCalendar();
      return;
    }

    if (hasAssignment && state.mode === 'work' && state.selectedRecord) { editCalendarDay(selected); return; }

    if (state.selectedRecord && (state.mode !== 'work' || !hasAssignment)) markDayForEdit(selected);
    const active = state[state.mode];
    ['work','rest','vacation'].forEach((mode) => state[mode].delete(selected));
    state.specialStates.forEach((item) => { if (item.codigo !== state.mode) state.special[item.codigo]?.delete(selected); });
    if (isSpecialMode) {
      const selectedState = state.specialStates.find((item) => item.codigo === state.mode);
      if (selectedState.categoria === 'vacaciones') {
        state.vacation.add(selected);
        state.assignments[String(selected)] = 'V';
      } else {
        state.special[state.mode].has(selected) ? state.special[state.mode].delete(selected) : state.special[state.mode].add(selected);
        if (state.special[state.mode].has(selected)) {
          state.assignments[String(selected)] = state.mode;
          if (selectedState.categoria === 'trabajo') state.work.add(selected);
          if (selectedState.categoria === 'descanso') state.rest.add(selected);
        } else {
          delete state.assignments[String(selected)];
          state.work.delete(selected);
        }
      }
    } else if (state.mode === 'vacation') {
      active.has(selected) ? active.delete(selected) : active.add(selected);
      if (active.has(selected)) state.assignments[String(selected)] = 'V';
      else delete state.assignments[String(selected)];
    } else if (state.mode === 'rest') {
      active.has(selected) ? active.delete(selected) : active.add(selected);
      delete state.assignments[String(selected)];
    } else {
      const selectedCode = `${routeNomenclature.value}${shiftSelect.value}`;
      if (!active.has(selected)) {
        const decision = await confirmCodeConflict(selectedCode, selected, controllerCredential.value);
        if (!decision) return;
      }
      active.add(selected);
      state.assignments[String(selected)] = selectedCode;
      state.dailyDetails[String(selected)] = { route: routeSelect.value, shift: shiftSelect.value, nomenclature: routeNomenclature.value, code: selectedCode };
    }
    renderCalendar();
  }));
  $('#month-label').textContent = `${months[state.month - 1]} ${state.year}`;
  const monthlyRolePeriod = $('#monthly-role-period');
  if (monthlyRolePeriod) monthlyRolePeriod.textContent = `${months[state.month - 1]} ${state.year}`;
  const specialCount = state.specialStates
    .filter((item) => item.categoria !== 'trabajo')
    .reduce((total, item) => total + (state.special[item.codigo]?.size || 0), 0);
  $('#selection-summary').textContent = `${state.work.size} trabajo · ${state.rest.size} descanso · ${state.vacation.size} vacaciones · ${specialCount} especiales`;
}
let activeScheduleActions = null;
function closeScheduleActions() {
  if (!activeScheduleActions) return;
  const { actions, button, cell, row } = activeScheduleActions;
  actions.hidden = true;
  actions.classList.remove('is-floating');
  actions.style.removeProperty('top');
  actions.style.removeProperty('left');
  cell.appendChild(actions);
  button.setAttribute('aria-expanded', 'false');
  row.classList.remove('has-open-actions');
  activeScheduleActions = null;
}
document.addEventListener('scroll', closeScheduleActions, true);
window.addEventListener('resize', closeScheduleActions);

function renderTable(records) {
  closeScheduleActions();
  state.monthRecords = records || [];
  const isAdminEmbedded = body.classList.contains('admin-embedded-role');
  const grouped = [...new Map(records.map((record) => [record.credential, record])).values()];
  const controllerMap = new Map(state.controllerCatalog.map((controller) => [controller.credencial, controller]));
  if (monthlyRoleCount) monthlyRoleCount.textContent = String(grouped.length);
  if (scheduleRecordCount) {
    scheduleRecordCount.textContent = `${grouped.length} ${grouped.length === 1 ? 'registro' : 'registros'}`;
  }
  $('#schedule-table thead').innerHTML = `<tr>${isAdminEmbedded ? '<th>Controlador</th>' : '<th>Nombre</th><th>Cred.</th>'}${Array.from({length: daysInMonth()}, (_, i) => { const day = i + 1; const initial = ['D', 'L', 'M', 'M', 'J', 'V', 'S'][new Date(state.year, state.month - 1, day).getDay()]; return `<th class="schedule-day-header"><span class="schedule-day-number">${day}</span><span class="schedule-day-initial">${initial}</span></th>`; }).join('')}</tr>`;
  $('#schedule-table tbody').innerHTML = grouped.length ? grouped.map((record) => {
    const controller = controllerMap.get(record.credential);
    const displayName = controller?.nombre || record.name;
    const assignments = record.daily_assignments || {}; const details = record.daily_details || {}; const work = new Set(record.work_days || []); const rest = new Set(record.rest_days || []);
    const cells = Array.from({length: daysInMonth()}, (_, i) => {
      const day = i + 1;
      const detail = details[String(day)];
      const code = detail?.code || assignments[String(day)];
      const custom = detail ? ' table-custom' : '';
      const edited = state.lastEditedDay === day ? ' table-edited-last' : '';
      const category = state.specialStates.find((item) => item.codigo === code)?.categoria;
      const duplicateCode = code || (work.has(day) ? `${record.nomenclature}${record.shift}` : '');
      const duplicate = hasDuplicateRouteCode(duplicateCode, day, record.credential);
      const duplicateClass = duplicate ? ' table-duplicate' : '';
      const marker = duplicate ? '<span class="duplicate-marker" aria-label="Código duplicado">!</span>' : '';
      const cell = (className, value) => `<td class="${className}${custom}${edited}${duplicateClass}"${duplicate ? ' title="Código duplicado en este día"' : ''}>${escapeHtml(value)}${marker}</td>`;
      if (code === 'V' || category === 'vacaciones') return cell('table-vacation', 'V');
      if (category === 'trabajo') return cell('table-work', code);
      if (category === 'descanso') return cell('table-rest', code);
      if (category === 'falta') return cell('table-absence', code);
      if (category === 'incapacidad') return cell('table-incapacity', code);
      if (code === 'MD') return cell('table-work', 'MD');
      if (code && !/^[A-Z]+\d+$/.test(code)) return cell('table-special', code);
      if (code) return cell('table-work', code);
      if (work.has(day)) return cell('table-work', `${record.nomenclature}${record.shift}`);
      if (rest.has(day)) return cell('table-rest', 'D');
      return '<td></td>';
    }).join('');
    const disabled = monthIsClosed() ? ' disabled' : '';
    const actions = `<div class="table-row-actions"${isAdminEmbedded ? ' hidden' : ''}><button class="table-update-button" type="button" data-credential="${escapeHtml(record.credential)}" title="Editar registro de ${escapeHtml(displayName)}"${disabled}>Editar</button><button class="table-delete-button" type="button" data-credential="${escapeHtml(record.credential)}" title="Eliminar registro de ${escapeHtml(displayName)}"${disabled}>Eliminar</button></div>`;
    const nameCell = isAdminEmbedded
      ? `<td class="name-cell admin-role-name-cell"><div class="admin-role-controller-cell"><button class="table-actions-toggle" type="button" data-credential="${escapeHtml(record.credential)}" aria-label="Acciones para ${escapeHtml(displayName)}" aria-expanded="false" title="Mostrar acciones"><span aria-hidden="true">⋮</span></button><div class="person-meta"><button class="person-button" type="button" data-credential="${escapeHtml(record.credential)}">${escapeHtml(displayName)}</button><small class="person-credential">${escapeHtml(record.credential)}</small></div>${actions}</div></td>`
      : `<td class="name-cell"><div class="person-meta"><button class="person-button" type="button" data-credential="${escapeHtml(record.credential)}">${escapeHtml(displayName)}</button></div>${actions}</td><td>${escapeHtml(record.credential)}</td>`;
    return `<tr data-credential="${escapeHtml(record.credential)}">${nameCell}${cells}</tr>`;
  }).join('') : '<tr><td class="empty-state" colspan="40">No hay registros para este mes.</td></tr>';
  filterScheduleTable();
  document.querySelectorAll('.table-actions-toggle').forEach((button) => button.addEventListener('click', () => {
    const controllerCell = button.closest('.admin-role-controller-cell');
    const actions = activeScheduleActions?.button === button
      ? activeScheduleActions.actions
      : controllerCell.querySelector('.table-row-actions');
    if (!actions) return;
    const willExpand = actions.hidden;
    closeScheduleActions();
    if (!willExpand) return;

    actions.hidden = false;
    const menuBounds = actions.getBoundingClientRect();
    const cellBounds = controllerCell.getBoundingClientRect();
    const padding = 8;
    const gap = 4;
    const spaceBelow = window.innerHeight - cellBounds.bottom - padding;
    const spaceAbove = cellBounds.top - padding;
    const openUp = spaceBelow < menuBounds.height + gap && spaceAbove > spaceBelow;
    const preferredTop = openUp
      ? cellBounds.top - menuBounds.height + 1
      : cellBounds.bottom - 1;
    const maxTop = Math.max(padding, window.innerHeight - menuBounds.height - padding);
    const top = Math.max(padding, Math.min(preferredTop, maxTop));
    const maxLeft = Math.max(padding, window.innerWidth - menuBounds.width - padding);
    const left = Math.max(padding, Math.min(cellBounds.left, maxLeft));

    actions.classList.add('is-floating');
    document.body.appendChild(actions);
    actions.style.top = `${top}px`;
    actions.style.left = `${left}px`;
    button.setAttribute('aria-expanded', 'true');
    const row = button.closest('tr');
    row.classList.add('has-open-actions');
    activeScheduleActions = { actions, button, cell: controllerCell, row };
  }));
  document.querySelectorAll('.person-button').forEach((button) => button.addEventListener('click', () => selectRecord(grouped.find((item) => item.credential === button.dataset.credential))));
  document.querySelectorAll('.table-update-button:not(:disabled)').forEach((button) => button.addEventListener('click', () => {
    if (isAdminEmbedded) {
      closeScheduleActions();
    }
    setScheduleGridCollapsed(false);
    const record = grouped.find((item) => item.credential === button.dataset.credential);
    selectRecord(record);
    state.calendarEditingEnabled = true;
    saveAssignmentButton.disabled = false;
    setEditModeActionsVisible(true);
    state.mode = 'work';
    document.querySelectorAll('.mode-button').forEach((item) => item.classList.toggle('is-active', item.dataset.mode === 'work'));
    setRouteFieldsEnabled(true);
    updateCalendarLock();
    state.work.forEach((day) => {
      if (!codeForDay(record, day)) editCalendarDay(day);
    });
    routeSelect.value = '';
    shiftSelect.value = '';
    routeNomenclature.value = '';
    $('#code-preview').textContent = '--';
    openScheduleAssignment(false);
  }));
  renderControllerOptions();
  document.querySelectorAll('.table-delete-button:not(:disabled)').forEach((button) => button.addEventListener('click', async () => {
    if (isAdminEmbedded) {
      closeScheduleActions();
    }
    const credential = button.dataset.credential;
    if (!credential) return;
    const confirmed = window.confirm(`¿Eliminar el registro de ${credential}?`);
    if (!confirmed) {
      return;
    }
    setLoadingButton(button, true, 'Eliminando asignación...');
    showLoader('Eliminando asignación...');
    try {
      await waitForLoadingPaint();
      const response = await fetch('/api/records/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ credential, month: state.month, year: state.year, module_number: activeModuleNumber })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'No se pudo eliminar el registro.');
      clearFormMessageError();
      setFormMessage(result.deleted ? `Registro de ${credential} eliminado.` : 'No se encontró el registro para eliminar.');
      if (result.deleted) {
        state.selectedRecord = null;
        createNewRecord();
        await loadRecords();
        showScheduleFeedback('Asignación eliminada');
      }
    } catch (error) {
      setFormMessage(error.message, true);
    } finally {
      setLoadingButton(button, false, 'Eliminar');
      hideLoader();
    }
  }));
}
async function loadMonthStatus(moduleNumber = activeModuleNumber) {
  const response = await fetch(`/administrador/rol-mensual/${moduleNumber}/estado?month=${state.month}&year=${state.year}`);
  const result = response.ok ? await response.json() : null;
  if (moduleNumber !== activeModuleNumber) return;
  state.monthActivated = Boolean(result?.activo);
  updateMonthEditability();
}
async function loadRecords(moduleNumber = activeModuleNumber) {
  const moduleQuery = body.dataset.tableOnly === 'true' || body.classList.contains('admin-embedded-role') ? `&module_number=${moduleNumber}` : '';
  try {
    const response = await fetch(`/api/records?month=${state.month}&year=${state.year}${moduleQuery}`);
    if (!response.ok) throw new Error('No se pudieron cargar los registros del rol mensual.');
    const records = await response.json();
    if (moduleNumber === activeModuleNumber) renderTable(records);
  } catch (error) {
    if (moduleNumber === activeModuleNumber) setFormMessage(error.message, true);
  }
}
async function changeMonth(delta) { clearPendingCodeConflicts(); resetClearDaysUndo(); finishDayEdit(); state.month += delta; if (state.month === 0) { state.month = 12; state.year -= 1; } if (state.month === 13) { state.month = 1; state.year += 1; } state.work.clear(); state.rest.clear(); state.vacation.clear(); state.assignments = {}; state.dailyDetails = {}; state.editedDays.clear(); await loadMonthStatus(); renderCalendar(); loadRecords(); }
function selectRecord(record) {
  if (!record) return;
  clearPendingCodeConflicts();
  resetClearDaysUndo();
  state.selectedRecord = record;
  state.calendarEditingEnabled = false;
  const currentController = state.controllerCatalog.find((item) => item.credencial === record.credential);
  controllerName.value = currentController?.nombre || record.name;
  controllerCredential.value = record.credential;
  routeSelect.value = record.route;
  routeNomenclature.value = record.nomenclature || routeSelect.selectedOptions[0]?.dataset.nomenclature || '';
  shiftSelect.value = record.shift;
  renderControllerOptions();
  state.work = new Set((record.work_days || []).map(Number));
  state.rest = new Set((record.rest_days || []).map(Number));
  state.vacation = new Set();
  state.assignments = { ...(record.daily_assignments || {}) };
  state.dailyDetails = { ...(record.daily_details || {}) };
  state.editedDays = new Set();
  setRecordFieldsEnabled(false);
  finishDayEdit();
  setRouteFieldsEnabled(false);
  state.specialStates.forEach((item) => state.special[item.codigo]?.clear());
  Object.entries(record.daily_assignments || {}).forEach(([day, code]) => {
    const numericDay = Number(day);
    const category = state.specialStates.find((item) => item.codigo === code)?.categoria;
    if (code === 'V' || category === 'vacaciones') {
      state.work.delete(numericDay);
      state.rest.delete(numericDay);
      state.vacation.add(numericDay);
    } else if (state.special[code]) {
      state.work.delete(numericDay);
      state.rest.delete(numericDay);
      state.vacation.delete(numericDay);
      state.special[code].add(numericDay);
      if (category === 'trabajo') state.work.add(numericDay);
      if (category === 'descanso') state.rest.add(numericDay);
    } else if (code === 'MD' || state.dailyDetails[String(day)]) {
      state.rest.delete(numericDay);
      state.vacation.delete(numericDay);
      state.work.add(numericDay);
    }
  });
  state.rest.forEach((day) => {
    if (!state.assignments[String(day)] && !state.dailyDetails[String(day)]) {
      state.work.delete(day);
    }
  });
  setFormMessage(`Registro de ${record.name} seleccionado.`);
  updateCalendarLock();
  renderCalendar();
  document.querySelector('.schedule-form-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function editCalendarDay(day) {
  if (!state.selectedRecord || !dayHasAssignment(day)) {
    setFormMessage('Selecciona primero una persona del rol mensual.', true);
    return;
  }
  const route = routeSelect.value || state.selectedRecord.route || '';
  const shift = shiftSelect.value || state.selectedRecord.shift || '';
  if (!route || !shift) {
    if (!workAssignmentReady()) return;
  }
  markDayForEdit(day);
  const nomenclature = routeSelect.selectedOptions[0]?.dataset.nomenclature || routeNomenclature.value || state.selectedRecord.nomenclature || '';
  const code = `${nomenclature}${shift}`;
  const dayKey = String(day);
  state.dailyDetails[dayKey] = { route, shift, nomenclature, code };
  state.assignments[dayKey] = code;
  state.work.add(day);
  state.rest.delete(day);
  state.vacation.delete(day);
  state.specialStates.forEach((item) => state.special[item.codigo]?.delete(day));
  markLastEditedDay(day);
  setFormMessage(`Día ${day} preparado con el código ${code}. Presiona Guardar asignación para confirmar.`);
  renderCalendar();
}
function cancelDayEdit(dayToCancel = null) {
  const days = dayToCancel === null ? [...state.editingDays] : [dayToCancel];
  days.forEach((day) => {
    const snapshot = state.editingSnapshots.get(day);
    if (!snapshot) return;
    if (snapshot.assignment === undefined) delete state.assignments[String(day)]; else state.assignments[String(day)] = snapshot.assignment;
    if (snapshot.detail === undefined) delete state.dailyDetails[String(day)]; else state.dailyDetails[String(day)] = snapshot.detail;
    ['work', 'rest', 'vacation'].forEach((mode) => snapshot[mode] ? state[mode].add(day) : state[mode].delete(day));
    state.specialStates.forEach((item) => state.special[item.codigo]?.delete(day));
    snapshot.special.forEach((code) => state.special[code]?.add(day));
    state.editingDays.delete(day);
    state.editingSnapshots.delete(day);
  });
  if (!state.editingDays.size) finishDayEdit(); else { if (dayEditActions) dayEditActions.hidden = true; if (editingDayLabel) editingDayLabel.textContent = ''; updateSaveAssignmentButton(); }
  updateRouteFieldsForMode();
  updateScheduleAssignmentCancelButton();
  renderCalendar();
}
cancelEditButton?.addEventListener('click', () => {
  cancelDayEdit();
  state.calendarEditingEnabled = false;
  saveAssignmentButton.disabled = true;
  setEditModeActionsVisible(false);
  updateCalendarLock();
  setFormMessage('Edición cancelada');
  renderCalendar();
});
$('#previous-month').addEventListener('click', () => changeMonth(-1)); $('#next-month').addEventListener('click', () => changeMonth(1));
clearDaysButton?.addEventListener('click', () => {
  if (clearDaysSnapshot) {
    const snapshot = clearDaysSnapshot;
    clearDaysSnapshot = null;
    restoreClearDaysSnapshot(snapshot);
    updateClearDaysButton(false);
    return;
  }
  clearDaysSnapshot = captureClearDaysSnapshot();
  if (state.editedTimer) clearTimeout(state.editedTimer);
  state.editedTimer = null;
  finishDayEdit();
  state.work.clear();
  state.rest.clear();
  state.vacation.clear();
  state.assignments = {};
  state.dailyDetails = {};
  state.editedDays.clear();
  state.lastEditedDay = null;
  state.specialStates.forEach((item) => state.special[item.codigo]?.clear());
  updateClearDaysButton(true);
  renderCalendar();
  updateCalendarLock();
});
$('#create-record')?.addEventListener('click', createNewRecord);
scheduleRecordFilter?.addEventListener('input', filterScheduleTable);
scheduleStatusFilter?.addEventListener('change', filterScheduleTable);
clearScheduleFilter?.addEventListener('click', () => {
  scheduleRecordFilter.value = '';
  filterScheduleTable();
  scheduleRecordFilter.focus();
});
function bindModeButtons() { document.querySelectorAll('.mode-button').forEach((button) => button.addEventListener('click', () => { state.mode = button.dataset.mode; document.querySelectorAll('.mode-button').forEach((item) => item.classList.toggle('is-active', item === button)); updateRouteFieldsForMode(); })); }
$('#download-excel').addEventListener('click', async () => {
  const button = $('#download-excel');
  const needsModuleQuery = body.dataset.tableOnly === 'true' || body.classList.contains('admin-embedded-role');
  const moduleQuery = needsModuleQuery ? `&module_number=${activeModuleNumber}` : '';
  setLoadingButton(button, true, 'Descargando...');
  showLoader('Descargando Excel...');
  await waitForLoadingPaint();
  try {
    const response = await fetch(`/export/excel?month=${state.month}&year=${state.year}${moduleQuery}`);
    if (!response.ok) throw new Error('No se pudo descargar el Excel.');
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `rol-mensual-${state.year}-${String(state.month).padStart(2, '0')}.xlsx`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    showScheduleFeedback('Excel descargado');
  } catch (error) {
    setFormMessage(error.message, true);
  } finally {
    setLoadingButton(button, false, 'Descargar Excel');
    hideLoader();
  }
});
calendarTabs.forEach((button) => {
  button.addEventListener('click', () => setCalendarTab(button.dataset.tab));
});
form.addEventListener('input', () => { $('#code-preview').textContent = `${routeNomenclature.value.trim().toUpperCase() || '—'}${shiftSelect.value || ''}`; });
controllerSearch.addEventListener('focus', () => { setControllerMenuOpen(true); renderControllerOptions(); });
controllerSearch.addEventListener('click', () => { setControllerMenuOpen(true); renderControllerOptions(); });
controllerSearch.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') { setControllerMenuOpen(false); return; }
  if (event.key === 'ArrowDown' && !controllerMenuOpen) { event.preventDefault(); setControllerMenuOpen(true); renderControllerOptions(); }
});
controllerSearch.addEventListener('blur', () => setTimeout(() => setControllerMenuOpen(false), 120));
controllerSearch.addEventListener('input', () => {
  setControllerMenuOpen(true);
  renderControllerOptions();
  const selected = state.controllerCatalog.find((item) => item.nombre.trim().toLowerCase() === controllerSearch.value.trim().toLowerCase() || item.credencial.trim().toLowerCase() === controllerSearch.value.trim().toLowerCase());
  if (selected) {
    controllerName.value = selected.nombre;
    controllerCredential.value = selected.credencial;
  } else if (!controllerSearch.value.trim()) {
    controllerName.value = '';
    controllerCredential.value = '';
  }
  if (!state.selectedRecord) setRouteFieldsEnabled(Boolean(controllerSearch.value.trim()));
  updateCalendarLock();
});
controllerName.addEventListener('change', () => {
  const option = state.controllerCatalog.find((item) => item.nombre.trim().toLowerCase() === controllerName.value.trim().toLowerCase() || item.credencial.trim().toLowerCase() === controllerName.value.trim().toLowerCase());
  if (option) {
    controllerName.value = option.nombre;
    controllerCredential.value = option.credencial;
    controllerSearch.value = option.nombre;
  }
  if (!state.selectedRecord) setRouteFieldsEnabled(Boolean(controllerName.value));
  updateCalendarLock();
});
controllerCredential.addEventListener('change', () => {
  const option = state.controllerCatalog.find((item) => item.credencial === controllerCredential.value);
  controllerName.value = option?.nombre || '';
  if (option) controllerSearch.value = option.nombre;
  updateCalendarLock();
});
routeSelect.addEventListener('change', () => { routeNomenclature.value = routeSelect.selectedOptions[0]?.dataset.nomenclature || ''; $('#code-preview').textContent = `${routeNomenclature.value}${shiftSelect.value || ''}`; });
async function readJsonResponse(response, fallbackMessage) {
  const bodyText = await response.text();
  let result;
  try {
    result = JSON.parse(bodyText);
  } catch {
    const status = response.status ? ` (HTTP ${response.status})` : '';
    throw new Error(`El servidor devolvió una respuesta inesperada en lugar de JSON${status}. Revisa el registro del servidor.`);
  }
  if (!response.ok) throw new Error(result.error || fallbackMessage);
  return result;
}
function currentRecordPayload(extra = {}) {
  const base = state.selectedRecord || {};
  const credential = controllerCredential.value || base.credential;
  const forceUpdate = Boolean(state.selectedRecord && state.selectedRecord.credential === credential);
  return {
    name: controllerName.value || base.name,
    credential,
    route: routeSelect.value || base.route,
    shift: shiftSelect.value || base.shift,
    nomenclature: routeNomenclature.value || base.nomenclature,
    month: state.month,
    year: state.year,
    module_number: activeModuleNumber,
    work_days: [...state.work],
    rest_days: [...state.rest],
    vacation_days: [...state.vacation],
    daily_assignments: { ...state.assignments },
    daily_details: { ...state.dailyDetails },
    force_update: forceUpdate,
    ...extra,
  };
}
function pendingTransferPayload() {
  const targetCredential = String(controllerCredential.value || state.selectedRecord?.credential || '').trim();
  return state.pendingCodeTransfers
    .filter((item) => {
      const dayKey = String(item.day);
      const code = state.dailyDetails[dayKey]?.code || state.assignments[dayKey] || '';
      return item.target_credential === targetCredential
        && state.work.has(item.day)
        && String(code).trim().toUpperCase() === item.code;
    })
    .map(({ source_credential, target_credential, day, code }) => ({
      source_credential,
      target_credential,
      day,
      code,
    }));
}
async function saveRecord(extra = {}) {
  const payload = currentRecordPayload(extra);
  const response = await fetch('/api/records', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
    body: JSON.stringify(payload),
  });
  return readJsonResponse(response, 'No se pudo guardar.');
}
async function saveAllRecords() {
  if (monthIsClosed()) { setFormMessage('El mes seleccionado ya terminó y no permite modificaciones.', true); return; }
  setLoadingButton(saveAllRecordsButton, true, 'Guardando...');
  showLoader('Guardando asignaciones...');
  try {
    const transfers = pendingTransferPayload();
    let records = state.monthRecords;
    if (transfers.length) {
      const currentRecord = currentRecordPayload();
      const currentIndex = records.findIndex((record) => record.credential === currentRecord.credential);
      records = [...records];
      if (currentIndex >= 0) records[currentIndex] = currentRecord;
      else records.push(currentRecord);
    }
    const response = await fetch('/api/records/save-all', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        month: state.month,
        year: state.year,
        module_number: activeModuleNumber,
        records,
        transfers,
      }),
    });
    const result = await readJsonResponse(response, 'No se pudieron guardar los registros.');
    if (transfers.length) {
      clearPendingCodeConflicts();
      await loadRecords();
      const selectedRecord = state.monthRecords.find((record) => record.credential === currentRecordPayload().credential);
      if (selectedRecord) state.selectedRecord = selectedRecord;
      renderCalendar();
    }
    clearFormMessageError();
    setFormMessage(`${result.saved_count} registro${result.saved_count === 1 ? '' : 's'} guardado${result.saved_count === 1 ? '' : 's'} correctamente.`);
    showScheduleFeedback('Asignaciones guardadas');
  } catch (error) {
    setFormMessage(error.message, true);
  } finally {
    setLoadingButton(saveAllRecordsButton, false, 'Guardado');
    hideLoader();
  }
}
saveAllRecordsButton?.addEventListener('click', saveAllRecords);
document.querySelector('#activate-month')?.addEventListener('click', async function () {
  const activate = !state.monthActivated;
  const bodyData = new URLSearchParams({ month: String(state.month), year: String(state.year), activo: String(activate) });
  try {
    const response = await fetch(`/administrador/rol-mensual/${activeModuleNumber}/estado`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: bodyData });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'No se pudo cambiar el estado del mes.');
    state.monthActivated = Boolean(result.activo);
    clearFormMessageError();
    updateMonthEditability();
    renderTable(state.monthRecords);
    document.dispatchEvent(new CustomEvent('admin-month-status-updated', {
      detail: { active: state.monthActivated }
    }));
  } catch (error) {
    setFormMessage(error.message, true);
  }
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (monthIsClosed()) { setFormMessage('El mes seleccionado ya terminó y no permite modificaciones.', true); return; }
  if (scheduleAssignmentModal && state.selectedRecord && !state.editingDays.size) {
    setFormMessage('Realiza una modificación en al menos un día del calendario antes de guardar.', true);
    return;
  }
  const hasEditingDays = state.editingDays.size > 0;
  if (hasEditingDays && [...state.editingDays].some((day) => {
    const code = state.assignments[String(day)];
    const category = state.specialStates.find((item) => item.codigo === code)?.categoria;
    return state.work.has(day)
      && code !== 'MD'
      && category !== 'trabajo'
      && (!state.dailyDetails[String(day)]?.route || !state.dailyDetails[String(day)]?.shift);
  })) {
    setFormMessage('Selecciona una ruta y un turno para los días de trabajo editados.', true);
    return;
  }
  const selectedDays = hasEditingDays ? [...state.editingDays] : [];
  const wasUpdating = Boolean(state.selectedRecord);
  const loadingLabel = wasUpdating ? 'Actualizando asignación...' : 'Guardando registro...';
  const successMessage = wasUpdating
    ? `${selectedDays.length} día${selectedDays.length === 1 ? '' : 's'} actualizado${selectedDays.length === 1 ? '' : 's'}.`
    : 'Asignación guardada.';
  let savedSuccessfully = false;
  try {
    if (hasEditingDays) {
      for (const day of selectedDays) {
        const detail = state.dailyDetails[String(day)];
        const category = state.specialStates.find((item) => item.codigo === state.assignments[String(day)])?.categoria;
        if (state.work.has(day) && state.assignments[String(day)] !== 'MD' && category !== 'trabajo' && (!detail?.route || !detail?.shift || !detail?.code)) {
          throw new Error(`El día ${day} necesita una ruta y un turno válidos.`);
        }
        if (state.work.has(day) && state.assignments[String(day)] !== 'MD' && category !== 'trabajo') {
          const decision = await confirmCodeConflict(detail.code, day, controllerCredential.value || state.selectedRecord?.credential);
          if (!decision) return;
        }
      }
    }
    setScheduleFormLoading(true);
    setLoadingButton(saveAssignmentButton, true, loadingLabel);
    showLoader(loadingLabel);
    await waitForLoadingPaint();
    const savedCredential = String(controllerCredential.value || state.selectedRecord?.credential || '').trim();
    const saveOptions = selectedDays.length ? { edited_days: selectedDays } : {};
    const transfers = pendingTransferPayload();
    if (transfers.length) saveOptions.transfers = transfers;
    const saved = await saveRecord(saveOptions);
    const feedbackMessage = wasUpdating ? 'Asignación actualizada' : 'Asignación guardada';
    savedSuccessfully = true;
    state.selectedRecord = saved;
    clearFormMessageError();
    if (hasEditingDays) {
      finishDayEdit();
      state.calendarEditingEnabled = false;
      setFormMessage(`${selectedDays.length} día${selectedDays.length === 1 ? '' : 's'} actualizado${selectedDays.length === 1 ? '' : 's'}.`);
    } else {
      state.lastEditedDay = null;
      state.editedDays = new Set();
      setFormMessage('Asignación guardada.');
    }
    renderCalendar();
    await loadRecords();
    showScheduleFeedback(feedbackMessage, savedCredential);
  } catch (error) {
    setFormMessage(error.message, true);
  } finally {
    setLoadingButton(saveAssignmentButton, false, 'Guardar asignación');
    setScheduleFormLoading(false);
    hideLoader();
    if (savedSuccessfully) {
      clearScheduleEditorAfterSave(successMessage);
      closeScheduleAssignment();
    }
    updateSaveAssignmentButton();
    updateCalendarLock();
  }
});
async function loadSpecialStates() {
  if (specialStatesLoaded) return;
  if (!specialStatesLoadPromise) {
    specialStatesLoadPromise = (async function () {
      const response = await fetch('/api/catalogos/estados_especiales');
      if (!response.ok) throw new Error('No se pudieron cargar los estados especiales.');
      state.special = {};
      state.specialStates = (await response.json()).filter((item) => item.activo);
      state.specialStates.forEach((item) => {
        state.special[item.codigo] = new Set();
        $('#calendar-modes').insertAdjacentHTML('beforeend', `<button class="mode-button special-mode" data-mode="${escapeHtml(item.codigo)}" type="button" title="${escapeHtml(item.descripcion)}">${escapeHtml(item.codigo)} - ${escapeHtml(item.descripcion)}</button>`);
      });
      bindModeButtons();
      specialStatesLoaded = true;
    })().finally(function () {
      if (!specialStatesLoaded) specialStatesLoadPromise = null;
    });
  }
  await specialStatesLoadPromise;
}
async function initializeScheduleModule(moduleNumber = activeModuleNumber) {
  resetClearDaysUndo();
  activeModuleNumber = String(moduleNumber || '');
  body.dataset.module = activeModuleNumber;
  initializedModuleNumber = activeModuleNumber;
  const loadVersion = ++moduleLoadVersion;
  if (scheduleAssignmentModal && !scheduleAssignmentModal.hidden) closeScheduleAssignment();
  finishDayEdit();
  state.selectedRecord = null;
  updateSaveAssignmentButton();
  state.work.clear();
  state.rest.clear();
  state.vacation.clear();
  state.assignments = {};
  state.dailyDetails = {};
  state.editedDays.clear();
  state.lastEditedDay = null;
  state.monthRecords = [];
  state.specialStates.forEach((item) => state.special[item.codigo]?.clear());
  state.controllerCatalog = [];
  routeOptions.splice(0, routeOptions.length);
  shiftOptions = [];
  state.monthActivated = false;
  if (!activeModuleNumber) {
    renderTable([]);
    return;
  }
  form.reset();
  controllerSearch.value = '';
  controllerName.value = '';
  controllerCredential.value = '';
  routeSelect.innerHTML = '<option value="">Selecciona una ruta</option>';
  shiftSelect.innerHTML = '<option value="">Selecciona un turno</option>';
  routeNomenclature.value = '';
  setRecordFieldsEnabled(true);
  setRouteFieldsEnabled(false);
  saveAssignmentButton.disabled = false;
  $('#code-preview').textContent = '--';
  setFormMessage('');
  renderTable([]);
  try {
    await Promise.all([loadScheduleCatalogs(activeModuleNumber), loadSpecialStates(), loadMonthStatus(activeModuleNumber)]);
    if (loadVersion !== moduleLoadVersion) return;
    await loadRecords(activeModuleNumber);
    if (loadVersion !== moduleLoadVersion) return;
    renderCalendar();
  } catch (error) {
    if (loadVersion === moduleLoadVersion) setFormMessage(error.message, true);
  } finally {
    if (loadVersion === moduleLoadVersion) updateMonthEditability();
  }
}

document.addEventListener('admin-module-changed', function (event) {
  if (!body.classList.contains('admin-role-standalone')) return;
  const moduleNumber = String(event.detail?.moduleId || '');
  if (moduleNumber && moduleNumber !== activeModuleNumber) initializeScheduleModule(moduleNumber);
});

document.addEventListener('admin-role-section-changed', function (event) {
  if (event.detail?.section === 'monthly-role-section') return;
  closeScheduleAssignment();
});

document.addEventListener('DOMContentLoaded', function () {
  if (initializedModuleNumber !== activeModuleNumber) initializeScheduleModule(activeModuleNumber);
});
