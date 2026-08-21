(() => {
  'use strict';

  const viewer = document.querySelector('#viewer');
  const grid = document.querySelector('#grid');
  if (!viewer) return;

  let warmingTimer = 0;
  const normalize = value => String(value || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');

  function isEditable(target) {
    if (!(target instanceof Element)) return false;
    return !!target.closest('input,textarea,select,[contenteditable="true"]');
  }

  document.addEventListener('keydown', e => {
    if (!viewer.open || e.altKey || e.ctrlKey || e.metaKey || isEditable(e.target)) return;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const player = window.videojs?.getPlayer?.('videoPlayer');
    if (!player) return;
    const current = Number(player.currentTime()) || 0;
    const duration = Number(player.duration()) || 0;
    const delta = e.key === 'ArrowLeft' ? -10 : 10;
    const target = Math.max(0, duration > 0 ? Math.min(duration, current + delta) : current + delta);
    e.preventDefault();
    e.stopPropagation();
    try { player.currentTime(target); } catch {}
  }, true);

  async function postJSON(url, payload, keepalive = false) {
    try {
      await fetch(url, {
        method:'POST', cache:'no-store', keepalive,
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
    } catch {}
  }

  function reportPlayback(active) {
    void postJSON('/api/stable2/playback', {active:!!active}, true);
  }

  function queueVisibleCovers() {
    clearTimeout(warmingTimer);
    if (viewer.open || !grid) return;
    warmingTimer = window.setTimeout(() => {
      if (viewer.open) return;
      const paths = [...grid.querySelectorAll('.card[data-id]')]
        .map(node => normalize(node.dataset.id))
        .filter(Boolean)
        .slice(0, 24);
      if (paths.length) void postJSON('/api/stable2/warm', {paths, includeHover:false});
    }, 600);
  }

  const viewerObserver = new MutationObserver(() => {
    reportPlayback(viewer.open);
    if (!viewer.open) queueVisibleCovers();
  });
  viewerObserver.observe(viewer, {attributes:true, attributeFilter:['open']});
  viewer.addEventListener('close', () => { reportPlayback(false); queueVisibleCovers(); });
  viewer.addEventListener('cancel', () => { reportPlayback(false); queueVisibleCovers(); });
  window.addEventListener('beforeunload', () => reportPlayback(false));

  if (grid) new MutationObserver(queueVisibleCovers).observe(grid, {childList:true, subtree:false});

  reportPlayback(viewer.open);
  queueVisibleCovers();
})();
(() => {
  'use strict';

  const folderNav = document.querySelector('#folderNav');
  if (!folderNav) return;

  const EXPANDED_KEY = 'localhub:tree-expanded-v1';
  const DRAG_DWELL_MS = 800;
  const TEMP_COLLAPSE_MS = 8000;

  const normalize = value => String(value || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  const parentOf = path => {
    const parts = normalize(path).split('/').filter(Boolean);
    parts.pop();
    return parts.join('/');
  };
  const depthOf = path => normalize(path).split('/').filter(Boolean).length - 1;
  const esc = s => String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function readExpanded() {
    try {
      const rows = JSON.parse(sessionStorage.getItem(EXPANDED_KEY) || '[]');
      return new Set(Array.isArray(rows) ? rows.map(normalize).filter(Boolean) : []);
    } catch {
      return new Set();
    }
  }
  function saveExpanded() {
    try { sessionStorage.setItem(EXPANDED_KEY, JSON.stringify([...manualExpanded])); } catch {}
  }

  const manualExpanded = readExpanded();
  const tempExpanded = new Set();
  const meta = new Map();
  const sourceButtons = new Map();
  let selectedHint = '';
  let rebuilding = false;
  let rebuildQueued = false;
  let dwellTimer = 0;
  let dwellPath = '';
  let tempCollapseTimer = 0;

  function sourceBox() { return folderNav.querySelector(':scope > .lh-tree-source'); }
  function treeBox() { return folderNav.querySelector(':scope > .lh-tree'); }
  function isExpanded(path) { return manualExpanded.has(path) || tempExpanded.has(path); }
  function hasChildren(path) {
    for (const key of meta.keys()) if (parentOf(key) === path) return true;
    return false;
  }
  function selectedPath() {
    const activeSource = sourceBox()?.querySelector('button.active[data-folder]');
    const activeTree = treeBox()?.querySelector('.lh-tree-open.active[data-folder]');
    return normalize(activeSource?.dataset.folder || activeTree?.dataset.folder || selectedHint);
  }

  function parseFlatButton(button) {
    const path = normalize(button.dataset.folder);
    if (!path) return null;
    const name = (button.querySelector('span')?.textContent || path.split('/').pop() || path).replace(/^\s*[▸›⌄]\s*/, '').trim();
    const count = (button.querySelector('small')?.textContent || '').trim();
    return {path, name, count};
  }

  function harvestFlatButtons() {
    const raw = [...folderNav.querySelectorAll(':scope > button[data-folder]:not(.lh-tree-open):not(.lh-tree-expander)')];
    if (!raw.length) return false;

    let source = sourceBox();
    if (!source) {
      source = document.createElement('div');
      source.className = 'lh-tree-source';
    }
    source.innerHTML = '';
    meta.clear();
    sourceButtons.clear();

    for (const button of raw) {
      const row = parseFlatButton(button);
      if (!row) continue;
      button.classList.add('lh-tree-source-button');
      source.appendChild(button);
      meta.set(row.path, row);
      sourceButtons.set(row.path, button);
    }
    folderNav.appendChild(source);
    return true;
  }

  function restoreMetaFromSource() {
    const source = sourceBox();
    if (!source) return;
    meta.clear();
    sourceButtons.clear();
    for (const button of source.querySelectorAll('button[data-folder]')) {
      const row = parseFlatButton(button);
      if (!row) continue;
      meta.set(row.path, row);
      sourceButtons.set(row.path, button);
    }
  }

  function childrenOf(parent) {
    const rows = [];
    for (const row of meta.values()) if (parentOf(row.path) === parent) rows.push(row);
    rows.sort((a,b) => a.name.localeCompare(b.name, undefined, {numeric:true, sensitivity:'base'}));
    return rows;
  }

  function currentContext(path, selected) {
    if (!selected || !path) return false;
    return selected === path || selected.startsWith(path + '/');
  }

  function makeNode(row, selected) {
    const node = document.createElement('div');
    node.className = 'lh-tree-node';
    node.dataset.folderNode = row.path;
    node.dataset.depth = String(Math.max(0, depthOf(row.path)));

    const line = document.createElement('div');
    line.className = 'lh-tree-row';
    line.dataset.folder = row.path;
    line.dataset.hasChildren = hasChildren(row.path) ? '1' : '0';
    if (selected === row.path) line.classList.add('lh-tree-selected');
    else if (currentContext(row.path, selected)) line.classList.add('lh-tree-branch');
    if (isExpanded(row.path)) line.classList.add('lh-tree-expanded');

    const expander = document.createElement('button');
    expander.type = 'button';
    expander.className = 'lh-tree-expander';
    expander.dataset.folder = row.path;
    expander.tabIndex = 0;
    if (hasChildren(row.path)) {
      expander.textContent = isExpanded(row.path) ? '⌄' : '›';
      expander.setAttribute('aria-label', `${isExpanded(row.path) ? '折叠' : '展开'} ${row.name}`);
      expander.setAttribute('aria-expanded', String(isExpanded(row.path)));
      expander.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        if (tempExpanded.has(row.path) && !manualExpanded.has(row.path)) {
          tempExpanded.delete(row.path);
          manualExpanded.add(row.path);
        } else if (manualExpanded.has(row.path)) {
          manualExpanded.delete(row.path);
        } else {
          manualExpanded.add(row.path);
        }
        saveExpanded();
        renderTree();
      });
    } else {
      expander.textContent = '';
      expander.classList.add('lh-tree-expander-empty');
      expander.tabIndex = -1;
      expander.setAttribute('aria-hidden', 'true');
    }

    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'lh-tree-open';
    open.dataset.folder = row.path;
    open.title = `打开 ${row.path}`;
    open.innerHTML = `<span class="lh-tree-name">${esc(row.name)}</span><small class="lh-tree-count" aria-hidden="true">${esc(row.count)}</small>`;
    if (selected === row.path) open.classList.add('active');
    open.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      if (document.body.classList.contains('move-mode')) return;
      selectedHint = row.path;
      sourceButtons.get(row.path)?.click();
      syncSelectedSoon();
    });

    line.append(expander, open);
    node.appendChild(line);

    if (hasChildren(row.path) && isExpanded(row.path)) {
      const children = document.createElement('div');
      children.className = 'lh-tree-children';
      for (const child of childrenOf(row.path)) children.appendChild(makeNode(child, selected));
      node.appendChild(children);
    }
    return node;
  }

  function renderTree() {
    if (rebuilding) return;
    let tree = treeBox();
    if (!tree) {
      tree = document.createElement('div');
      tree.className = 'lh-tree';
      folderNav.appendChild(tree);
    }
    const selected = selectedPath();
    tree.innerHTML = '';
    const roots = childrenOf('');
    if (!roots.length) {
      tree.innerHTML = '<div class="lh-tree-empty">没有文件夹</div>';
      return;
    }
    for (const row of roots) tree.appendChild(makeNode(row, selected));
  }

  function rebuildFromFlat() {
    if (rebuilding) return;
    rebuilding = true;
    try {
      const changed = harvestFlatButtons();
      if (!changed && !meta.size) restoreMetaFromSource();
      if (meta.size) renderTree();
    } finally {
      rebuilding = false;
    }
  }

  function queueRebuild() {
    if (rebuildQueued) return;
    rebuildQueued = true;
    queueMicrotask(() => {
      rebuildQueued = false;
      const raw = folderNav.querySelector(':scope > button[data-folder]:not(.lh-tree-open):not(.lh-tree-expander)');
      if (raw) rebuildFromFlat();
    });
  }

  function syncSelectedSoon() {
    window.setTimeout(() => {
      const active = sourceBox()?.querySelector('button.active[data-folder]');
      if (active) selectedHint = normalize(active.dataset.folder);
      renderTree();
    }, 40);
  }

  function guide(text) {
    const span = document.querySelector('.move-guide span');
    if (span && text) span.textContent = text;
  }

  function clearDwellVisual() {
    clearTimeout(dwellTimer);
    dwellTimer = 0;
    dwellPath = '';
    folderNav.querySelectorAll('.lh-tree-dwell-target').forEach(row => row.classList.remove('lh-tree-dwell-target'));
  }

  function scheduleTempCollapse() {
    clearTimeout(tempCollapseTimer);
    if (!tempExpanded.size) return;
    tempCollapseTimer = window.setTimeout(() => {
      if (document.body.classList.contains('move-mode')) return scheduleTempCollapse();
      tempExpanded.clear();
      renderTree();
    }, TEMP_COLLAPSE_MS);
  }

  document.addEventListener('pointermove', e => {
    if (!document.body.classList.contains('move-mode')) {
      clearDwellVisual();
      return;
    }
    clearTimeout(tempCollapseTimer);
    const hit = document.elementFromPoint(e.clientX, e.clientY);
    const row = hit?.closest?.('#folderNav .lh-tree-row[data-folder]');
    const path = normalize(row?.dataset.folder || '');
    if (!path) {
      clearDwellVisual();
      return;
    }

    const expandable = hasChildren(path) && !isExpanded(path);
    guide(`移动至：${path}${expandable ? ' · 松开移动；停留可展开' : ' · 松开移动'}`);
    if (!expandable) {
      clearDwellVisual();
      return;
    }
    if (dwellPath === path && dwellTimer) return;

    clearDwellVisual();
    dwellPath = path;
    row.classList.add('lh-tree-dwell-target');
    dwellTimer = window.setTimeout(() => {
      if (!document.body.classList.contains('move-mode') || dwellPath !== path) return;
      tempExpanded.add(path);
      clearDwellVisual();
      renderTree();
      guide(`已展开：${path} · 继续选择子文件夹，或在当前目录松开`);
    }, DRAG_DWELL_MS);
  }, true);

  function finishMoveTree() {
    clearDwellVisual();
    scheduleTempCollapse();
  }
  document.addEventListener('pointerup', finishMoveTree, true);
  document.addEventListener('pointercancel', finishMoveTree, true);

  document.querySelectorAll('.main-nav button').forEach(button => {
    button.addEventListener('click', () => {
      selectedHint = '';
      window.setTimeout(renderTree, 20);
    });
  });
  document.querySelector('#searchInput')?.addEventListener('input', e => {
    if (String(e.target.value || '').trim()) {
      selectedHint = '';
      window.setTimeout(renderTree, 20);
    }
  });

  const observer = new MutationObserver(records => {
    if (rebuilding) return;
    for (const record of records) {
      if (record.type === 'childList') {
        queueRebuild();
        break;
      }
    }
  });
  observer.observe(folderNav, {childList:true});

  const style = document.createElement('style');
  style.id = 'lhStable3TreeStyles';
  style.textContent = `
    #folderNav{display:block!important;position:relative}
    #folderNav>.lh-tree-source{display:none!important}
    #folderNav>.lh-tree{display:block;min-width:0;padding:1px 0 4px}
    #folderNav .lh-tree-node{display:block;min-width:0}
    #folderNav .lh-tree-children{margin-left:10px;padding-left:5px;border-left:1px solid #252529}
    #folderNav .lh-tree-row{position:relative;display:grid;grid-template-columns:20px minmax(0,1fr);align-items:center;min-height:32px;border:1px solid transparent;border-radius:7px;margin:1px 0;transition:background .12s,border-color .12s,box-shadow .12s}
    #folderNav .lh-tree-row:hover{background:#18181b}
    #folderNav .lh-tree-row.lh-tree-branch:not(.lh-tree-selected){background:#141416}
    #folderNav .lh-tree-row.lh-tree-selected{background:#1d1d20;box-shadow:inset 2px 0 0 var(--accent)}
    #folderNav .lh-tree-expander{width:20px;height:28px;padding:0;border:0;background:transparent!important;color:#777780!important;display:grid;place-items:center;text-align:center;font-size:15px;line-height:1;cursor:pointer;border-radius:5px}
    #folderNav .lh-tree-expander:hover{color:#fff!important;background:#252529!important}
    #folderNav .lh-tree-expander-empty{cursor:default!important;pointer-events:none!important}
    #folderNav .lh-tree-open{min-width:0;height:30px;padding:0 4px!important;border:0!important;background:transparent!important;display:grid!important;grid-template-columns:minmax(0,1fr) auto;align-items:center!important;text-align:left!important;color:#b9b9c0!important;border-radius:4px!important;cursor:pointer!important}
    #folderNav .lh-tree-open:hover{color:#fff!important}
    #folderNav .lh-tree-open.active{color:#fff!important;font-weight:760}
    #folderNav .lh-tree-expander.active{background:transparent!important;color:#777780!important}
    #folderNav .lh-tree-name{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #folderNav .lh-tree-count{min-width:22px;padding:0 6px 0 4px;text-align:right;color:#5f5f67;font-size:9px;font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:500}
    #folderNav .lh-tree-row[data-has-children="0"] .lh-tree-count{padding-right:6px}
    #folderNav .lh-tree-empty{padding:10px 9px;color:#666;font-size:11px}
    body.move-mode #folderNav .lh-tree-row{cursor:grabbing}
    body.move-mode #folderNav .lh-tree-row:has(.move-drop-hover){border-color:#765321!important;background:#241b10!important;box-shadow:inset 0 0 0 1px rgba(255,184,93,.08)}
    body.move-mode #folderNav .lh-tree-row:has(.move-drop-hover) .lh-tree-open{color:#ffd18a!important}
    body.move-mode #folderNav .lh-tree-row.lh-tree-dwell-target::after{content:'';position:absolute;right:5px;top:5px;width:18px;height:18px;border-radius:50%;border:2px solid #4a3923;border-top-color:#e5a64d;animation:lhTreeDwell .8s linear infinite;pointer-events:none}
    body.move-mode #folderNav .lh-tree-row.lh-tree-dwell-target .lh-tree-count{opacity:0}
    @keyframes lhTreeDwell{to{transform:rotate(360deg)}}
  `;
  document.head.appendChild(style);

  rebuildFromFlat();
})();
