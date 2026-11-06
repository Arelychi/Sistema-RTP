document.addEventListener('DOMContentLoaded', function () {
  const toast = document.querySelector('[data-admin-toast]');
  if (!toast) return;

  const title = toast.querySelector('[data-admin-toast-title]');
  const message = toast.querySelector('[data-admin-toast-message]');
  const icon = toast.querySelector('[data-admin-toast-icon]');
  let hideTimer = 0;

  function showNotification(notificationTitle, notificationMessage, type) {
    if (!notificationTitle || !notificationMessage) return;
    window.clearTimeout(hideTimer);
    title.textContent = notificationTitle;
    message.textContent = notificationMessage;
    toast.dataset.type = type || 'info';
    icon.textContent = type === 'success' ? '✓' : type === 'error' ? '!' : 'i';
    toast.hidden = false;
    requestAnimationFrame(function () {
      toast.classList.add('is-visible');
    });
    hideTimer = window.setTimeout(function () {
      toast.classList.remove('is-visible');
      window.setTimeout(function () {
        if (!toast.classList.contains('is-visible')) toast.hidden = true;
      }, 100);
    }, 1500);
  }

  function activeSectionName() {
    const activeLink = document.querySelector('.admin-sidebar nav .admin-nav-section.active');
    if (activeLink) return activeLink.textContent.trim().replace(/\s+/g, ' ');

    const pageHeading = document.querySelector('.admin-controller-page-header .admin-page-tab-label, .admin-registry-page-header .admin-page-tab-label');
    return pageHeading?.textContent.trim().replace(/\s+/g, ' ') || 'Administración';
  }

  document.addEventListener('admin-module-changed', function (event) {
    if (!event.detail?.changed) return;
    const moduleId = String(event.detail?.moduleId || '');
    const moduleTab = Array.from(document.querySelectorAll('[data-admin-module]'))
      .find((tab) => tab.dataset.adminModule === moduleId);
    const moduleName = moduleTab?.textContent.trim() || `Módulo ${moduleId}`;
    showNotification('NAVEGACIÓN', `${activeSectionName()}: ${moduleName}`, 'info');
  });

  document.addEventListener('click', function (event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    const moduleEditButton = target.closest('.module-edit-button');
    if (moduleEditButton) {
      showNotification('EDICIÓN', `Editando módulo: ${moduleEditButton.dataset.moduleName || ''}`, 'info');
    }

    const editLink = target.closest('a[data-admin-edit-trigger], a.admin-edit-button[href]');
    if (editLink && editLink.href) {
      try {
        sessionStorage.setItem('adminPendingNotification', JSON.stringify({
          title: 'EDICIÓN',
          message: `Abriendo edición: ${editLink.getAttribute('aria-label') || editLink.textContent.trim() || 'registro'}`,
          type: 'info'
        }));
      } catch (error) {
        console.warn('No se pudo guardar la notificación de edición.', error);
      }
    }
  });

  document.querySelectorAll('.admin-alert').forEach(function (alert, index) {
    const type = alert.classList.contains('admin-alert-error') ? 'error' : 'success';
    window.setTimeout(function () {
      showNotification(type === 'error' ? 'ERROR' : 'ÉXITO', alert.textContent.trim(), type);
    }, index * 4500);
  });
  const flashAlerts = document.querySelectorAll('.admin-alert');
  document.querySelectorAll('.admin-alerts').forEach(function (alerts) {
    alerts.hidden = true;
  });

  let hasPendingNotification = false;
  try {
    const pendingNotification = sessionStorage.getItem('adminPendingNotification');
    if (pendingNotification) {
      sessionStorage.removeItem('adminPendingNotification');
      const notification = JSON.parse(pendingNotification);
      showNotification(notification.title, notification.message, notification.type);
      hasPendingNotification = true;
    }
  } catch (error) {
    console.warn('No se pudo recuperar la notificación pendiente.', error);
  }

  const activeModule = document.querySelector('.admin-module-tab.active');
  if (activeModule && !hasPendingNotification) {
    window.setTimeout(function () {
      showNotification('NAVEGACIÓN', `${activeSectionName()}: ${activeModule.textContent.trim()}`, 'info');
    }, flashAlerts.length * 4500);
  }

  const scheduleFeedback = document.querySelector('#schedule-feedback');
  if (scheduleFeedback) {
    const observer = new MutationObserver(function () {
      const feedbackMessage = scheduleFeedback.textContent.trim();
      if (feedbackMessage && scheduleFeedback.classList.contains('is-visible')) {
        showNotification('ÉXITO', feedbackMessage, 'success');
      }
    });
    observer.observe(scheduleFeedback, { childList: true, characterData: true, subtree: true, attributes: true });
  }

  const scheduleFormMessage = document.querySelector('#form-message');
  if (scheduleFormMessage) {
    const observer = new MutationObserver(function () {
      const errorMessage = scheduleFormMessage.textContent.trim();
      if (errorMessage && scheduleFormMessage.classList.contains('error')) {
        showNotification('ERROR', errorMessage, 'error');
      }
    });
    observer.observe(scheduleFormMessage, { childList: true, characterData: true, subtree: true, attributes: true });
  }

  document.addEventListener('admin-month-status-updated', function (event) {
    const active = Boolean(event.detail?.active);
    const status = active ? 'activado' : 'desactivado';
    showNotification('ÉXITO', `Mes ${status} correctamente.`, 'success');
  });
});
