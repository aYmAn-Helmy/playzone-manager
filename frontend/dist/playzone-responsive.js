(() => {
  const tabletQuery = window.matchMedia('(max-width: 1100px)');
  const handsetQuery = window.matchMedia('(max-width: 768px)');
  const privacyKey = 'playzone_dashboard_private_hidden';
  const privateLabels = new Set(['إجمالي الإيرادات اليوم', 'ساعات اللعب اليوم']);
  const maskText = '••••••';
  let framePending = false;
  let scrollDrag = null;

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
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12s3.5-5 9-5 9 5 9 5-3.5 5-9 5-9-5Z"/><circle cx="12" cy="12" r="2.5"/></svg>';
  }

  function getPrivateStatLabel(stat) {
    return [...stat.querySelectorAll('span')]
      .map((span) => span.textContent.trim())
      .find((text) => privateLabels.has(text)) || '';
  }

  function applyPrivacy(hidden) {
    document.querySelectorAll('.stats .stat').forEach((stat) => {
      const label = getPrivateStatLabel(stat);
      const privateStat = privateLabels.has(label);
      stat.classList.toggle('pz-private-stat', privateStat);
      stat.classList.toggle('pz-private-stat-hidden', privateStat && hidden);
      if (!privateStat) return;

      const value = stat.querySelector('strong');
      if (!value) return;

      const current = value.textContent.trim();
      if (current && current !== maskText) {
        value.dataset.pzPrivateValue = current;
      }

      if (hidden) {
        if (value.textContent !== maskText) value.textContent = maskText;
        value.setAttribute('aria-label', 'القيمة مخفية');
      } else {
        const saved = value.dataset.pzPrivateValue;
        if (saved && value.textContent !== saved) value.textContent = saved;
        value.removeAttribute('aria-label');
      }
    });

    document.querySelectorAll('.pz-privacy-toggle').forEach((button) => {
      button.classList.toggle('is-hidden', hidden);
      button.innerHTML = privacyIcon(hidden);
      button.setAttribute('aria-label', hidden ? 'إظهار الإيرادات وساعات اللعب' : 'إخفاء الإيرادات وساعات اللعب');
      button.setAttribute('title', hidden ? 'إظهار التفاصيل' : 'إخفاء التفاصيل');
      button.setAttribute('aria-pressed', hidden ? 'true' : 'false');
    });
  }

  function ensurePrivacyToggle() {
    document.querySelectorAll('.stats').forEach((stats) => {
      const hasPrivateStats = [...stats.querySelectorAll('.stat')].some((stat) => privateLabels.has(getPrivateStatLabel(stat)));
      if (!hasPrivateStats) return;

      let button = stats.querySelector(':scope > .pz-privacy-toggle');
      if (!button) {
        button = document.createElement('button');
        button.type = 'button';
        button.className = 'pz-privacy-toggle';
        button.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          const hidden = localStorage.getItem(privacyKey) === '1';
          const next = !hidden;
          localStorage.setItem(privacyKey, next ? '1' : '0');
          applyPrivacy(next);
        });
        stats.prepend(button);
      }
    });
    applyPrivacy(localStorage.getItem(privacyKey) === '1');
  }

  function ensureVoltraInternalNavigation() {
    const anchor = document.querySelector('a.button.ghost[href="http://127.0.0.1:8086/voltra"], a.button.ghost[href="#voltra-console"]');
    if (!anchor || anchor.dataset.pzInternalVoltra === '1') return;

    anchor.dataset.pzInternalVoltra = '1';
    anchor.removeAttribute('target');
    anchor.removeAttribute('rel');
    anchor.setAttribute('href', '/voltra-console');
    anchor.textContent = 'لوحة Voltra';
    anchor.addEventListener('click', (event) => {
      event.preventDefault();
      window.location.assign('/voltra-console');
    });
  }

  function ensureLeftScrollbar() {
    let track = document.getElementById('pz-left-scroll-track');
    if (track) return;

    track = document.createElement('div');
    track.id = 'pz-left-scroll-track';
    track.setAttribute('aria-hidden', 'true');
    track.innerHTML = '<div id="pz-left-scroll-thumb"></div>';
    document.body.appendChild(track);

    const thumb = track.firstElementChild;

    thumb.addEventListener('pointerdown', (event) => {
      const scroller = document.scrollingElement || document.documentElement;
      scrollDrag = {
        pointerId: event.pointerId,
        startY: event.clientY,
        startScrollTop: scroller.scrollTop,
      };
      thumb.setPointerCapture?.(event.pointerId);
      document.body.classList.add('pz-scroll-dragging');
      event.preventDefault();
    });

    thumb.addEventListener('pointermove', (event) => {
      if (!scrollDrag || event.pointerId !== scrollDrag.pointerId) return;
      const scroller = document.scrollingElement || document.documentElement;
      const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      const trackHeight = Math.max(1, track.clientHeight);
      const thumbHeight = Math.max(30, thumb.offsetHeight);
      const travel = Math.max(1, trackHeight - thumbHeight);
      const delta = event.clientY - scrollDrag.startY;
      scroller.scrollTop = scrollDrag.startScrollTop + (delta / travel) * maxScroll;
      event.preventDefault();
    });

    const stopDrag = (event) => {
      if (!scrollDrag) return;
      if (event?.pointerId != null && event.pointerId !== scrollDrag.pointerId) return;
      scrollDrag = null;
      document.body.classList.remove('pz-scroll-dragging');
    };
    thumb.addEventListener('pointerup', stopDrag);
    thumb.addEventListener('pointercancel', stopDrag);

    track.addEventListener('pointerdown', (event) => {
      if (event.target === thumb) return;
      const scroller = document.scrollingElement || document.documentElement;
      const rect = track.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (event.clientY - rect.top) / Math.max(1, rect.height)));
      const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      scroller.scrollTo({ top: ratio * maxScroll, behavior: 'smooth' });
    });
  }

  function updateLeftScrollbar() {
    const track = document.getElementById('pz-left-scroll-track');
    const thumb = document.getElementById('pz-left-scroll-thumb');
    if (!track || !thumb) return;

    const scroller = document.scrollingElement || document.documentElement;
    const viewport = scroller.clientHeight;
    const total = scroller.scrollHeight;
    const maxScroll = Math.max(0, total - viewport);

    if (total <= viewport + 2) {
      track.classList.add('is-hidden');
      return;
    }
    track.classList.remove('is-hidden');

    const trackHeight = Math.max(1, track.clientHeight);
    const thumbHeight = Math.max(30, Math.round(trackHeight * viewport / total));
    const travel = Math.max(0, trackHeight - thumbHeight);
    const top = maxScroll > 0 ? Math.round(travel * scroller.scrollTop / maxScroll) : 0;
    thumb.style.height = `${thumbHeight}px`;
    thumb.style.transform = `translateY(${top}px)`;
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
    ensureVoltraInternalNavigation();
    ensureLeftScrollbar();
    annotateTables();
    updateLeftScrollbar();
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

  window.addEventListener('scroll', updateLeftScrollbar, { passive: true });
  tabletQuery.addEventListener?.('change', schedule);
  handsetQuery.addEventListener?.('change', schedule);
  window.addEventListener('orientationchange', schedule);
  window.addEventListener('resize', schedule, { passive: true });

  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', schedule, { once: true });
  } else {
    schedule();
  }
})();
