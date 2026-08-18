(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const video = $('#videoPlayer');
  const stage = $('#viewerStage');
  const viewer = $('#viewer');
  const pathNode = $('#viewerPath');
  const notice = $('#playerNotice');
  const noticeTitle = $('#playerNoticeTitle');
  const noticeText = $('#playerNoticeText');
  const progress = $('#compatProgress');
  const mode = $('#playMode');
  const toastNode = $('#toast');
  if (!video || !stage || !viewer || !mode) return;

  let probeToken = 0;
  let lastPassive = '';

  function toast(message) {
    if (!toastNode || !message) return;
    toastNode.textContent = message;
    toastNode.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => toastNode.classList.remove('show'), 2200);
  }

  function setOrientation(width, height, rotation = 0) {
    width = Number(width) || 0;
    height = Number(height) || 0;
    const r = Math.abs(Math.round(Number(rotation) || 0)) % 180;
    if (r === 90) [width, height] = [height, width];
    if (!width || !height) return;
    const portrait = height > width * 1.08;
    stage.classList.toggle('v23-video-portrait', portrait);
    stage.classList.toggle('v23-video-landscape', !portrait);
    stage.style.setProperty('--v23-video-ratio', `${width} / ${height}`);
  }

  function fitFromVideo() {
    if (video.videoWidth && video.videoHeight) setOrientation(video.videoWidth, video.videoHeight, 0);
  }

  async function fitFromProbe() {
    const path = (pathNode?.textContent || '').trim();
    if (!path) return;
    const token = ++probeToken;
    try {
      const r = await fetch(`/api/media/probe?path=${encodeURIComponent(path)}`, {cache:'no-store'});
      if (!r.ok) return;
      const data = await r.json();
      if (token !== probeToken || !viewer.open || (pathNode?.textContent || '').trim() !== path) return;
      const p = data.probe || {};
      setOrientation(p.displayWidth || p.width, p.displayHeight || p.height, p.rotation || 0);
    } catch {}
  }

  function passiveLabel(title, text) {
    if (/准备兼容封装|正在准备兼容封装/.test(title)) return '正在无损封装';
    if (/兼容封装/.test(title)) return '正在无损封装';
    if (/准备兼容播放|正在准备兼容播放/.test(title)) return '正在准备兼容播放';
    if (/正在转为兼容格式|正在转/.test(title)) return '正在兼容转码';
    if (/正在分析媒体|正在分析/.test(title)) return '分析媒体';
    if (/兼容播放失败/.test(title)) return '兼容失败';
    if (/兼容/.test(text) && /准备|转码|封装/.test(text)) return '兼容处理中';
    return '';
  }

  function mirrorPassiveNotice() {
    if (!notice || notice.classList.contains('hidden')) return;
    const title = (noticeTitle?.textContent || '').trim();
    const text = (noticeText?.textContent || '').trim();
    const label = passiveLabel(title, text);
    if (!label) return;

    let pct = '';
    const bar = progress?.querySelector('i');
    const width = bar?.style.width || '';
    if (/^\d+(?:\.\d+)?%$/.test(width) && width !== '0%') pct = ` ${Math.round(parseFloat(width))}%`;
    mode.textContent = label + pct;
    mode.classList.add('v23-mode-busy');
    mode.classList.toggle('v23-mode-error', label === '兼容失败');
    notice.classList.add('v23-passive-notice');

    if (label === '兼容失败' && lastPassive !== `${title}|${text}`) toast(text || title);
    lastPassive = `${title}|${text}`;
  }

  function clearBusyWhenSettled() {
    const text = (mode.textContent || '').trim();
    if (/^(原生|兼容封装|兼容转码)$/.test(text)) {
      mode.classList.remove('v23-mode-busy','v23-mode-error');
      notice?.classList.remove('v23-passive-notice');
    }
  }

  async function openRecommendationDirect(card) {
    const id = card?.dataset.recId || '';
    const name = (card?.querySelector('.v23-rec-title')?.textContent || '').trim();
    if (!id || !name) return;
    $('#closeViewer')?.click();
    await sleep(55);
    const input = $('#searchInput');
    if (!input) return;
    input.value = name;
    input.dispatchEvent(new Event('input',{bubbles:true}));
    const deadline = Date.now() + 4500;
    while (Date.now() < deadline) {
      const target = $$('.card[data-id]').find(node => node.dataset.id === id);
      if (target) { target.click(); return; }
      await sleep(90);
    }
    toast('暂时无法打开这个推荐视频');
  }

  document.addEventListener('click', e => {
    const card = e.target.closest?.('.v23-rec-card');
    if (!card) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    openRecommendationDirect(card);
  }, true);

  video.addEventListener('loadedmetadata', () => {
    fitFromVideo();
    requestAnimationFrame(fitFromVideo);
  });
  video.addEventListener('loadeddata', fitFromVideo);
  video.addEventListener('resize', fitFromVideo);

  if (pathNode) {
    new MutationObserver(() => {
      stage.classList.remove('v23-video-portrait','v23-video-landscape');
      fitFromProbe();
    }).observe(pathNode, {subtree:true,childList:true,characterData:true});
  }
  if (notice) new MutationObserver(mirrorPassiveNotice).observe(notice, {subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class','style']});
  if (progress) new MutationObserver(mirrorPassiveNotice).observe(progress, {subtree:true,attributes:true,attributeFilter:['style','class']});
  new MutationObserver(clearBusyWhenSettled).observe(mode, {subtree:true,childList:true,characterData:true});
  viewer.addEventListener('close', () => {
    probeToken++;
    stage.classList.remove('v23-video-portrait','v23-video-landscape');
    notice?.classList.remove('v23-passive-notice');
    mode.classList.remove('v23-mode-busy','v23-mode-error');
  });

  fitFromProbe();
})();

