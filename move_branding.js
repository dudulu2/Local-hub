(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const LONG_PRESS_MS = 480;
  const LONG_PRESS_SLOP = 16;
  const RESTORE_KEY = 'localhub:move-restore-view';

  let pressTimer = 0;
  let pressCard = null;
  let pressPointerId = null;
  let pressStartX = 0;
  let pressStartY = 0;
  let pressActive = false;
  let pressDropNode = null;
  let movingPath = '';
  let moveBusy = false;
  let suppressClickUntil = 0;

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const toast = msg => {
    const el = $('#toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => el.classList.remove('show'), 1900);
  };

  async function api(url, opt = {}) {
    const r = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await r.json(); } catch {}
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  function installBranding() {
    const appName = 'LocalHub';
    let meta = document.querySelector('meta[name="application-name"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'application-name';
      document.head.appendChild(meta);
    }
    meta.content = appName;

    let apple = document.querySelector('meta[name="apple-mobile-web-app-title"]');
    if (!apple) {
      apple = document.createElement('meta');
      apple.name = 'apple-mobile-web-app-title';
      document.head.appendChild(apple);
    }
    apple.content = appName;

    if (!document.querySelector('link[data-localhub-favicon]')) {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#ff9800"/><rect x="8" y="8" width="48" height="48" rx="11" fill="#111113"/><path d="M27 20v24l20-12z" fill="#ff9800"/></svg>`;
      const icon = document.createElement('link');
      icon.rel = 'icon';
      icon.type = 'image/svg+xml';
      icon.dataset.localhubFavicon = '1';
      icon.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
      document.head.appendChild(icon);
    }

    const updateTitle = () => {
      const viewer = $('#viewer');
      const viewerTitle = ($('#viewerTitle')?.textContent || '').trim();
      const pageTitle = ($('#pageTitle')?.textContent || '').trim();
      if (viewer?.open && viewerTitle) document.title = `${viewerTitle} · LocalHub`;
      else if (pageTitle && pageTitle !== '首页') document.title = `${pageTitle} · LocalHub`;
      else document.title = 'LocalHub · 本地媒体库';
    };
    const observer = new MutationObserver(updateTitle);
    const page = $('#pageTitle'), viewerTitle = $('#viewerTitle'), viewer = $('#viewer');
    if (page) observer.observe(page, {subtree:true, childList:true, characterData:true});
    if (viewerTitle) observer.observe(viewerTitle, {subtree:true, childList:true, characterData:true});
    if (viewer) observer.observe(viewer, {attributes:true, attributeFilter:['open']});
    updateTitle();
  }

  function installStyles() {
    if ($('#localhubMoveStyles')) return;
    const style = document.createElement('style');
    style.id = 'localhubMoveStyles';
    style.textContent = `
      #moveModeBtn,#rescanBtn,#viewerMoveBtn{display:none!important}
      .move-guide{position:fixed;z-index:60;right:22px;top:76px;display:none;align-items:center;gap:9px;padding:8px 11px;border:1px solid #34343a;border-radius:9px;background:rgba(18,18,20,.96);backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(0,0,0,.28);font-size:11px;color:#a2a2a9;pointer-events:none}
      .move-guide strong{color:#d7d7dc;font-size:11px}
      body.move-mode .move-guide{display:flex}
      body.move-mode .card[data-id]{user-select:none}
      body.move-mode .folder-nav button,body.move-mode .main-nav button[data-route="root"]{position:relative;border:1px dashed transparent}
      body.move-mode .folder-nav button::after,body.move-mode .main-nav button[data-route="root"]::after{content:'松开移动';margin-left:auto;font-size:9px;color:#777780}
      body.move-mode .move-drop-hover{border-color:#6c4b20!important;background:#21190f!important;color:#f2d19e!important}
      body.move-mode .move-drop-hover::after{color:#e8b86d!important}
      body.move-busy .card[data-id]{pointer-events:none;opacity:.72}
      .card.longpress-source .thumb{outline:2px solid #a06b23!important;outline-offset:2px;transform:translateY(-2px)}
      .card.longpress-source{cursor:grabbing!important}
      @media(max-width:900px){.move-guide{left:12px;right:12px;top:auto;bottom:18px;justify-content:center}}
    `;
    document.head.appendChild(style);
  }

  function ensureGuide() {
    if ($('.move-guide')) return;
    const guide = document.createElement('div');
    guide.className = 'move-guide';
    guide.innerHTML = '<strong>移动位置</strong><span>按住并拖到左侧文件夹；松开即结束</span>';
    document.body.appendChild(guide);
  }

  function setGuide(text) {
    const el = $('.move-guide span');
    if (el) el.textContent = text || '按住并拖到左侧文件夹；松开即结束';
  }

  function fileName(path) {
    return String(path || '').replace(/\\/g, '/').split('/').pop() || path;
  }

  function destinationFrom(node) {
    const root = node?.closest?.('.main-nav button[data-route="root"]');
    if (root) return '';
    const folder = node?.closest?.('.folder-nav button');
    if (folder) return folder.dataset.folder ?? null;
    return null;
  }

  function pageNumber() {
    const text = ($('#pageInfo')?.textContent || '').trim();
    const m = text.match(/第\s*(\d+)/);
    return m ? Math.max(1, Number(m[1]) || 1) : 1;
  }

  function snapshotView() {
    const folder = $('.folder-nav button.active');
    const route = $('.main-nav button.active')?.dataset.route || 'home';
    const query = ($('#searchInput')?.value || '').trim();
    return {
      route,
      folder: folder ? folder.dataset.folder : null,
      query,
      page: pageNumber(),
      scrollY: Math.max(0, window.scrollY || 0),
    };
  }

  function migrateLocalState(oldId, newId) {
    if (!oldId || !newId || oldId === newId) return;
    try {
      const fav = JSON.parse(localStorage.getItem('localhub:favorites') || '[]');
      localStorage.setItem('localhub:favorites', JSON.stringify([...new Set(fav.map(id => id === oldId ? newId : id))]));
      const progress = JSON.parse(localStorage.getItem('localhub:progress') || '{}');
      if (progress[oldId]) {
        progress[newId] = progress[oldId];
        delete progress[oldId];
        localStorage.setItem('localhub:progress', JSON.stringify(progress));
      }
    } catch {}
  }

  function waitFor(predicate, timeout = 4000) {
    return new Promise(resolve => {
      const start = Date.now();
      const tick = () => {
        let ok = false;
        try { ok = !!predicate(); } catch {}
        if (ok || Date.now() - start >= timeout) return resolve(ok);
        setTimeout(tick, 70);
      };
      tick();
    });
  }

  async function restorePage(page) {
    const target = Math.max(1, Number(page) || 1);
    if (target <= 1) return;
    await waitFor(() => pageNumber() === 1 || !$('#pager')?.classList.contains('hidden'), 3000);
    for (let p = 2; p <= target; p++) {
      const next = $('#nextPage');
      if (!next || next.disabled) break;
      next.click();
      const reached = await waitFor(() => pageNumber() === p, 4000);
      if (!reached) break;
    }
  }

  async function restorePendingView() {
    let view = null;
    try {
      view = JSON.parse(sessionStorage.getItem(RESTORE_KEY) || 'null');
      sessionStorage.removeItem(RESTORE_KEY);
    } catch {
      sessionStorage.removeItem(RESTORE_KEY);
    }
    if (!view) return;

    await waitFor(() => $('#grid') && $('.main-nav button[data-route="home"]'), 3000);
    await sleep(180);

    if (view.query) {
      const input = $('#searchInput');
      if (input) {
        input.value = view.query;
        input.dispatchEvent(new Event('input', {bubbles:true}));
        await sleep(360);
        await restorePage(view.page);
      }
    } else if (view.folder !== null) {
      const found = await waitFor(() => $$('.folder-nav button').some(n => n.dataset.folder === view.folder), 3500);
      if (found) {
        const target = $$('.folder-nav button').find(n => n.dataset.folder === view.folder);
        target?.click();
        await sleep(180);
        await restorePage(view.page);
      }
    } else if (view.route && view.route !== 'home') {
      const target = $(`.main-nav button[data-route="${CSS.escape(view.route)}"]`);
      target?.click();
      await sleep(180);
      await restorePage(view.page);
    }

    setTimeout(() => window.scrollTo({top:Number(view.scrollY)||0,left:0,behavior:'instant'}), 80);
  }

  async function moveNow(path, folder, view) {
    if (moveBusy || !path || folder === null) return;
    moveBusy = true;
    document.body.classList.add('move-busy');
    try {
      const d = await api('/api/manage', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'move', paths:[path], folder, create:false})
      });
      const moved = d.moved?.[0];
      if (!moved) throw new Error('移动失败');
      migrateLocalState(path, moved.new);

      // The physical rename is already complete at this point. Refresh the
      // smart catalog directly, then reload once so home/list/favorites and
      // every in-memory id all agree with the new path.
      await api('/api/smart/rescan');
      try { sessionStorage.setItem(RESTORE_KEY, JSON.stringify(view || snapshotView())); } catch {}
      location.reload();
    } catch (e) {
      moveBusy = false;
      document.body.classList.remove('move-busy');
      toast(e.message || '移动失败');
    }
  }

  function clearDropHighlight() {
    $$('.move-drop-hover').forEach(n => n.classList.remove('move-drop-hover'));
    pressDropNode = null;
  }

  function endPressVisual() {
    clearTimeout(pressTimer);
    pressTimer = 0;
    if (pressCard) {
      pressCard.classList.remove('longpress-source');
      try {
        if (pressPointerId !== null && pressCard.hasPointerCapture?.(pressPointerId)) pressCard.releasePointerCapture(pressPointerId);
      } catch {}
    }
    pressCard = null;
    pressPointerId = null;
    pressActive = false;
    movingPath = '';
    clearDropHighlight();
    document.body.classList.remove('move-mode','is-dragging');
    setGuide('按住并拖到左侧文件夹；松开即结束');
  }

  function cancelPress() {
    endPressVisual();
  }

  function dropNodeAt(x, y) {
    const hit = document.elementFromPoint(x, y);
    const node = hit?.closest?.('.folder-nav button,.main-nav button[data-route="root"]') || null;
    $$('.move-drop-hover').forEach(n => { if (n !== node) n.classList.remove('move-drop-hover'); });
    node?.classList.add('move-drop-hover');
    pressDropNode = node;
    return node;
  }

  function activateLongPress() {
    const card = pressCard;
    const path = card?.dataset.id || '';
    if (!card || !path || moveBusy) return;
    pressTimer = 0;
    pressActive = true;
    movingPath = path;
    card.classList.add('longpress-source');
    document.body.classList.add('move-mode','is-dragging');
    suppressClickUntil = Date.now() + 900;
    try { navigator.vibrate?.(28); } catch {}
    setGuide(`正在移动 ${fileName(path)}：拖到左侧文件夹后松开；松开即取消`);
  }

  document.addEventListener('pointerdown', e => {
    if (moveBusy || e.isPrimary === false) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    const card = e.target.closest?.('.card[data-id]');
    if (!card || e.target.closest?.('button,input,select,a')) return;
    const path = card.dataset.id || '';
    if (!path) return;

    cancelPress();
    pressCard = card;
    pressPointerId = e.pointerId;
    pressStartX = e.clientX;
    pressStartY = e.clientY;
    try { card.setPointerCapture?.(e.pointerId); } catch {}
    pressTimer = setTimeout(activateLongPress, LONG_PRESS_MS);
  }, true);

  document.addEventListener('pointermove', e => {
    if (!pressCard || e.pointerId !== pressPointerId) return;
    if (!pressActive) {
      const dx = e.clientX - pressStartX, dy = e.clientY - pressStartY;
      if (Math.hypot(dx, dy) > LONG_PRESS_SLOP) cancelPress();
      return;
    }
    if (e.cancelable) e.preventDefault();
    dropNodeAt(e.clientX, e.clientY);
  }, {capture:true, passive:false});

  document.addEventListener('pointerup', e => {
    if (!pressCard || e.pointerId !== pressPointerId) return;
    clearTimeout(pressTimer);
    pressTimer = 0;
    if (!pressActive) {
      cancelPress();
      return;
    }

    if (e.cancelable) e.preventDefault();
    suppressClickUntil = Date.now() + 900;
    const path = movingPath;
    const view = snapshotView();
    const node = dropNodeAt(e.clientX, e.clientY) || pressDropNode;
    const destination = destinationFrom(node);

    // One-shot interaction: every pointer release leaves move mode. A valid
    // folder performs the move; any other release simply cancels it.
    endPressVisual();
    if (destination !== null && path) {
      void moveNow(path, destination, view);
    }
  }, {capture:true, passive:false});

  document.addEventListener('pointercancel', e => {
    if (!pressCard || e.pointerId !== pressPointerId) return;
    cancelPress();
  }, true);

  document.addEventListener('contextmenu', e => {
    if (pressActive || Date.now() < suppressClickUntil) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);

  document.addEventListener('click', e => {
    if (Date.now() >= suppressClickUntil) return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }, true);

  installStyles();
  ensureGuide();
  installBranding();
  restorePendingView().catch(() => {});
})();
