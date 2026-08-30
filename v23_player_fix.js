(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const video = $('#videoPlayer');
  const seekBar = $('#seekBar');
  const currentTime = $('#currentTime');
  const durationTime = $('#durationTime');
  const viewer = $('#viewer');
  const compatBtn = $('#compatBtn');
  const notice = $('#playerNotice');
  const noticeTitle = $('#playerNoticeTitle');
  const noticeText = $('#playerNoticeText');
  const diagnostics = $('#mediaDiagnostics');
  const pathNode = $('#viewerPath');
  const toastNode = $('#toast');

  document.documentElement.dataset.interactionFix = '2.4-probe-failfast';

  // LocalHub is already reading local files. Hide browser download/export
  // affordances so playback behaves like a library player rather than a web
  // download page. This removes Chromium's media-menu Download item, blocks the
  // video context menu/drag-out path, and keeps the media inline.
  function enforceNoDownload() {
    if (!video) return;
    video.setAttribute('controlslist', 'nodownload noremoteplayback');
    video.controlsList?.add?.('nodownload');
    video.controlsList?.add?.('noremoteplayback');
    video.disableRemotePlayback = true;
    video.disablePictureInPicture = true;
    video.setAttribute('draggable', 'false');
  }
  enforceNoDownload();
  video?.addEventListener('loadedmetadata', enforceNoDownload);
  video?.addEventListener('contextmenu', event => { event.preventDefault(); event.stopPropagation(); });
  video?.addEventListener('dragstart', event => event.preventDefault());
  window.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 's') {
      event.preventDefault();
      toast('LocalHub 是本地媒体库，无需下载');
    }
  }, true);

  // Media diagnostics are useful, but they are never allowed to hold the player
  // hostage. smart_ui calls the global fetch binding at request time, so this
  // small guard gives only /api/media/probe a strict browser-side deadline.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function localHubFetch(input, init = {}) {
    const url = typeof input === 'string' ? input : String(input?.url || '');
    if (!url.includes('/api/media/probe')) return nativeFetch(input, init);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3500);
    const upstream = init?.signal;
    if (upstream) {
      if (upstream.aborted) controller.abort();
      else upstream.addEventListener('abort', () => controller.abort(), {once:true});
    }
    return nativeFetch(input, {...init, signal:controller.signal}).finally(() => clearTimeout(timer));
  };

  let diagnosticsTimer = null;
  function armDiagnosticsDeadline() {
    clearTimeout(diagnosticsTimer);
    diagnosticsTimer = setTimeout(() => {
      if (!viewer?.open) return;
      const text = (diagnostics?.textContent || '').trim();
      if (/正在读取媒体信息|正在获取媒体信息|诊断失败.*abort/i.test(text)) {
        diagnostics.textContent = '媒体诊断暂未返回 · 不影响直接播放';
      }
      const title = (noticeTitle?.textContent || '').trim();
      if ((video?.currentSrc || video?.src) && /正在分析媒体|正在分析/.test(title)) {
        notice?.classList.add('hidden');
      }
    }, 3800);
  }
  if (pathNode) {
    new MutationObserver(armDiagnosticsDeadline).observe(pathNode, {subtree:true,childList:true,characterData:true});
  }
  video?.addEventListener('loadedmetadata', () => {
    const title = (noticeTitle?.textContent || '').trim();
    if (/正在分析媒体|正在分析/.test(title)) notice?.classList.add('hidden');
  });
  viewer?.addEventListener('close', () => clearTimeout(diagnosticsTimer));

  function toast(message) {
    if (!toastNode || !message) return;
    toastNode.textContent = message;
    toastNode.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => toastNode.classList.remove('show'), 1800);
  }

  async function api(url, opt = {}) {
    const response = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  // -----------------------------------------------------------------------
  // One drag implementation only.
  // v23_features has an older document-level drag handler. These window-capture
  // handlers intercept video-card pointer events before that legacy handler so
  // only this cleaned-up state machine runs.
  // -----------------------------------------------------------------------
  let armedDrag = null;
  let suppressClickUntil = 0;

  function sourceFolder(path) {
    const parts = String(path || '').replace(/\\/g, '/').split('/');
    parts.pop();
    return parts.join('/');
  }

  function markCardMediaNonDraggable(root = document) {
    root.querySelectorAll?.('.card[data-id] img').forEach(img => {
      img.draggable = false;
      img.setAttribute('draggable', 'false');
    });
  }

  const grid = $('#grid');
  if (grid) {
    new MutationObserver(records => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeType === 1) markCardMediaNonDraggable(node);
        }
      }
    }).observe(grid, {childList:true});
  }
  markCardMediaNonDraggable();

  window.addEventListener('dragstart', event => {
    if (event.target?.closest?.('.card[data-id]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  function draggableCardFrom(target) {
    const card = target?.closest?.('.card[data-id]');
    if (!card?.querySelector('.video-thumb')) return null;
    if (target.closest?.('button,input,select,a,[contenteditable="true"]')) return null;
    return card;
  }

  function clearDropTargets() {
    $$('.v23-drop-hover').forEach(node => node.classList.remove('v23-drop-hover'));
  }

  function dropTargetAt(x, y, path) {
    const node = document.elementFromPoint(x, y)?.closest?.('.folder-nav button,.main-nav button[data-route="root"]');
    if (!node) return null;
    const folder = node.matches('.main-nav button[data-route="root"]') ? '' : (node.dataset.folder ?? null);
    if (folder == null || folder === sourceFolder(path)) return null;
    return {node, folder};
  }

  function cleanDrag(state = armedDrag, suppressClick = false) {
    if (!state) return;
    clearTimeout(state.timer);
    state.card?.classList.remove('v23-dragging');
    state.ghost?.remove();
    clearDropTargets();
    document.body.classList.remove('v23-is-dragging');
    if (armedDrag === state) armedDrag = null;
    if (suppressClick) suppressClickUntil = Date.now() + 650;
  }

  function positionDrag(state, x, y) {
    if (state.ghost) state.ghost.style.transform = `translate3d(${x + 14}px,${y + 14}px,0)`;
    clearDropTargets();
    state.target = dropTargetAt(x, y, state.path);
    state.target?.node?.classList.add('v23-drop-hover');
  }

  function activateDrag(state, x, y) {
    if (!state || armedDrag !== state || state.active) return;
    state.active = true;
    clearTimeout(state.timer);
    document.body.classList.add('v23-is-dragging');
    state.card.classList.add('v23-dragging');
    state.card.dispatchEvent(new Event('mouseleave'));
    const ghost = document.createElement('div');
    ghost.className = 'v23-drag-ghost';
    ghost.textContent = state.card.querySelector('.card-title')?.textContent || '视频';
    document.body.appendChild(ghost);
    state.ghost = ghost;
    positionDrag(state, x, y);
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
      const exposure = JSON.parse(localStorage.getItem('localhub:recommend-exposure') || '{}');
      if (exposure[oldId]) {
        exposure[newId] = exposure[oldId];
        delete exposure[oldId];
        localStorage.setItem('localhub:recommend-exposure', JSON.stringify(exposure));
      }
    } catch {}
  }

  async function finishMove(path, folder, card) {
    try {
      const data = await api('/api/manage', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'move', paths:[path], folder, create:false})
      });
      const moved = data.moved?.[0];
      if (!moved) throw new Error('移动失败');
      migrateLocalState(path, moved.new);
      card?.remove();
      toast(`已移动到 ${folder || '根目录'}`);
      api('/api/smart/rescan').then(() => {
        const activeFolder = $('.folder-nav button.active');
        const activeRoute = $('.main-nav button.active');
        if (activeFolder) activeFolder.click();
        else if (activeRoute) activeRoute.click();
      }).catch(() => {});
    } catch (error) {
      toast(error.message || '移动失败');
    }
  }

  window.addEventListener('pointerdown', event => {
    const card = draggableCardFrom(event.target);
    if (!card) return;
    event.stopPropagation();
    const state = {
      card,
      path: card.dataset.id,
      pointerId: event.pointerId,
      pointerType: event.pointerType || 'mouse',
      startX: event.clientX,
      startY: event.clientY,
      active: false,
      target: null,
      ghost: null,
      timer: null,
    };
    armedDrag = state;
    const delay = state.pointerType === 'touch' ? 360 : 180;
    state.timer = setTimeout(() => activateDrag(state, state.startX, state.startY), delay);
  }, true);

  window.addEventListener('pointermove', event => {
    const state = armedDrag;
    if (!state || state.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const distance = Math.hypot(event.clientX - state.startX, event.clientY - state.startY);
    if (!state.active) {
      if (state.pointerType === 'touch') {
        if (distance > 12) cleanDrag(state, false);
        return;
      }
      if (distance > 6) activateDrag(state, event.clientX, event.clientY);
      else return;
    }
    event.preventDefault();
    positionDrag(state, event.clientX, event.clientY);
  }, true);

  window.addEventListener('pointerup', event => {
    const state = armedDrag;
    if (!state || state.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const target = state.active ? (dropTargetAt(event.clientX, event.clientY, state.path) || state.target) : null;
    const wasActive = state.active;
    if (wasActive) event.preventDefault();
    cleanDrag(state, wasActive);
    if (wasActive && target?.folder != null) finishMove(state.path, target.folder, state.card);
  }, true);

  const cancelActiveDrag = () => {
    const state = armedDrag;
    if (state) cleanDrag(state, !!state.active);
  };
  window.addEventListener('pointercancel', cancelActiveDrag, true);
  window.addEventListener('blur', cancelActiveDrag);
  document.addEventListener('visibilitychange', () => { if (document.hidden) cancelActiveDrag(); });
  window.addEventListener('keydown', event => { if (event.key === 'Escape') cancelActiveDrag(); }, true);
  window.addEventListener('click', event => {
    if (Date.now() < suppressClickUntil) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  // -----------------------------------------------------------------------
  // Timeline scrubbing: UI-only while dragging, exactly one real seek on commit.
  // Failure is surfaced to the user; it NEVER starts hidden transcoding.
  // -----------------------------------------------------------------------
  if (!video || !seekBar || !currentTime) return;

  let scrubbing = false;
  let scrubValue = Number(seekBar.value) || 0;
  let seekGeneration = 0;
  let seekCleanup = null;
  let lastCommitAt = 0;
  let lastCommitTarget = -1;

  function parseClock(text) {
    const parts = String(text || '').trim().split(':').map(Number);
    if (!parts.length || parts.some(v => !Number.isFinite(v))) return 0;
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return parts[0] || 0;
  }

  function mediaDuration() {
    if (Number.isFinite(video.duration) && video.duration > 0) return video.duration;
    return parseClock(durationTime?.textContent);
  }

  function formatClock(sec) {
    sec = Math.max(0, Number(sec) || 0);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    return h ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` : `${m}:${String(s).padStart(2,'0')}`;
  }

  function scrubTarget() {
    const duration = mediaDuration();
    return duration > 0 ? duration * Math.max(0, Math.min(1000, scrubValue)) / 1000 : 0;
  }

  function paintScrubPreview() {
    currentTime.textContent = formatClock(scrubTarget());
  }

  function cancelSeekMonitor() {
    seekGeneration++;
    if (seekCleanup) { seekCleanup(); seekCleanup = null; }
  }

  function recommendCompat(reason) {
    if (!viewer?.open) return;
    compatBtn?.classList.add('recommended');
    if (noticeTitle) noticeTitle.textContent = '当前文件定位不稳定';
    if (noticeText) noticeText.textContent = `${reason}。可以手动选择“兼容播放”或系统播放器。`;
    notice?.classList.remove('hidden');
    toast('当前视频定位不稳定');
  }

  function monitorSeek(target) {
    cancelSeekMonitor();
    const generation = seekGeneration;
    const duration = mediaDuration();
    const tolerance = Math.max(2, Math.min(8, duration * 0.004));
    let timer = null;
    const cleanup = () => {
      if (timer) clearTimeout(timer);
      video.removeEventListener('seeked', onSeeked);
      video.removeEventListener('error', onError);
    };
    const onSeeked = () => {
      if (generation !== seekGeneration) return cleanup();
      const delta = Math.abs((video.currentTime || 0) - target);
      cleanup(); seekCleanup = null;
      if (delta > tolerance) recommendCompat('浏览器实际定位位置与目标偏差较大');
    };
    const onError = () => {
      if (generation !== seekGeneration) return cleanup();
      cleanup(); seekCleanup = null;
      recommendCompat('浏览器在定位时发生解码错误');
    };
    video.addEventListener('seeked', onSeeked);
    video.addEventListener('error', onError);
    timer = setTimeout(() => {
      if (generation !== seekGeneration) return;
      const stillStuck = video.seeking || (video.readyState < 2 && !video.paused);
      cleanup(); seekCleanup = null;
      if (stillStuck) recommendCompat('浏览器定位超过 8 秒仍未完成');
    }, 8000);
    seekCleanup = cleanup;
  }

  function commitSeek() {
    const duration = mediaDuration();
    if (!(duration > 0)) { scrubbing = false; return; }
    const target = scrubTarget();
    const now = performance.now();
    scrubbing = false;
    if (Math.abs(target - lastCommitTarget) < 0.05 && now - lastCommitAt < 300) return;
    lastCommitTarget = target;
    lastCommitAt = now;
    try {
      video.currentTime = target;
      monitorSeek(target);
    } catch {
      recommendCompat('浏览器拒绝定位到这个时间点');
    }
  }

  window.addEventListener('pointerdown', event => {
    if (event.target !== seekBar) return;
    event.stopPropagation();
    scrubbing = true;
    scrubValue = Number(seekBar.value) || 0;
  }, true);

  window.addEventListener('input', event => {
    if (event.target !== seekBar) return;
    event.stopPropagation();
    event.stopImmediatePropagation();
    scrubbing = true;
    scrubValue = Number(seekBar.value) || 0;
    paintScrubPreview();
  }, true);

  window.addEventListener('change', event => {
    if (event.target !== seekBar) return;
    event.stopPropagation();
    event.stopImmediatePropagation();
    scrubValue = Number(seekBar.value) || 0;
    paintScrubPreview();
    commitSeek();
  }, true);

  window.addEventListener('pointerup', event => {
    if (event.target !== seekBar || !scrubbing) return;
    setTimeout(() => { if (scrubbing) commitSeek(); }, 0);
  }, true);

  video.addEventListener('loadedmetadata', cancelSeekMonitor);
  viewer?.addEventListener('close', () => {
    scrubbing = false;
    cancelSeekMonitor();
    cancelActiveDrag();
  });
})();
