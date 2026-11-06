const body = document.body;
let activeModuleNumber = String(body.dataset.module || '');
let moduleLoadVersion = 0;
let initializedModuleNumber = '';
let specialStatesLoaded = false;
let specialStatesLoadPromise = null;
const state = { year: Number(body.dataset.year), month: Number(body.dataset.month), monthActivated: false, calendarEditingEnabled: true, savingRecord: false, mode: 'work', work: new Set(), rest: new Set(), vacation: new Set(), special: {}, specialStates: [], assignments: {}, dailyDetails: {}, editedDays: new Set(), lastEditedDay: null, editedTimer: null, selectedRecord: null, editingDays: new Set(), editingSnapshots: new Map(), monthRecords: [], controllerCatalog: [] };
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
const saveAssignmentButton = document.querySelector('.record-form-actions .primary-button');
const cancelEditButton = $('#cancel-edit-button');
const saveAllRecordsButton = $('#save-all-records');
const scheduleRecordFilter = $('#schedule-record-filter');
const clearScheduleFilter = $('#clear-schedule-filter');
const scheduleGrid = $('#schedule-grid');
const scheduleGridToggle = $('#toggle-schedule-grid');
const scheduleTableCard = document.querySelector('.schedule-table-card');
const scheduleAssignmentModal = $('#schedule-assignment-modal');
const openScheduleAssignmentButton = $('#open-schedule-assignment');
const scheduleFeedback = $('#schedule-feedback');
const loadingOverlay = $('#loadingOverlay');
const loadingText = $('#loadingText');
const scheduleFormDisabledState = new Map();
const routeOptions = [];
let shiftOptions = [];
const calendarTabs = document.querySelectorAll('.calendar-tab');
const calendarPanels = document.querySelectorAll('.calendar-panel');
const codeConflictDialog = $('#code-conflict-dialog');
const codeConflictMessage = $('#code-conflict-message');
let resolveCodeConflict = null;
let controllerMenuOpen = false;
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
  $('#form-message').textContent = !routeSelected && !shiftSelected
    ? 'Selecciona una ruta y un turno antes de asignar un día.'
    : !routeSelected
      ? 'Selecciona una ruta antes de asignar un día.'
      : 'Selecciona un turno antes de asignar un día.';
  if (!routeSelected) routeSelect.focus();
  else shiftSelect.focus();
  return false;
}
function askCodeConflict(message) {
  codeConflictMessage.textContent = message;
  codeConflictDialog.hidden = false;
  document.body.classList.add('dialog-open');
  return new Promise((resolve) => { resolveCodeConflict = resolve; });
}
function closeCodeConflict(accepted) {
  codeConflictDialog.hidden = true;
  document.body.classList.remove('dialog-open');
  if (resolveCodeConflict) resolveCodeConflict(accepted);
  resolveCodeConflict = null;
}
function codeForDay(record, day) {
  return record?.daily_details?.[String(day)]?.code || record?.daily_assignments?.[String(day)] || '';
}
function findCodeConflict(code, day, credential) {
  return state.monthRecords.find((record) => record.credential !== credential && codeForDay(record, day) === code);
}
async function confirmCodeConflict(code, day, credential) {
  const conflict = findCodeConflict(code, day, credential);
  if (!conflict) return true;
  const name = conflict.name || conflict.credential;
  return askCodeConflict(`Estas ingresando un controlador al mismo turno y ruta. El código ${code} ya está asignado a ${name} el día ${day}. ¿Deseas continuar?`);
}
codeConflictDialog?.querySelector('[data-conflict-accept]')?.addEventListener('click', () => closeCodeConflict(true));
codeConflictDialog?.querySelectorAll('[data-conflict-cancel]').forEach((element) => element.addEventListener('click', () => closeCodeConflict(false)));
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
  scheduleGridToggle.setAttribute('aria-expanded', String(!collapsed));
  const action = collapsed ? 'Mostrar' : 'Ocultar';
  scheduleGridToggle.setAttribute('aria-label', `${action} formulario`);
  scheduleGridToggle.title = `${action} formulario`;
  scheduleGridToggle.querySelector('.schedule-grid-toggle-icon').textContent = collapsed ? '🠋' : '🠉';
  scheduleGridToggle.querySelector('.schedule-grid-toggle-text').textContent = `${action} formulario`;
}

scheduleGridToggle.addEventListener('click', () => setScheduleGridCollapsed(!scheduleGrid.classList.contains('is-collapsed')));

