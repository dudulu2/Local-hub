(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const video = $('#videoPlayer');
  const viewer = $('#viewer');
  const stage = $('#viewerStage');
  const pathNode = $('#viewerPath');
  const playBtn = $('#playBtn');
  const compatBtn = $('#compatBtn');
  const systemBtn = $('#systemPlayerBtn');
  const playMode = $('#playMode');
  if (!video || !viewer || !stage || !pathNode) return;

  let probeToken = 0;
  let currentProbe = null;
  let recHover = null;
  let recHoverToken = 0;

  function toast(message) {
    const node = $('#toast');
    if (!node || !message) return;
    node.textContent = message;
    node.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => node.classList.remove('show'), 2200);
  }

  async function json(url, opt = {}) {
    const response = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function currentPath() {
    return (pathNode.textContent || '').trim();
  }

  // The video surface itself behaves like a normal web player: click toggles
  // play/pause. Controls keep their own handlers and are not affected.
  video.style.cursor = 'pointer';
  video.addEventListener('click', event => {
    if (event.button && event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    if (!video.currentSrc && !video.src) return;
    if (video.paused || video.ended) video.play().catch(() => {});
    else video.pause();
  });

  video.addEventListener('dblclick', event => {
    event.preventDefault();
    if (document.fullscreenElement) document.exitFullscreen?.();
    else stage.requestFullscreen?.();
  });

  function applyOrientation(width, height) {
    width = Number(width) || 0;
    height = Number(height) || 0;
    if (!width || !height) return;
    const portrait = height > width * 1.08;
    viewer.classList.toggle('lh-player-portrait', portrait);
    viewer.classList.toggle('lh-player-landscape', !portrait);
    stage.classList.toggle('lh-stage-portrait', portrait);
    stage.style.setProperty('--lh-media-aspect', `${width}/${height}`);
  }

  function fromIntrinsicSize() {
    if (video.videoWidth && video.videoHeight) applyOrientation(video.videoWidth, video.videoHeight);
  }

  async function refreshProbe() {
    const path = currentPath();
    const token = ++probeToken;
    currentProbe = null;
    viewer.classList.remove('lh-system-preferred');
    systemBtn?.classList.remove('lh-recommended');
    if (!path) return;
    try {
      const data = await json(`/api/media/probe?path=${encodeURIComponent(path)}`);
      if (token !== probeToken || !viewer.open || currentPath() !== path) return;
      const p = data.probe || {};
      currentProbe = p;
      applyOrientation(p.displayWidth || p.width, p.displayHeight || p.height);
      if (p.systemPreferred || p.autoCompatBlocked) {
        viewer.classList.add('lh-system-preferred');
        systemBtn?.classList.add('lh-recommended');
        if (playMode) playMode.textContent = '大型媒体 · 系统播放优先';
        if (compatBtn) compatBtn.textContent = '系统播放器';
      } else if (compatBtn) {
        compatBtn.textContent = '兼容播放';
      }
    } catch {}
  }

  video.addEventListener('loadedmetadata', () => {
    fromIntrinsicSize();
    requestAnimationFrame(fromIntrinsicSize);
  });
  video.addEventListener('loadeddata', fromIntrinsicSize);
  video.addEventListener('resize', fromIntrinsicSize);

  // Large TS / huge transcode-required files are intentionally routed to the
  // Windows-associated player instead of launching a multi-gigabyte background
  // conversion from an innocent button click.
  compatBtn?.addEventListener('click', event => {
    if (!viewer.classList.contains('lh-system-preferred')) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    systemBtn?.click();
  }, true);

  async function cancelCompat(path) {
    if (!path) return;
    try {
      await fetch('/api/compat/cancel', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({path}),
        cache:'no-store',
        keepalive:true,
      });
    } catch {}
  }

  let lastPath = '';
  const inspectPath = () => {
    const next = currentPath();
    if (lastPath && next && lastPath !== next) cancelCompat(lastPath);
    lastPath = next;
    viewer.classList.remove('lh-player-portrait','lh-player-landscape','lh-system-preferred');
    stage.classList.remove('lh-stage-portrait');
    if (next) setTimeout(refreshProbe, 10);
  };
  new MutationObserver(inspectPath).observe(pathNode, {subtree:true,childList:true,characterData:true});

  viewer.addEventListener('close', () => {
    const path = currentPath() || lastPath;
    probeToken++;
    cancelCompat(path);
    stopRecHover(true);
    viewer.classList.remove('lh-player-portrait','lh-player-landscape','lh-system-preferred');
    stage.classList.remove('lh-stage-portrait');
    if (compatBtn) compatBtn.textContent = '兼容播放';
  });
  addEventListener('pagehide', () => cancelCompat(currentPath() || lastPath));

  // Recommendation cards are rendered outside smart_ui.js, so they never got
  // the homepage hover binding. Bind them here to the interactive low-priority
  // preview endpoint. Only one recommendation hover runs at a time.
  function stopRecHover(restore = true) {
    recHoverToken++;
    const state = recHover;
    recHover = null;
    if (!state) return;
    clearTimeout(state.timer);
    state.controller?.abort();
    if (restore && state.img?.isConnected && state.base) state.img.src = state.base;
    state.card?.classList.remove('lh-rec-previewing');
    for (const url of state.urls || []) URL.revokeObjectURL(url);
  }

  async function recFrame(state, slot, token) {
    if (!state.card.matches(':hover') || recHover !== state || token !== recHoverToken) return null;
    const controller = new AbortController();
    state.controller = controller;
    try {
      const response = await fetch(`/api/smart/hover-interactive?path=${encodeURIComponent(state.path)}&slot=${slot}`, {
        cache:'no-store', signal:controller.signal
      });
      if (response.status === 204 || !response.ok) return null;
      const blob = await response.blob();
      if (recHover !== state || token !== recHoverToken || !state.card.matches(':hover')) return null;
      return URL.createObjectURL(blob);
    } catch { return null; }
    finally { if (state.controller === controller) state.controller = null; }
  }

  function startRecHover(card) {
    const path = card.dataset.recId || '';
    const img = card.querySelector('img[data-rec-thumb]');
    if (!path || !img) return;
    stopRecHover(true);
    const state = {card,path,img,base:img.src || '',urls:[],controller:null,timer:null};
    recHover = state;
    const token = ++recHoverToken;
    state.timer = setTimeout(async () => {
      if (recHover !== state || token !== recHoverToken || !card.matches(':hover')) return;
      const frames = [];
      // Three representative frames are enough to feel alive and keep explicit
      // recommendation hover far lighter than the normal six-frame browser grid.
      for (const slot of [0, 3, 5]) {
        const url = await recFrame(state, slot, token);
        if (!url) continue;
        state.urls.push(url); frames.push(url);
        img.src = url; card.classList.add('lh-rec-previewing');
        try { await img.decode(); } catch {}
        await new Promise(resolve => state.timer = setTimeout(resolve, 360));
      }
      if (frames.length < 2) return;
      let index = 0;
      while (recHover === state && token === recHoverToken && card.matches(':hover')) {
        img.src = frames[index++ % frames.length];
        await new Promise(resolve => state.timer = setTimeout(resolve, 620));
      }
    }, 520);
  }

  function bindRecCards(root = document) {
    root.querySelectorAll?.('.v23-rec-card:not([data-lh-hover-bound])').forEach(card => {
      card.dataset.lhHoverBound = '1';
      const img = card.querySelector('img[data-rec-thumb]');
      if (img) {
        img.addEventListener('load', () => {
          if (!card.classList.contains('lh-rec-previewing') && img.src) img.dataset.lhBaseRec = img.src;
        });
      }
      card.addEventListener('mouseenter', () => {
        const image = card.querySelector('img[data-rec-thumb]');
        if (image?.dataset.lhBaseRec) image.src = image.dataset.lhBaseRec;
        startRecHover(card);
      });
      card.addEventListener('mouseleave', () => stopRecHover(true));
    });
  }

  const recGrid = $('#recommendGrid');
  if (recGrid) {
    new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) if (node.nodeType === 1) bindRecCards(node);
      bindRecCards(recGrid);
    }).observe(recGrid, {childList:true});
    bindRecCards(recGrid);
  }

  inspectPath();
})();
