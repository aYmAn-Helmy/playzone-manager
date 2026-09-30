(() => {
  const tabletQuery = window.matchMedia('(max-width: 1100px)');
  const handsetQuery = window.matchMedia('(max-width: 768px)');
  const privacyKey = 'playzone_dashboard_private_hidden';
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

  function privacyIcon(hidden) {
    return hidden
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18M10.6 10.7a2 2 0 0 0 2.7 2.7M9.9 4.2A10.8 10.8 0 0 1 12 4c5.5 0 9 5 9 5a16.8 16.8 0 0 1-3.1 3.7M6.6 6.6C4.3 8 3 10 3 10s3.5 5 9 5c1 0 2-.2 2.8-.5"/></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12s3.5-5 9-5 9 5 9 5-3.5 5-9 5-9-5-9-5Z"/><circle cx="12" cy="12" r="2.5"/></svg>';
  }

  function applyPrivacy(hidden) {
    document.querySelectorAll('.stats .stat').forEach((stat) => {
      const label = stat.querySelector('span')?.textContent.trim() || '';
      const privateStat = label === 'إجمالي الإيرادات اليوم' || label === 'ساعات اللعب اليوم';
      stat.classList.toggle('pz-private-stat', privateStat);
      stat.classList.toggle('pz-private-stat-hidden', privateStat && hidden);
    });

    document.querySelectorAll('.pz-privacy-toggle').forEach((button) => {
      button.classList.toggle('is-hidden', hidden);
      button.innerHTML = privacyIcon(hidden);
      button.setAttribute('aria-label', hidden ? 'إظهار الإيرادات وساعات اللعب' : 'إخفاء الإيرادات وساعات اللعب');
      button.setAttribute('title', hidden ? 'إظهار التفاصيل' : 'إخفاء التفاصيل');
    });
  }

  function ensurePrivacyToggle() {
    document.querySelectorAll('.stats').forEach((stats) => {
      const labels = [...stats.querySelectorAll('.stat span')].map((span) => span.textContent.trim());
      if (!labels.includes('إجمالي الإيرادات اليوم') && !labels.includes('ساعات اللعب اليوم')) return;

      let button = stats.querySelector(':scope > .pz-privacy-toggle');
      if (!button) {
        button = document.createElement('button');
        button.type = 'button';
        button.className = 'pz-privacy-toggle';
        button.addEventListener('click', () => {
          const next = localStorage.getItem(privacyKey) !== '1';
          localStorage.setItem(privacyKey, next ? '1' : '0');
          applyPrivacy(next);
        });
        stats.prepend(button);
      }
    });
    applyPrivacy(localStorage.getItem(privacyKey) === '1');
  }

  function closeVoltraConsole() {
    document.getElementById('pz-voltra-console')?.remove();
  }

  function toggleVoltraConsole(anchor) {
    const existing = document.getElementById('pz-voltra-console');
    if (existing) {
      existing.remove();
      return;
    }

    const host = anchor.closest('.content-section') || anchor.closest('section') || anchor.parentElement;
    if (!host) return;

    const panel = document.createElement('section');
    panel.id = 'pz-voltra-console';
    panel.className = 'content-section pz-voltra-console';
    panel.innerHTML = `
      <div class="pz-voltra-console-head">
        <div>
          <h2>لوحة Voltra داخل PlayZone</h2>
          <p>إدارة المشتركات والربط والطاقة بدون فتح متصفح أو نافذة خارجية.</p>
        </div>
        <button type="button" class="button ghost pz-voltra-console-close">إغلاق اللوحة</button>
      </div>
      <iframe
        class="pz-voltra-console-frame"
        src="/voltra-console"
        title="Voltra Power Manager"
        loading="eager"
      ></iframe>
    `;
    panel.querySelector('.pz-voltra-console-close')?.addEventListener('click', closeVoltraConsole);
    host.insertAdjacentElement('afterend', panel);
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function ensureVoltraEmbed() {
    const anchor = document.querySelector('a.button.ghost[href="http://127.0.0.1:8086/voltra"]');
    if (!anchor) {
      if (!document.querySelector('.sidebar .nav-item.selected')?.textContent.includes('Voltra')) {
        closeVoltraConsole();
      }
      return;
    }
    if (anchor.dataset.pzEmbedded === '1') return;

    anchor.dataset.pzEmbedded = '1';
    anchor.removeAttribute('target');
    anchor.removeAttribute('rel');
    anchor.setAttribute('href', '#voltra-console');
    anchor.textContent = 'لوحة Voltra';
    anchor.addEventListener('click', (event) => {
      event.preventDefault();
      toggleVoltraConsole(anchor);
    });
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
    ensurePrivacyToggle();
    ensureVoltraEmbed();
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
    if (event.key === 'Escape') {
      closeDrawer();
      closeVoltraConsole();
    }
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
