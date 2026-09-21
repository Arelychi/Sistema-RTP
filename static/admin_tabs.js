document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.admin-registry-tabs').forEach(function (carousel) {
    const viewport = carousel.querySelector('.admin-registry-tabs-viewport');
    const track = carousel.querySelector('.admin-registry-tabs-track');
    const previous = carousel.querySelector('[data-registry-prev]');
    const next = carousel.querySelector('[data-registry-next]');
    const tabs = carousel.querySelectorAll('.admin-registry-tab');

    if (!viewport || !track || !previous || !next) {
      return;
    }

    const updateDimensions = function () {
      const gap = 10;
      const tabWidth = Math.max(110, (viewport.clientWidth - gap * 6) / 7);
      tabs.forEach(function (tab) {
        tab.style.flexBasis = `${tabWidth}px`;
      });
    };

    const updateArrows = function () {
      const canGoBack = viewport.scrollLeft > 2;
      const canGoNext = viewport.scrollLeft + viewport.clientWidth < viewport.scrollWidth - 2;
      previous.disabled = !canGoBack;
      next.disabled = !canGoNext;
      previous.hidden = !canGoBack && !canGoNext;
      next.hidden = !canGoBack && !canGoNext;
    };

    previous.addEventListener('click', function () {
      viewport.scrollBy({ left: -viewport.clientWidth, behavior: 'smooth' });
    });

    next.addEventListener('click', function () {
      viewport.scrollBy({ left: viewport.clientWidth, behavior: 'smooth' });
    });

    viewport.addEventListener('scroll', updateArrows, { passive: true });
    window.addEventListener('resize', function () {
      updateDimensions();
      updateArrows();
    });
    updateDimensions();
    updateArrows();
  });
});
