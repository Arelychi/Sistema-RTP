document.addEventListener('DOMContentLoaded', function () {
  const modal = document.querySelector('#controller-delete-modal');
  if (!modal) return;

  const title = modal.querySelector('#controller-delete-title');
  const message = modal.querySelector('#controller-delete-message');
  const confirmButton = modal.querySelector('[data-controller-delete-confirm]');
  const cancelButtons = modal.querySelectorAll('[data-controller-delete-cancel]');
  let pendingForm = null;
  let trigger = null;
  let confirmedForm = null;

  function closeModal() {
    modal.hidden = true;
    pendingForm = null;
    trigger?.focus();
    trigger = null;
  }

  document.querySelectorAll('[data-delete-confirm-form]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (confirmedForm === form) {
        confirmedForm = null;
        return;
      }

      event.preventDefault();
      const kind = form.dataset.deleteKind || 'registro';
      const name = form.dataset.deleteName || '';
      pendingForm = form;
      trigger = event.submitter || form.querySelector('button[type="submit"]');
      if (title) title.textContent = `¿Eliminar ${kind}?`;
      if (message) {
        message.textContent = form.dataset.deleteMessage
          || `Se eliminará ${name || kind}. Esta acción no se puede deshacer.`;
      }
      modal.hidden = false;
      confirmButton?.focus();
    });
  });

  cancelButtons.forEach((button) => button.addEventListener('click', closeModal));
  confirmButton?.addEventListener('click', function () {
    const form = pendingForm;
    if (!form) return;
    pendingForm = null;
    modal.hidden = true;
    confirmedForm = form;
    form.requestSubmit();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !modal.hidden) closeModal();
  });
});
