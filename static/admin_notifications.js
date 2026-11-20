document.addEventListener('DOMContentLoaded', function () {
  const notification = document.querySelector('[data-admin-action-notification]');
  if (!notification) return;

  const message = notification.querySelector('[data-admin-action-notification-message]');
  const icon = notification.querySelector('[data-admin-action-notification-icon]');
  let hideTimer = 0;
  let removeTimer = 0;

  function showNotification(notificationMessage, type) {
    const text = String(notificationMessage || '').trim();
    if (!text) return;

    window.clearTimeout(hideTimer);
    window.clearTimeout(removeTimer);
    message.textContent = text;
    notification.dataset.type = type || 'success';
    icon.textContent = type === 'error' ? '!' : type === 'delete' ? '🞪' : type === 'edit' ? '🖍' : type === 'module' ? '↔' : '✓';
    notification.hidden = false;
    requestAnimationFrame(function () {
      notification.classList.add('is-visible');
    });
    hideTimer = window.setTimeout(function () {
      notification.classList.remove('is-visible');
      removeTimer = window.setTimeout(function () {
        if (!notification.classList.contains('is-visible')) notification.hidden = true;
      }, 250);
    }, 2800);
  }

  function activeSectionName() {
    const activeLink = document.querySelector('.admin-sidebar nav .admin-nav-section.active');
    if (activeLink) return activeLink.textContent.trim().replace(/\s+/g, ' ');

    const pageHeading = document.querySelector('.admin-controller-page-header .admin-page-tab-label, .admin-registry-page-header .admin-page-tab-label');
    return pageHeading?.textContent.trim().replace(/\s+/g, ' ') || 'Administración';
  }

  function notificationType(messageText, category) {
    if (category === 'error') return 'error';
    const normalized = messageText.toLocaleLowerCase('es');
    if (/elimin|borr|desvincul|vaciad|quitad/.test(normalized)) return 'delete';
    if (/actualiz|editad/.test(normalized)) return 'edit';
    return 'success';
  }

  document.addEventListener('admin-module-changed', function (event) {
    if (!event.detail?.changed) return;
    const moduleId = String(event.detail?.moduleId || '');
    const moduleTab = Array.from(document.querySelectorAll('[data-admin-module]'))
      .find((tab) => tab.dataset.adminModule === moduleId);
    const moduleName = moduleTab?.textContent.trim() || `Módulo ${moduleId}`;
    showNotification(`${activeSectionName()}: ${moduleName}`, 'module');
  });

  document.addEventListener('admin-action-notification', function (event) {
    showNotification(event.detail?.message, event.detail?.type);
  });

  const flashAlerts = Array.from(document.querySelectorAll('.admin-alert'));
  flashAlerts.forEach(function (alert, index) {
    const alertMessage = alert.textContent.trim();
    const category = alert.classList.contains('admin-alert-error') ? 'error' : 'success';
    window.setTimeout(function () {
      showNotification(alertMessage, notificationType(alertMessage, category));
    }, index * 3100);
  });
  document.querySelectorAll('.admin-alerts').forEach(function (alerts) {
    alerts.hidden = true;
  });

  const scheduleFeedback = document.querySelector('#schedule-feedback');
  if (scheduleFeedback) {
    const observer = new MutationObserver(function () {
      const feedbackMessage = scheduleFeedback.textContent.trim();
      if (feedbackMessage && scheduleFeedback.classList.contains('is-visible')) {
        showNotification(feedbackMessage, notificationType(feedbackMessage, 'success'));
      }
    });
    observer.observe(scheduleFeedback, { childList: true, characterData: true, subtree: true, attributes: true });
  }

  const scheduleFormMessage = document.querySelector('#form-message');
  if (scheduleFormMessage) {
    const observer = new MutationObserver(function () {
      const errorMessage = scheduleFormMessage.textContent.trim();
      if (errorMessage && scheduleFormMessage.classList.contains('error')) {
        showNotification(errorMessage, 'error');
      }
    });
    observer.observe(scheduleFormMessage, { childList: true, characterData: true, subtree: true, attributes: true });
  }

  document.addEventListener('admin-month-status-updated', function (event) {
    const active = Boolean(event.detail?.active);
    const status = active ? 'activado' : 'desactivado';
    showNotification(`Mes ${status} correctamente.`, 'success');
  });
});