function openScheduleAssignment(resetForm = true) {
  if (!scheduleAssignmentModal) return;
  if (resetForm) createNewRecord();
  setScheduleGridCollapsed(false);
  if (scheduleAssignmentModal.parentElement !== document.body) {
    document.body.appendChild(scheduleAssignmentModal);
  }
  scheduleAssignmentModal.hidden = false;
  document.body.classList.add('schedule-assignment-open');
  requestAnimationFrame(() => {
    $('.schedule-assignment-dialog').focus();
    controllerSearch.focus();
  });
}

function closeScheduleAssignment() {
  if (!scheduleAssignmentModal || scheduleAssignmentModal.hidden) return;
  scheduleAssignmentModal.hidden = true;
  document.body.classList.remove('schedule-assignment-open');
  openScheduleAssignmentButton?.focus();
}

openScheduleAssignmentButton?.addEventListener('click', () => openScheduleAssignment());
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
function filterScheduleTable() {
  const query = normalizeScheduleSearch(scheduleRecordFilter?.value);
  const rows = [...document.querySelectorAll('#schedule-table tbody tr[data-credential]')];
  let visibleCount = 0;
  rows.forEach((row) => {
    const name = row.querySelector('.person-button')?.textContent || '';
    const credential = row.dataset.credential || '';
    const matches = !query || normalizeScheduleSearch(`${name} ${credential}`).includes(query);
    row.hidden = !matches;
    if (matches) visibleCount += 1;
  });
  document.querySelector('#schedule-table tbody .schedule-filter-empty')?.remove();
  if (query && rows.length && visibleCount === 0) {
    $('#schedule-table tbody').insertAdjacentHTML('beforeend', '<tr class="schedule-filter-empty"><td class="empty-state" colspan="40">No hay registros que coincidan con la búsqueda.</td></tr>');
  }
  if (clearScheduleFilter) clearScheduleFilter.hidden = !query;
  if (query) {
    $('#record-count').textContent = `${visibleCount} de ${rows.length} registros`;
  } else {
    $('#record-count').textContent = `${rows.length} ${rows.length === 1 ? 'registro' : 'registros'}`;
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
  if (scheduleFeedback) {
    scheduleFeedback.textContent = message;
    scheduleFeedback.classList.add('is-visible');
    window.setTimeout(() => scheduleFeedback.classList.remove('is-visible'), 3200);
  }
}
function setScheduleFormLoading(isLoading) {
  state.savingRecord = isLoading;
  document.querySelectorAll('.schedule-form-card input, .schedule-form-card select, .schedule-form-card button').forEach((element) => {
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
  saveAssignmentButton.textContent = state.editingDays.size ? 'Guardar edición' : 'Guardar asignación';
}
function setEditModeActionsVisible(visible) {
  if (cancelEditButton) cancelEditButton.hidden = !visible;
}
function setRecordFieldsEnabled(enabled) { controllerName.disabled = !enabled; controllerCredential.disabled = !enabled; controllerSearch.disabled = !enabled; controllerSearch.setAttribute('aria-readonly', String(!enabled)); if (!enabled) setControllerMenuOpen(false); }
function setRouteFieldsEnabled(enabled) { routeSelect.disabled = !enabled; shiftSelect.disabled = !enabled; routeNomenclature.disabled = true; }
function updateRouteFieldsForMode() { setRouteFieldsEnabled(!state.selectedRecord || state.mode === 'work'); }
function finishDayEdit() { state.editingDays.clear(); state.editingSnapshots.clear(); dayEditActions.hidden = true; editingDayLabel.textContent = ''; setEditModeActionsVisible(false); setRecordFieldsEnabled(false); setRouteFieldsEnabled(false); updateSaveAssignmentButton(); }
function markDayForEdit(day) {
  if (!state.selectedRecord || state.editingSnapshots.has(day)) return;
  state.editingDays.add(day);
  state.editingSnapshots.set(day, { assignment: state.assignments[String(day)], detail: state.dailyDetails[String(day)], work: state.work.has(day), rest: state.rest.has(day), vacation: state.vacation.has(day), special: state.specialStates.filter((item) => state.special[item.codigo]?.has(day)).map((item) => item.codigo) });
  saveAssignmentButton.disabled = false;
  updateSaveAssignmentButton();
}
function clearDayAssignment(day) {
  const dayKey = String(day);
  delete state.assignments[dayKey];
  delete state.dailyDetails[dayKey];
  state.work.delete(day);
  state.rest.delete(day);
  state.vacation.delete(day);
  state.specialStates.forEach((item) => state.special[item.codigo]?.delete(day));
  state.editingDays.delete(day);
  state.editingSnapshots.delete(day);
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
function createNewRecord() { finishDayEdit(); state.selectedRecord = null; state.calendarEditingEnabled = true; state.work.clear(); state.rest.clear(); state.vacation.clear(); state.assignments = {}; state.dailyDetails = {}; state.editedDays.clear(); state.specialStates.forEach((item) => state.special[item.codigo]?.clear()); form.reset(); controllerName.value = ''; controllerCredential.value = ''; routeSelect.value = ''; shiftSelect.value = ''; routeNomenclature.value = ''; setRecordFieldsEnabled(true); setRouteFieldsEnabled(true); saveAssignmentButton.disabled = false; $('#code-preview').textContent = '--'; $('#form-message').textContent = 'Listo para crear un nuevo registro.'; renderCalendar(); controllerName.focus(); }
function clearScheduleEditorAfterSave(message) {
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
  $('#code-preview').textContent = '--';
  $('#form-message').textContent = message;
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
    fetch('/api/catalogos/turnos')
  ]);
  if (!controllersResponse.ok || !routesResponse.ok || !shiftsResponse.ok) throw new Error('No se pudieron cargar los catálogos del registro.');
  const [controllers, routes, shifts] = await Promise.all([controllersResponse.json(), routesResponse.json(), shiftsResponse.json()]);
  if (moduleNumber !== activeModuleNumber) return;
  state.controllerCatalog = controllers;
  const activeRoutes = routes.filter((item) => String(item.estado || '').trim().toLowerCase() === 'activo');
  routeOptions.splice(0, routeOptions.length, ...activeRoutes);
  const selectedShiftIds = new Set(JSON.parse(localStorage.getItem(`selected-shifts-${activeModuleNumber}`) || '[]').map(String));
  shiftOptions = shifts.filter((item) => item.activo && selectedShiftIds.has(String(item.id)));
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
    calendar.insertAdjacentHTML('beforeend', `<button type="button" class="day ${status}${edited}" data-day="${day}" title="Haz clic para asignar, editar o cancelar"><b>${day}</b><small>${escapeHtml(label)}</small></button>`);
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

    if (state.selectedRecord && state.mode !== 'work') markDayForEdit(selected);
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
        const accepted = await confirmCodeConflict(selectedCode, selected, controllerCredential.value);
        if (!accepted) return;
      }
      active.add(selected);
      state.assignments[String(selected)] = selectedCode;
      state.dailyDetails[String(selected)] = { route: routeSelect.value, shift: shiftSelect.value, nomenclature: routeNomenclature.value, code: selectedCode };
    }
    renderCalendar();
  }));
  $('#month-label').textContent = `${months[state.month - 1]} ${state.year}`;
  $('#monthly-role-period').textContent = `${months[state.month - 1]} ${state.year}`;
  const specialCount = state.specialStates
    .filter((item) => item.categoria !== 'trabajo')
    .reduce((total, item) => total + (state.special[item.codigo]?.size || 0), 0);
  $('#selection-summary').textContent = `${state.work.size} trabajo · ${state.rest.size} descanso · ${state.vacation.size} vacaciones · ${specialCount} especiales`;
}
function renderTable(records) {
  state.monthRecords = records || [];
  const grouped = [...new Map(records.map((record) => [record.credential, record])).values()];
  const controllerMap = new Map(state.controllerCatalog.map((controller) => [controller.credencial, controller]));
  $('#record-count').textContent = `${grouped.length} ${grouped.length === 1 ? 'registro' : 'registros'}`;
  $('#schedule-table thead').innerHTML = `<tr><th>Nombre</th><th>Cred.</th>${Array.from({length: daysInMonth()}, (_, i) => { const day = i + 1; const initial = ['D', 'L', 'M', 'M', 'J', 'V', 'S'][new Date(state.year, state.month - 1, day).getDay()]; return `<th class="schedule-day-header"><span class="schedule-day-number">${day}</span><span class="schedule-day-initial">${initial}</span></th>`; }).join('')}</tr>`;
  $('#schedule-table tbody').innerHTML = grouped.length ? grouped.map((record) => {
    const controller = controllerMap.get(record.credential);
    const displayName = controller?.nombre || record.name;
    const assignments = record.daily_assignments || {}; const details = record.daily_details || {}; const work = new Set(record.work_days || []); const rest = new Set(record.rest_days || []);
    const cells = Array.from({length: daysInMonth()}, (_, i) => { const day = i + 1; const detail = details[String(day)]; const code = detail?.code || assignments[String(day)]; const custom = detail ? ' table-custom' : ''; const edited = state.lastEditedDay === day ? ' table-edited-last' : ''; const category = state.specialStates.find((item) => item.codigo === code)?.categoria; if (code === 'V' || category === 'vacaciones') return `<td class="table-vacation${custom}${edited}">V</td>`; if (category === 'trabajo') return `<td class="table-work${custom}${edited}">${escapeHtml(code)}</td>`; if (category === 'descanso') return `<td class="table-rest${custom}${edited}">${escapeHtml(code)}</td>`; if (category === 'falta') return `<td class="table-absence${custom}${edited}">${escapeHtml(code)}</td>`; if (category === 'incapacidad') return `<td class="table-incapacity${custom}${edited}">${escapeHtml(code)}</td>`; if (code === 'MD') return `<td class="table-work${custom}${edited}">MD</td>`; if (code && !/^[A-Z]+\d+$/.test(code)) return `<td class="table-special${custom}${edited}">${escapeHtml(code)}</td>`; if (code) return `<td class="table-work${custom}${edited}">${escapeHtml(code)}</td>`; if (work.has(day)) return `<td class="table-work${custom}${edited}">${escapeHtml(record.nomenclature)}${escapeHtml(record.shift)}</td>`; if (rest.has(day)) return `<td class="table-rest${custom}${edited}">D</td>`; return '<td></td>'; }).join('');
    const disabled = monthIsClosed() ? ' disabled' : '';
    return `<tr data-credential="${escapeHtml(record.credential)}"><td class="name-cell"><div class="person-meta"><button class="person-button" type="button" data-credential="${escapeHtml(record.credential)}">${escapeHtml(displayName)}</button></div><div class="table-row-actions"><button class="table-update-button" type="button" data-credential="${escapeHtml(record.credential)}" title="Editar registro de ${escapeHtml(displayName)}"${disabled}>Editar</button><button class="table-delete-button" type="button" data-credential="${escapeHtml(record.credential)}" title="Eliminar registro de ${escapeHtml(displayName)}"${disabled}>Eliminar</button></div></td><td>${escapeHtml(record.credential)}</td>${cells}</tr>`;
  }).join('') : '<tr><td class="empty-state" colspan="40">No hay registros para este mes.</td></tr>';
  filterScheduleTable();
  document.querySelectorAll('.person-button').forEach((button) => button.addEventListener('click', () => selectRecord(grouped.find((item) => item.credential === button.dataset.credential))));
  document.querySelectorAll('.table-update-button:not(:disabled)').forEach((button) => button.addEventListener('click', () => {
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
      $('#form-message').classList.remove('error');
      $('#form-message').textContent = result.deleted ? `Registro de ${credential} eliminado.` : 'No se encontró el registro para eliminar.';
      if (result.deleted) {
        state.selectedRecord = null;
        createNewRecord();
        await loadRecords();
        showScheduleFeedback('Asignación eliminada');
      }
    } catch (error) {
      $('#form-message').textContent = error.message;
      $('#form-message').classList.add('error');
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
    if (moduleNumber === activeModuleNumber) $('#form-message').textContent = error.message;
  }
}
async function changeMonth(delta) { finishDayEdit(); state.month += delta; if (state.month === 0) { state.month = 12; state.year -= 1; } if (state.month === 13) { state.month = 1; state.year += 1; } state.work.clear(); state.rest.clear(); state.vacation.clear(); state.assignments = {}; state.dailyDetails = {}; state.editedDays.clear(); await loadMonthStatus(); renderCalendar(); loadRecords(); }
function selectRecord(record) {
  if (!record) return;
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
  $('#form-message').textContent = `Registro de ${record.name} seleccionado.`;
  updateCalendarLock();
  renderCalendar();
  document.querySelector('.schedule-form-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function editCalendarDay(day) {
  if (!state.selectedRecord || !dayHasAssignment(day)) {
    $('#form-message').textContent = 'Selecciona primero una persona del rol mensual.';
    return;
  }
  const dayKey = String(day);
  const assignment = state.assignments[dayKey];
  const specialState = state.specialStates.find((item) => item.codigo === assignment);
  const isRouteCode = /^[A-Z]+\d+$/.test(assignment || '');
  if (assignment === 'MD') {
    markDayForEdit(day);
    state.mode = 'md';
    document.querySelectorAll('.mode-button').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.mode === 'md');
    });
    updateRouteFieldsForMode();
    $('#form-message').textContent = `Día ${day} seleccionado como Módulo (MD). Guarda la edición para conservar la asignación.`;
    renderCalendar();
    return;
  }
  const isWorkAssignment = Boolean(state.dailyDetails[dayKey] && !specialState)
    || (state.work.has(day) && !specialState && (!assignment || isRouteCode));
  if (!isWorkAssignment) {
    markDayForEdit(day);
    const mode = assignment === 'V' || specialState?.categoria === 'vacaciones'
      ? 'vacation'
      : specialState
        ? specialState.codigo
        : 'rest';
    state.mode = mode;
    document.querySelectorAll('.mode-button').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.mode === mode);
    });
    updateRouteFieldsForMode();
    $('#form-message').textContent = `Día ${day} seleccionado con el estado ${specialState?.descripcion || (mode === 'vacation' ? 'Vacaciones' : 'Descanso')}. Selecciona otro estado si deseas cambiarlo y guarda la edición.`;
    renderCalendar();
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
  state.dailyDetails[String(day)] = { route, shift, nomenclature, code };
  state.assignments[String(day)] = code;
  state.work.add(day);
  state.rest.delete(day);
  state.vacation.delete(day);
  state.specialStates.forEach((item) => state.special[item.codigo]?.delete(day));
  markLastEditedDay(day);
  $('#form-message').textContent = `Día ${day} preparado con el código ${code}. Presiona Guardar asignación para confirmar.`;
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
  if (!state.editingDays.size) finishDayEdit(); else { dayEditActions.hidden = true; editingDayLabel.textContent = ''; updateSaveAssignmentButton(); }
  renderCalendar();
}
cancelEditButton?.addEventListener('click', () => {
  cancelDayEdit();
  finishDayEdit();
  state.calendarEditingEnabled = false;
  saveAssignmentButton.disabled = true;
  setEditModeActionsVisible(false);
  updateCalendarLock();
  $('#form-message').textContent = 'Edición cancelada';
  renderCalendar();
});
$('#previous-month').addEventListener('click', () => changeMonth(-1)); $('#next-month').addEventListener('click', () => changeMonth(1)); $('#clear-days').addEventListener('click', () => { finishDayEdit(); state.work.clear(); state.rest.clear(); state.vacation.clear(); state.assignments = {}; state.dailyDetails = {}; state.editedDays.clear(); state.lastEditedDay = null; state.specialStates.forEach((item) => state.special[item.codigo]?.clear()); renderCalendar(); });
$('#create-record').addEventListener('click', createNewRecord);
scheduleRecordFilter?.addEventListener('input', filterScheduleTable);
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
    $('#form-message').textContent = error.message;
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
async function saveRecord(extra = {}) { const base = state.selectedRecord || {}; const credential = controllerCredential.value || base.credential; const forceUpdate = Boolean(state.selectedRecord && state.selectedRecord.credential === credential); const payload = { name: controllerName.value || base.name, credential, route: routeSelect.value || base.route, shift: shiftSelect.value || base.shift, nomenclature: routeNomenclature.value || base.nomenclature, month: state.month, year: state.year, module_number: activeModuleNumber, work_days: [...state.work], rest_days: [...state.rest], vacation_days: [...state.vacation], daily_assignments: { ...state.assignments }, daily_details: { ...state.dailyDetails }, force_update: forceUpdate, ...extra }; const response = await fetch('/api/records', { method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'}, body: JSON.stringify(payload) }); return readJsonResponse(response, 'No se pudo guardar.'); }
async function saveAllRecords() {
  if (monthIsClosed()) { $('#form-message').textContent = 'El mes seleccionado ya terminó y no permite modificaciones.'; return; }
  setLoadingButton(saveAllRecordsButton, true, 'Guardando...');
  showLoader('Guardando asignaciones...');
  try {
    const response = await fetch('/api/records/save-all', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ month: state.month, year: state.year, module_number: activeModuleNumber, records: state.monthRecords }) });
    const result = await readJsonResponse(response, 'No se pudieron guardar los registros.');
    $('#form-message').classList.remove('error');
    $('#form-message').textContent = `${result.saved_count} registro${result.saved_count === 1 ? '' : 's'} guardado${result.saved_count === 1 ? '' : 's'} correctamente.`;
    showScheduleFeedback('Asignaciones guardadas');
  } catch (error) {
    $('#form-message').textContent = error.message;
    $('#form-message').classList.add('error');
  } finally {
    setLoadingButton(saveAllRecordsButton, false, 'Guardado');
    hideLoader();
  }
}
saveAllRecordsButton.addEventListener('click', saveAllRecords);
document.querySelector('#activate-month')?.addEventListener('click', async function () {
  const activate = !state.monthActivated;
  const bodyData = new URLSearchParams({ month: String(state.month), year: String(state.year), activo: String(activate) });
  try {
    const response = await fetch(`/administrador/rol-mensual/${activeModuleNumber}/estado`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: bodyData });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'No se pudo cambiar el estado del mes.');
    state.monthActivated = Boolean(result.activo);
    $('#form-message').classList.remove('error');
    updateMonthEditability();
    renderTable(state.monthRecords);
    document.dispatchEvent(new CustomEvent('admin-month-status-updated', {
      detail: { active: state.monthActivated }
    }));
  } catch (error) {
    $('#form-message').textContent = error.message;
    $('#form-message').classList.add('error');
  }
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (monthIsClosed()) { $('#form-message').textContent = 'El mes seleccionado ya terminó y no permite modificaciones.'; return; }
  const hasEditingDays = state.editingDays.size > 0;
  if (hasEditingDays && [...state.editingDays].some((day) => {
    const code = state.assignments[String(day)];
    const category = state.specialStates.find((item) => item.codigo === code)?.categoria;
    return state.work.has(day)
      && code !== 'MD'
      && category !== 'trabajo'
      && (!state.dailyDetails[String(day)]?.route || !state.dailyDetails[String(day)]?.shift);
  })) {
    $('#form-message').textContent = 'Selecciona una ruta y un turno para los días de trabajo editados.';
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
          const accepted = await confirmCodeConflict(detail.code, day, controllerCredential.value || state.selectedRecord?.credential);
          if (!accepted) return;
        }
      }
    }
    setScheduleFormLoading(true);
    setLoadingButton(saveAssignmentButton, true, loadingLabel);
    showLoader(loadingLabel);
    await waitForLoadingPaint();
    const savedCredential = String(controllerCredential.value || state.selectedRecord?.credential || '').trim();
    const saved = await saveRecord();
    const feedbackMessage = wasUpdating ? 'Asignación actualizada' : 'Asignación guardada';
    savedSuccessfully = true;
    state.selectedRecord = saved;
    $('#form-message').classList.remove('error');
    if (hasEditingDays) {
      finishDayEdit();
      state.calendarEditingEnabled = false;
      $('#form-message').textContent = `${selectedDays.length} día${selectedDays.length === 1 ? '' : 's'} actualizado${selectedDays.length === 1 ? '' : 's'}.`;
    } else {
      state.lastEditedDay = null;
      state.editedDays = new Set();
      $('#form-message').textContent = 'Asignación guardada.';
    }
    renderCalendar();
    await loadRecords();
    showScheduleFeedback(feedbackMessage, savedCredential);
  } catch (error) {
    $('#form-message').textContent = error.message;
    $('#form-message').classList.add('error');
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
  activeModuleNumber = String(moduleNumber || '');
  body.dataset.module = activeModuleNumber;
  initializedModuleNumber = activeModuleNumber;
  const loadVersion = ++moduleLoadVersion;
  if (scheduleAssignmentModal && !scheduleAssignmentModal.hidden) closeScheduleAssignment();
  finishDayEdit();
  state.selectedRecord = null;
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
  $('#form-message').textContent = '';
  renderTable([]);
  try {
    await Promise.all([loadScheduleCatalogs(activeModuleNumber), loadSpecialStates(), loadMonthStatus(activeModuleNumber)]);
    if (loadVersion !== moduleLoadVersion) return;
    await loadRecords(activeModuleNumber);
    if (loadVersion !== moduleLoadVersion) return;
    renderCalendar();
  } catch (error) {
    if (loadVersion === moduleLoadVersion) $('#form-message').textContent = error.message;
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
