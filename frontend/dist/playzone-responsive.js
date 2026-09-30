(() => {
  const tabletQuery = window.matchMedia('(max-width: 1100px)');
  const handsetQuery = window.matchMedia('(max-width: 768px)');
  let framePending = false;

  function closeDrawer() {
    document.body?.classList.remove('pz-sidebar-open');
  }

  function toggleDrawer() {
    document.body?.classList.toggle('pz-sidebar-open');
  }

  function ensureChrome() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;

    sidebar.classList.add('pz-auto-sidebar');
    sidebar.id = 'pz-main-sidebar';

    let button = document.getElementById('pz-mobile-menu');
    if (!button) {
      button = document.createElement('button');
      button.id = 'pz-mobile-menu';
      button.type = 'button';
      button.className = 'pz-mobile-menu icon-button';
      button.setAttribute('aria-label', 'فتح القائمة الرئيسية');
      button.setAttribute('aria-controls', 'pz-main-sidebar');
      button.innerHTML = '<span aria-hidden="true">☰</span>';
      button.addEventListener('click', toggleDrawer);
      document.body.appendChild(button);
    }

    let shade = document.getElementById('pz-mobile-sidebar-backdrop');
    if (!shade) {
      shade = document.createElement('div');
      shade.id = 'pz-mobile-sidebar-backdrop';
      shade.setAttribute('aria-hidden', 'true');
      shade.addEventListener('click', closeDrawer);
      document.body.appendChild(shade);
    }
  }

  function annotateTables() {
    document.querySelectorAll('.table-scroll table, .content-section table').forEach((table) => {
      table.classList.add('pz-responsive-table');
      const heads = [...table.querySelectorAll('thead th')].map((th) => th.textContent.trim());
      if (!heads.length) return;
      table.querySelectorAll('tbody tr').forEach((row) => {
        [...row.children].forEach((cell, index) => {
          if (cell.tagName === 'TD' && !cell.dataset.label) {
            cell.dataset.label = heads[index] || '';
          }
        });
      });
    });
  }

  function applyResponsiveState() {
    if (!document.body) return;
    document.body.classList.toggle('pz-mobile-layout', tabletQuery.matches);
    document.body.classList.toggle('pz-handset-layout', handsetQuery.matches);
    if (!tabletQuery.matches) closeDrawer();
    ensureChrome();
    annotateTables();
  }

  function schedule() {
    if (framePending) return;
    framePending = true;
    requestAnimationFrame(() => {
      framePending = false;
      applyResponsiveState();
    });
  }

  document.addEventListener('click', (event) => {
    if (!tabletQuery.matches) return;
    if (event.target.closest('.sidebar .nav-item')) closeDrawer();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeDrawer();
  });

  tabletQuery.addEventListener?.('change', schedule);
  handsetQuery.addEventListener?.('change', schedule);
  window.addEventListener('orientationchange', schedule);
  window.addEventListener('resize', schedule, { passive: true });

  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', schedule, { once: true });
  } else {
    schedule();
  }
})();
