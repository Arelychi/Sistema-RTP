document.addEventListener('DOMContentLoaded', function () {
  const tabs = document.querySelectorAll('[data-admin-module-tabs]');
  if (!tabs.length) return;

  const storageKey = 'adminSelectedModule';
  const queryModule = new URLSearchParams(window.location.search).get('module_number');
  const availableModules = Array.from(document.querySelectorAll('[data-admin-module]'))
    .map((tab) => tab.dataset.adminModule)
    .filter((value, index, values) => value && values.indexOf(value) === index);
  const storedModule = localStorage.getItem(storageKey);
  const moduleColors = {
    '1': '#027a35',
    '2': '#f08217',
    '3': '#d72f89',
    '4': '#00A19A',
    '5': '#fdc60a',
    '6': '#266cb4',
    '7': '#e5074c'
  };
  let selectedModule = availableModules.includes(queryModule)
    ? queryModule
    : availableModules.includes(storedModule) ? storedModule : availableModules[0];

  function updateHeaderModuleIndicator() {
    const selectedTab = document.querySelector(`[data-admin-module="${CSS.escape(selectedModule)}"]`);
    if (!selectedTab) return;

    const moduleName = selectedTab.textContent.trim();
    const moduleColor = moduleColors[selectedModule] || '#183b59';
    document.querySelectorAll('.admin-header').forEach(function (header) {
      let indicator = header.querySelector('[data-admin-module-indicator]');
      if (!indicator) {
        indicator = document.createElement('div');
        indicator.className = 'admin-header-module';
        indicator.dataset.adminModuleIndicator = '';
        indicator.setAttribute('aria-live', 'polite');
        const connection = header.querySelector('.admin-connection');
        header.insertBefore(indicator, connection || null);
      }
      indicator.textContent = moduleName;
      indicator.style.setProperty('--admin-module-color', moduleColor);
      indicator.setAttribute('aria-label', `Módulo activo: ${moduleName}`);
    });
  }

  function updateModuleView() {
    localStorage.setItem(storageKey, selectedModule);
    document.querySelectorAll('[data-admin-module]').forEach(function (tab) {
      const active = tab.dataset.adminModule === selectedModule;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('[data-admin-module-panel]').forEach(function (panel) {
      panel.hidden = panel.dataset.adminModulePanel !== selectedModule;
      panel.classList.toggle('active', !panel.hidden);
    });
    document.querySelectorAll('select[name="mod1"]').forEach(function (select) {
      if (Array.from(select.options).some((option) => option.value === selectedModule)) {
        select.value = selectedModule;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    document.querySelectorAll('[data-admin-module-link]').forEach(function (link) {
      const url = new URL(link.href, window.location.origin);
      url.searchParams.set('module_number', selectedModule);
      link.href = url.toString();
    });
    updateHeaderModuleIndicator();
  }

  function selectModule(moduleNumber, navigate) {
    if (!availableModules.includes(moduleNumber)) return;
    selectedModule = moduleNumber;
    updateModuleView();
    if (navigate) {
      const url = new URL(window.location.href);
      url.searchParams.set('module_number', selectedModule);
      history.replaceState(null, '', url);
    }
  }

  document.querySelectorAll('[data-admin-module]').forEach(function (tab) {
    tab.addEventListener('click', function () {
      selectModule(this.dataset.adminModule, true);
    });
  });

  tabs.forEach(function (bar) {
    const viewport = bar.querySelector('.admin-module-tabs-viewport');
    const previous = bar.querySelector('[data-admin-module-prev]');
    const next = bar.querySelector('[data-admin-module-next]');
    if (!viewport || !previous || !next) return;

    const moduleTabs = bar.querySelectorAll('[data-admin-module]');
    const updateTabDimensions = function () {
      const gap = 10;
      const tabWidth = Math.max(110, (viewport.clientWidth - gap * 6) / 7);
      moduleTabs.forEach(function (moduleTab) {
        moduleTab.style.setProperty('--admin-module-tab-width', `${tabWidth}px`);
      });
    };

    previous.addEventListener('click', () => viewport.scrollBy({ left: -viewport.clientWidth, behavior: 'smooth' }));
    next.addEventListener('click', () => viewport.scrollBy({ left: viewport.clientWidth, behavior: 'smooth' }));
    window.addEventListener('resize', updateTabDimensions);
    if (window.ResizeObserver) {
      new ResizeObserver(updateTabDimensions).observe(viewport);
    }
    updateTabDimensions();
  });

  selectModule(selectedModule, false);
});
