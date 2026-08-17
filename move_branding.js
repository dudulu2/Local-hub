(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  let moveMode = false;
  let selectedPath = '';
  let draggingPath = '';
  let moveBusy = false;

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
      #moveModeBtn{margin-left:auto;white-space:nowrap}
      #rescanBtn{margin-left:0}
      #moveModeBtn.active{border-color:#6a4a1d;background:#21180e;color:#ffc267}
      .move-guide{position:fixed;z-index:45;right:22px;top:76px;display:none;align-items:center;gap:9px;padding:8px 11px;border:1px solid #34343a;border-radius:9px;background:rgba(18,18,20,.94);backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(0,0,0,.28);font-size:11px;color:#a2a2a9;pointer-events:none}
      .move-guide strong{color:#d7d7dc;font-size:11px}
      body.move-mode .move-guide{display:flex}
      body.move-mode .card[data-id]{cursor:grab;user-select:none}
      body.move-mode .card[data-id]:active{cursor:grabbing}
      body.move-mode .card[data-id] .thumb{outline:1px solid transparent;outline-offset:2px;transition:outline-color .12s,transform .12s}
      body.move-mode .card[data-id]:hover .thumb{outline-color:#5e4524}
      body.move-mode .card.move-selected .thumb{outline:2px solid #a06b23;transform:translateY(-2px)}
      body.move-mode .card.move-selected::before{content:'已选择';position:absolute;right:8px;top:8px;z-index:8;background:#1c160e;color:#e0b56e;border:1px solid #6a4a1d;border-radius:6px;padding:3px 6px;font-size:9px;font-weight:800}
      body.move-mode .card.move-dragging{opacity:.55}
      body.move-mode .folder-nav button,body.move-mode .main-nav button[data-route="root"]{position:relative;border:1px dashed transparent}
      body.move-mode .folder-nav button::after,body.move-mode .main-nav button[data-route="root"]::after{content:'放这里';margin-left:auto;font-size:9px;color:#5e5e65;opacity:.65}
      body.move-mode .folder-nav button:hover,body.move-mode .main-nav button[data-route="root"]:hover,body.move-mode .move-drop-hover{border-color:#6c4b20!important;background:#21190f!important;color:#f2d19e!important}
      body.move-mode .move-drop-hover::after{content:'松开移动'!important;color:#e8b86d!important;opacity:1!important}
      body.move-busy .card[data-id]{pointer-events:none;opacity:.7}
      .viewer-actions #viewerMoveBtn{color:#b7b7bd}
      .viewer-actions #viewerMoveBtn:hover{color:#fff;border-color:#55555c}
      .manage-panel div:has(#moveInput),#moveBtn{display:none!important}
      @media(max-width:900px){#moveModeBtn{display:none}.move-guide{display:none!important}}
    `;
    document.head.appendChild(style);
  }

  function ensureMoveUi() {
    const rescan = $('#rescanBtn');
    if (rescan && !$('#moveModeBtn')) {
      const btn = document.createElement('button');
      btn.className = 'top-btn move-mode-btn';
      btn.id = 'moveModeBtn';
      btn.type = 'button';
      btn.textContent = '移动位置';
      btn.title = '把视频拖到左侧文件夹进行分类';
      rescan.parentElement?.insertBefore(btn, rescan);
      btn.addEventListener('click', () => setMoveMode(!moveMode));
    }

    if (!$('.move-guide')) {
      const guide = document.createElement('div');
      guide.className = 'move-guide';
      guide.innerHTML = '<strong>移动位置</strong><span>拖动视频到左侧文件夹，或先点视频再点目标文件夹</span>';
      document.body.appendChild(guide);
    }

    const actions = $('.viewer-actions');
    if (actions && !$('#viewerMoveBtn')) {
      const btn = document.createElement('button');
      btn.id = 'viewerMoveBtn';
      btn.type = 'button';
      btn.textContent = '移动位置';
      btn.title = '选择当前视频，然后点左侧目标文件夹';
      const manage = $('#manageBtn');
      actions.insertBefore(btn, manage || null);
      btn.addEventListener('click', () => {
        const path = ($('#viewerPath')?.textContent || '').trim();
        if (!path) return;
        selectedPath = path;
        $('#closeViewer')?.click();
        setMoveMode(true, true);
        decorateCards();
        const card = $$('.card[data-id]').find(node => node.dataset.id === path);
        if (card) {
          card.classList.add('move-selected');
          card.scrollIntoView({behavior:'smooth', block:'center'});
        }
        updateGuide(`已选择 ${fileName(path)}，点击左侧目标文件夹`);
      });
    }
  }

  function updateGuide(text = '') {
    const guide = $('.move-guide span');
    if (!guide) return;
    guide.textContent = text || (selectedPath ? `已选择 ${fileName(selectedPath)}，点击左侧目标文件夹` : '拖动视频到左侧文件夹，或先点视频再点目标文件夹');
  }

  function fileName(path) {
    return String(path || '').replace(/\\/g,'/').split('/').pop() || path;
  }

  function sourceFolder(path) {
    const parts = String(path || '').replace(/\\/g,'/').split('/');
    parts.pop();
    return parts.join('/');
  }

  function destinationFrom(node) {
    const root = node?.closest?.('.main-nav button[data-route="root"]');
    if (root) return '';
    const folder = node?.closest?.('.folder-nav button');
    if (folder) return folder.dataset.folder ?? null;
    return null;
  }

  function setMoveMode(on, keepSelection = false) {
    moveMode = !!on;
    if (!moveMode && !keepSelection) selectedPath = '';
    draggingPath = '';
    document.body.classList.toggle('move-mode', moveMode);
    document.body.classList.remove('is-dragging');
    const btn = $('#moveModeBtn');
    if (btn) {
      btn.classList.toggle('active', moveMode);
      btn.textContent = moveMode ? '完成移动' : '移动位置';
      btn.setAttribute('aria-pressed', moveMode ? 'true' : 'false');
    }
    decorateCards();
    updateGuide();
  }

  function decorateCards() {
    $$('.card[data-id]').forEach(card => {
      card.draggable = moveMode;
      card.classList.toggle('move-selected', moveMode && !!selectedPath && card.dataset.id === selectedPath);
      if (moveMode) card.title = '拖到左侧文件夹即可移动';
      else if (card.title === '拖到左侧文件夹即可移动') card.removeAttribute('title');
    });
  }

  function snapshotView() {
    const folder = $('.folder-nav button.active');
    const route = $('.main-nav button.active')?.dataset.route || '';
    const query = ($('#searchInput')?.value || '').trim();
    const title = ($('#pageTitle')?.textContent || '').trim();
    return {folder: folder ? folder.dataset.folder : null, route: route || (title === '根目录' ? 'root' : ''), query};
  }

  function migrateLocalState(oldId, newId) {
    if (!oldId || !newId || oldId === newId) return;
    try {
      const fav = JSON.parse(localStorage.getItem('localhub:favorites') || '[]');
      const mapped = fav.map(id => id === oldId ? newId : id);
      localStorage.setItem('localhub:favorites', JSON.stringify([...new Set(mapped)]));
      const progress = JSON.parse(localStorage.getItem('localhub:progress') || '{}');
      if (progress[oldId]) {
        progress[newId] = progress[oldId];
        delete progress[oldId];
        localStorage.setItem('localhub:progress', JSON.stringify(progress));
      }
    } catch {}
  }

  async function waitForRescan(btn) {
    const deadline = Date.now() + 20000;
    await sleep(50);
    while (Date.now() < deadline) {
      if (!btn.disabled && !/扫描中/.test(btn.textContent || '')) return;
      await sleep(100);
    }
  }

  async function refreshPreservingView(view) {
    const rescan = $('#rescanBtn');
    if (!rescan) { location.reload(); return; }
    rescan.click();
    await waitForRescan(rescan);
    await sleep(100);

    if (view.query) {
      const input = $('#searchInput');
      if (input) {
        input.value = view.query;
        input.dispatchEvent(new Event('input', {bubbles:true}));
        return;
      }
    }

    if (view.folder !== null) {
      const target = $$('.folder-nav button').find(node => node.dataset.folder === view.folder);
      if (target) { target.click(); return; }
    }

    if (view.route && view.route !== 'home') {
      const target = $(`.main-nav button[data-route="${CSS.escape(view.route)}"]`);
      if (target) { target.click(); return; }
    }
  }

  async function moveNow(path, folder) {
    if (!moveMode || moveBusy || !path || folder === null) return;
    if (sourceFolder(path) === folder) {
      toast('已经在这个分类里');
      selectedPath = '';
      decorateCards();
      updateGuide();
      return;
    }

    const view = snapshotView();
    moveBusy = true;
    document.body.classList.add('move-busy');
    updateGuide(`正在移动 ${fileName(path)}…`);
    try {
      const d = await api('/api/manage', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'move', paths:[path], folder, create:false})
      });
      const moved = d.moved?.[0];
      if (!moved) throw new Error('移动失败');
      migrateLocalState(path, moved.new);
      selectedPath = '';
      draggingPath = '';
      $$('.move-drop-hover').forEach(n => n.classList.remove('move-drop-hover'));
      toast(`已移动到 ${folder || '根目录'}`);
      await refreshPreservingView(view);
    } catch (e) {
      toast(e.message || '移动失败');
    } finally {
      moveBusy = false;
      document.body.classList.remove('move-busy','is-dragging');
      decorateCards();
      updateGuide();
    }
  }

  document.addEventListener('dragstart', e => {
    if (!moveMode) return;
    const card = e.target.closest?.('.card[data-id]');
    if (!card) return;
    const path = card.dataset.id;
    if (!path) return;
    draggingPath = path;
    selectedPath = path;
    card.classList.add('move-dragging','move-selected');
    document.body.classList.add('is-dragging');
    try {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', path);
      e.dataTransfer.setData('application/x-localhub-path', path);
    } catch {}
    updateGuide(`正在拖动 ${fileName(path)}，放到左侧目标文件夹`);
  }, true);

  document.addEventListener('dragend', e => {
    e.target.closest?.('.card[data-id]')?.classList.remove('move-dragging');
    draggingPath = '';
    document.body.classList.remove('is-dragging');
    $$('.move-drop-hover').forEach(n => n.classList.remove('move-drop-hover'));
    decorateCards();
    updateGuide();
  }, true);

  document.addEventListener('dragover', e => {
    if (!moveMode || !draggingPath) return;
    const destination = destinationFrom(e.target);
    if (destination === null) return;
    e.preventDefault();
    try { e.dataTransfer.dropEffect = 'move'; } catch {}
    const node = e.target.closest('.folder-nav button,.main-nav button[data-route="root"]');
    $$('.move-drop-hover').forEach(n => { if (n !== node) n.classList.remove('move-drop-hover'); });
    node?.classList.add('move-drop-hover');
  }, true);

  document.addEventListener('dragleave', e => {
    const node = e.target.closest?.('.folder-nav button,.main-nav button[data-route="root"]');
    if (node && !node.contains(e.relatedTarget)) node.classList.remove('move-drop-hover');
  }, true);

  document.addEventListener('drop', e => {
    if (!moveMode || !draggingPath) return;
    const destination = destinationFrom(e.target);
    if (destination === null) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const path = draggingPath;
    draggingPath = '';
    moveNow(path, destination);
  }, true);

  document.addEventListener('click', e => {
    if (!moveMode || moveBusy) return;

    const destination = destinationFrom(e.target);
    if (destination !== null && selectedPath) {
      e.preventDefault();
      e.stopImmediatePropagation();
      moveNow(selectedPath, destination);
      return;
    }

    const card = e.target.closest?.('.card[data-id]');
    if (!card) return;
    if (e.target.closest('button,input,select,a')) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const path = card.dataset.id || '';
    selectedPath = selectedPath === path ? '' : path;
    decorateCards();
    updateGuide();
  }, true);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && moveMode && !$('#viewer')?.open && !$('#reader')?.open) {
      setMoveMode(false);
      toast('已退出移动模式');
    }
  });

  const observer = new MutationObserver(() => {
    ensureMoveUi();
    decorateCards();
  });
  observer.observe(document.body, {subtree:true, childList:true});

  installStyles();
  installBranding();
  ensureMoveUi();
  decorateCards();
})();