(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const toast = message => {
    const node = $('#toast');
    if (!node || !message) return;
    node.textContent = message;
    node.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => node.classList.remove('show'), 1800);
  };
  const api = async (url, opt = {}) => {
    const response = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };

  document.documentElement.dataset.interactionFix = '2.3.2';

  // Native browser image dragging was racing LocalHub's pointer drag. Disable it
  // and intercept pointer events at window-capture before the old document drag.
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
      // Do the index refresh only after the drag UI is gone and responsive.
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
      timer: null
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
        if (distance > 12) { cleanDrag(state, false); return; }
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
    if (!state) return;
    cleanDrag(state, !!state.active);
  };
  window.addEventListener('pointercancel', cancelActiveDrag, true);
  window.addEventListener('blur', cancelActiveDrag);
  document.addEventListener('visibilitychange', () => { if (document.hidden) cancelActiveDrag(); });
  window.addEventListener('keydown', event => { if (event.key === 'Escape' && armedDrag) cancelActiveDrag(); }, true);
  window.addEventListener('click', event => {
    if (Date.now() < suppressClickUntil) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  // Timeline scrubbing: the thumb may emit dozens of input events per second.
  // Only paint a lightweight preview while dragging and perform one actual seek
  // after release. This also bypasses the old 650 ms false-positive compat switch.
  const video = $('#videoPlayer');
  const seekBar = $('#seekBar');
  const currentTime = $('#currentTime');
  const durationTime = $('#durationTime');
  const compatBtn = $('#compatBtn');
  const playMode = $('#playMode');
  const viewer = $('#viewer');
  if (!video || !seekBar || !currentTime) return;

  let scrubbing = false;
  let scrubValue = Number(seekBar.value) || 0;
  let seekGeneration = 0;
  let seekCleanup = null;
  let lastPreview = '';
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
    const label = formatClock(scrubTarget());
    if (label !== lastPreview && currentTime.textContent !== label) currentTime.textContent = label;
    lastPreview = label;
    const value = String(Math.round(scrubValue));
    if (String(seekBar.value) !== value) seekBar.value = value;
  }

  function cancelSeekMonitor() {
    seekGeneration++;
    if (seekCleanup) { seekCleanup(); seekCleanup = null; }
  }

  function isCompatMode() {
    return playMode?.classList.contains('compat') || /兼容/.test(playMode?.textContent || '');
  }

  function autoCompat(reason) {
    if (!viewer?.open || !compatBtn || compatBtn.disabled || isCompatMode()) return;
    toast(`原生拖动失败，正在自动兼容播放${reason ? ` · ${reason}` : ''}`);
    compatBtn.click();
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
      if (!isCompatMode() && delta > tolerance) autoCompat('定位偏差过大');
    };
    const onError = () => {
      if (generation !== seekGeneration) return cleanup();
      cleanup(); seekCleanup = null;
      autoCompat('浏览器解码失败');
    };
    video.addEventListener('seeked', onSeeked);
    video.addEventListener('error', onError);
    timer = setTimeout(() => {
      if (generation !== seekGeneration) return;
      const stillStuck = video.seeking || (video.readyState < 2 && !video.paused);
      cleanup(); seekCleanup = null;
      if (!isCompatMode() && stillStuck) autoCompat('定位超时');
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
    lastCommitTarget = target; lastCommitAt = now;
    try {
      video.currentTime = target;
      monitorSeek(target);
    } catch {
      autoCompat('浏览器拒绝定位');
    }
  }

  window.addEventListener('pointerdown', event => {
    if (event.target !== seekBar) return;
    scrubbing = true;
    scrubValue = Number(seekBar.value) || 0;
    lastPreview = '';
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

  video.addEventListener('timeupdate', () => {
    if (scrubbing) paintScrubPreview();
  });
  video.addEventListener('loadedmetadata', cancelSeekMonitor);
  viewer?.addEventListener('close', () => { scrubbing = false; cancelSeekMonitor(); });
})();
