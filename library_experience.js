(() => {
  'use strict';

  const folderNav = document.querySelector('#folderNav');
  const newNav = document.querySelector('#newVideoNav');
  const newCount = document.querySelector('#newVideoCount');
  const meta = document.querySelector('#pageMeta');
  const hint = document.querySelector('#viewHint');
  const viewer = document.querySelector('#viewer');
  const brand = document.querySelector('#brandBtn');
  if (!folderNav) return;

  const expanded = new Set();
  let hoverTimer = null;
  let lastNewTotal = 0;
  let pollTimer = null;
  let refreshingHome = false;

  function parentPath(path) {
    const clean = String(path || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
    const index = clean.lastIndexOf('/');
    return index < 0 ? '' : clean.slice(0, index);
  }

  function depthOf(path) {
    const clean = String(path || '').replace(/^\/+|\/+$/g, '');
    return clean ? clean.split('/').length - 1 : 0;
  }

  function ancestors(path) {
    const rows = [];
    let current = parentPath(path);
    while (current) {
      rows.unshift(current);
      current = parentPath(current);
    }
    return rows;
  }

  function visibleFor(path) {
    let current = parentPath(path);
    while (current) {
      if (!expanded.has(current)) return false;
      current = parentPath(current);
    }
    return true;
  }

  function setButtonLabel(button, hasChildren) {
    const holder = button.querySelector(':scope > span');
    if (!holder) return;
    if (!button.dataset.treeName) {
      button.dataset.treeName = holder.textContent.replace(/^[▸▾▶▼]\s*/, '').trim();
    }
    holder.classList.add('folder-tree-label');
    holder.textContent = '';

    const caret = document.createElement('i');
    caret.className = 'folder-caret';
    caret.setAttribute('aria-hidden', 'true');
    caret.textContent = hasChildren ? (expanded.has(button.dataset.folder) ? '▾' : '▸') : '·';

    const glyph = document.createElement('i');
    glyph.className = 'folder-tree-glyph';
    glyph.setAttribute('aria-hidden', 'true');
    glyph.textContent = depthOf(button.dataset.folder) === 0 ? '▰' : '▱';

    const name = document.createElement('span');
    name.className = 'folder-tree-name';
    name.textContent = button.dataset.treeName;

    holder.append(caret, glyph, name);
  }

  function applyFolderTree() {
    const buttons = [...folderNav.querySelectorAll('button[data-folder]')];
    if (!buttons.length) return;
    const paths = new Set(buttons.map(button => button.dataset.folder || ''));

    const active = buttons.find(button => button.classList.contains('active'));
    if (active) ancestors(active.dataset.folder).forEach(path => expanded.add(path));

    for (const button of buttons) {
      const path = button.dataset.folder || '';
      const depth = depthOf(path);
      const hasChildren = [...paths].some(other => parentPath(other) === path);
      button.dataset.treeDepth = String(depth);
      button.style.setProperty('--folder-depth', String(depth));
      button.classList.toggle('folder-has-children', hasChildren);
      button.classList.toggle('folder-expanded', hasChildren && expanded.has(path));
      button.classList.toggle('folder-hidden', depth > 0 && !visibleFor(path));
      setButtonLabel(button, hasChildren);
    }
  }

  function expandPath(path) {
    ancestors(path).forEach(value => expanded.add(value));
    if (path) expanded.add(path);
    applyFolderTree();
  }

  folderNav.addEventListener('click', event => {
    const button = event.target.closest('button[data-folder]');
    if (!button || !folderNav.contains(button)) return;
    const path = button.dataset.folder || '';
    if (!button.classList.contains('folder-has-children')) return;

    if (event.target.closest('.folder-caret')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (expanded.has(path)) expanded.delete(path);
      else expanded.add(path);
      applyFolderTree();
      return;
    }

    // Clicking a folder still opens it through smart_ui.js, but the first click
    // also reveals its direct children. Expanded folders stay open until the
    // caret is explicitly collapsed.
    if (!expanded.has(path)) {
      expanded.add(path);
      applyFolderTree();
    }
  }, true);

  folderNav.addEventListener('mouseover', event => {
    const button = event.target.closest('button[data-folder].folder-has-children');
    if (!button || button.contains(event.relatedTarget) || expanded.has(button.dataset.folder)) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => {
      if (!button.isConnected || !button.matches(':hover')) return;
      expanded.add(button.dataset.folder || '');
      applyFolderTree();
    }, 520);
  });

  folderNav.addEventListener('mouseout', event => {
    const button = event.target.closest('button[data-folder]');
    if (!button || button.contains(event.relatedTarget)) return;
    clearTimeout(hoverTimer);
    hoverTimer = null;
  });

  document.addEventListener('click', event => {
    const card = event.target.closest?.('.folder-card[data-folder]');
    if (card) expandPath(card.dataset.folder || '');
  }, true);

  let treeRefreshTimer = null;
  new MutationObserver(() => {
    clearTimeout(treeRefreshTimer);
    treeRefreshTimer = setTimeout(applyFolderTree, 0);
  }).observe(folderNav, {childList:true, subtree:false});

  function cleanMeta() {
    if (hint) hint.textContent = '';
    if (!meta) return;
    let text = meta.textContent || '';
    text = text.replace(/\s*·\s*首页只展示\s*\d+\s*个视频.*$/u, '');
    text = text.replace(/\s*·\s*当前页只加载\s*\d+\s*项.*$/u, '');
    text = text.replace(/\s*·\s*当前页最多\s*\d+\s*项.*$/u, '');
    meta.textContent = text.trim();
  }

  if (meta) new MutationObserver(cleanMeta).observe(meta, {childList:true, subtree:true, characterData:true});
  cleanMeta();

  function ensureNotice() {
    let notice = document.querySelector('#newMediaNotice');
    if (notice) return notice;
    notice = document.createElement('button');
    notice.type = 'button';
    notice.id = 'newMediaNotice';
    notice.className = 'new-media-notice hidden';
    notice.addEventListener('click', () => {
      notice.classList.add('hidden');
      newNav?.click();
    });
    document.body.appendChild(notice);
    return notice;
  }

  function updateNewNav(total) {
    total = Math.max(0, Number(total) || 0);
    if (!newNav) return;
    newNav.classList.toggle('hidden', total <= 0);
    if (newCount) newCount.textContent = total > 99 ? '99+' : String(total);
  }

  function announceNew(delta, total) {
    if (delta <= 0) return;
    const notice = ensureNotice();
    notice.innerHTML = `<strong>已新增 ${delta} 个视频</strong><span>点击查看</span>`;
    notice.classList.remove('hidden');
    clearTimeout(announceNew.timer);
    announceNew.timer = setTimeout(() => notice.classList.add('hidden'), 9000);
    updateNewNav(total);
  }

  async function pollNewVideos() {
    clearTimeout(pollTimer);
    if (document.hidden || viewer?.open) {
      pollTimer = setTimeout(pollNewVideos, 8000);
      return;
    }
    try {
      const response = await fetch('/api/smart/list?view=new&offset=0&limit=1&watch=1', {cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const total = Math.max(0, Number(data.total) || 0);
      const delta = Math.max(0, total - lastNewTotal);
      updateNewNav(total);
      if (delta > 0) announceNew(delta, total);
      lastNewTotal = total;

      // A changed catalog may contain a brand-new top-level folder. Refresh the
      // home snapshot only when the user is already on Home; never pull them out
      // of a folder/search/player just to update the sidebar.
      if (data.catalogChanged && document.querySelector('.main-nav button[data-route="home"]')?.classList.contains('active') && !refreshingHome) {
        refreshingHome = true;
        setTimeout(() => {
          try { brand?.click(); }
          finally { setTimeout(() => { refreshingHome = false; }, 600); }
        }, 80);
      }
    } catch {
      // Discovery is optional UX. A transient watcher failure must never affect
      // normal library browsing or playback.
    }
    pollTimer = setTimeout(pollNewVideos, 12000);
  }

  newNav?.addEventListener('click', () => document.querySelector('#newMediaNotice')?.classList.add('hidden'));
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      clearTimeout(pollTimer);
      pollTimer = setTimeout(pollNewVideos, 700);
    }
  });
  viewer?.addEventListener('close', () => {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(pollNewVideos, 900);
  });

  applyFolderTree();
  updateNewNav(0);
  pollTimer = setTimeout(pollNewVideos, 3200);
})();
