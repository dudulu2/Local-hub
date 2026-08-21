(() => {
  'use strict';

  const folderNav = document.querySelector('#folderNav');
  const viewer = document.querySelector('#viewer');
  const grid = document.querySelector('#grid');
  if (!folderNav || !viewer) return;

  const ROOT_RESET_MS = 8000;
  const DRILL_DWELL_MS = 1000;
  let level = '';
  let resetTimer = 0;
  let dwellTimer = 0;
  let dwellPath = '';
  let renderQueued = false;
  let warmingTimer = 0;

  const normalize = value => String(value || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  const parentOf = path => {
    const parts = normalize(path).split('/').filter(Boolean);
    parts.pop();
    return parts.join('/');
  };
  const baseName = path => normalize(path).split('/').filter(Boolean).pop() || '一级文件夹';
  const firstPart = path => normalize(path).split('/').filter(Boolean)[0] || '';

  function folderButtons() {
    return [...folderNav.querySelectorAll('button[data-folder]')];
  }

  function paths() {
    return new Set(folderButtons().map(node => normalize(node.dataset.folder)).filter(Boolean));
  }

  function hasChildren(path) {
    path = normalize(path);
    for (const candidate of paths()) {
      if (parentOf(candidate) === path) return true;
    }
    return false;
  }

  function activeFolder() {
    const active = folderNav.querySelector('button.active[data-folder]');
    return normalize(active?.dataset.folder || '');
  }

  function ensureBackRow() {
    let row = folderNav.querySelector('#lhFolderTreeBack');
    if (!row) {
      row = document.createElement('button');
      row.id = 'lhFolderTreeBack';
      row.type = 'button';
      row.className = 'lh-folder-tree-back';
      row.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        setLevel(parentOf(level));
      });
      folderNav.prepend(row);
    }
    return row;
  }

  function renderFolders() {
    renderQueued = false;
    const available = paths();
    if (level && !available.has(level)) level = parentOf(level);
    const active = activeFolder();
    const branch = firstPart(active);
    const back = ensureBackRow();
    back.classList.toggle('hidden', !level);
    back.textContent = level ? `← ${parentOf(level) ? baseName(parentOf(level)) : '一级文件夹'}` : '';
    back.title = level ? `返回 ${parentOf(level) || '一级文件夹'}` : '';

    for (const button of folderButtons()) {
      const path = normalize(button.dataset.folder);
      const visible = parentOf(path) === level;
      button.classList.toggle('lh-tree-visible', visible);
      button.classList.toggle('lh-current-branch', !level && !!branch && firstPart(path) === branch);
      button.style.display = visible ? '' : 'none';
      if (visible) button.dataset.hasChildren = hasChildren(path) ? '1' : '0';
      else delete button.dataset.hasChildren;
    }
  }

  function queueRender() {
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(renderFolders);
  }

  function setLevel(path) {
    level = normalize(path);
    clearTimeout(resetTimer);
    queueRender();
  }

  function scheduleRootReset() {
    clearTimeout(resetTimer);
    if (document.body.classList.contains('move-mode')) return;
    resetTimer = window.setTimeout(() => setLevel(''), ROOT_RESET_MS);
  }

  folderNav.addEventListener('mouseenter', () => clearTimeout(resetTimer));
  folderNav.addEventListener('mouseleave', scheduleRootReset);
  folderNav.addEventListener('click', e => {
    const button = e.target.closest('button[data-folder]');
    if (!button) return;
    const path = normalize(button.dataset.folder);
    window.setTimeout(() => {
      if (hasChildren(path)) setLevel(path);
      else {
        level = parentOf(path);
        queueRender();
      }
    }, 0);
  });

  document.querySelectorAll('.main-nav button').forEach(button => {
    button.addEventListener('click', () => {
      if (button.dataset.route === 'root' || button.dataset.route === 'home') setLevel('');
    });
  });

  const folderObserver = new MutationObserver(() => queueRender());
  folderObserver.observe(folderNav, {childList:true, subtree:true});

  function clearDwell() {
    clearTimeout(dwellTimer);
    dwellTimer = 0;
    dwellPath = '';
  }

  document.addEventListener('pointermove', e => {
    if (!document.body.classList.contains('move-mode')) {
      clearDwell();
      return;
    }
    clearTimeout(resetTimer);
    const hit = document.elementFromPoint(e.clientX, e.clientY);
    const button = hit?.closest?.('#folderNav button[data-folder]');
    const path = normalize(button?.dataset.folder || '');
    if (!path || !hasChildren(path)) {
      clearDwell();
      return;
    }
    if (path === dwellPath && dwellTimer) return;
    clearDwell();
    dwellPath = path;
    button.classList.add('lh-dwell-target');
    dwellTimer = window.setTimeout(() => {
      folderButtons().forEach(node => node.classList.remove('lh-dwell-target'));
      if (!document.body.classList.contains('move-mode') || dwellPath !== path) return;
      setLevel(path);
      folderNav.classList.add('lh-drill-disarm');
      window.setTimeout(() => folderNav.classList.remove('lh-drill-disarm'), 140);
      clearDwell();
    }, DRILL_DWELL_MS);
  }, true);

  document.addEventListener('pointerup', () => {
    folderButtons().forEach(node => node.classList.remove('lh-dwell-target'));
    clearDwell();
    window.setTimeout(() => {
      if (!document.body.classList.contains('move-mode')) scheduleRootReset();
    }, 0);
  }, true);
  document.addEventListener('pointercancel', clearDwell, true);

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

  const style = document.createElement('style');
  style.id = 'lhStable2Styles';
  style.textContent = `
    #folderNav .lh-folder-tree-back{display:flex;width:100%;align-items:center;border:0;background:transparent;color:#777780;border-radius:8px;text-align:left;cursor:pointer;padding:8px 9px;margin-bottom:3px;font-size:10px}
    #folderNav .lh-folder-tree-back:hover{background:#1d1d20;color:#fff}
    #folderNav button.lh-tree-visible{padding-left:9px!important}
    #folderNav button.lh-tree-visible[data-has-children="1"]::after{content:'›';margin-left:auto;color:#666;font-size:14px}
    #folderNav button.lh-current-branch:not(.active){background:#171719;color:#d1d1d5}
    #folderNav button.lh-dwell-target{border:1px solid #7b5724!important;background:#241b10!important;color:#ffd18a!important}
    #folderNav.lh-drill-disarm button[data-folder]{pointer-events:none!important}
  `;
  document.head.appendChild(style);

  renderFolders();
  reportPlayback(viewer.open);
  queueVisibleCovers();
})();
