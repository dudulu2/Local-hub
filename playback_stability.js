(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const video = $('#videoPlayer');
  const viewer = $('#viewer');
  const stage = $('#viewerStage');
  const pathNode = $('#viewerPath');
  const compatBtn = $('#compatBtn');
  const systemBtn = $('#systemPlayerBtn');
  const playMode = $('#playMode');
  const notice = $('#playerNotice');
  const noticeTitle = $('#playerNoticeTitle');
  const noticeText = $('#playerNoticeText');
  const compatProgress = $('#compatProgress');
  if (!video || !viewer || !stage || !pathNode) return;

  // Even MP4/MOV are held until LocalHub has inspected their timeline. A file
  // with a familiar extension can still contain missing/unstable timestamps and
  // wedge Chromium before the normal async probe has a chance to react.
  const GATED_EXTS = new Set(['mp4','m4v','mov','avi','mpg','mpeg','ts','mkv','ogv']);

  let probeToken = 0;
  let currentProbe = null;
  let gatePath = '';
  let gatePending = false;
  let gateHolding = false;
  let lastPath = '';
  let recHover = null;
  let recHoverToken = 0;
  let forcedCompatToken = 0;
  let forcedCompatTimer = null;
  let runtimeFallbackAt = 0;
  let lastMediaTime = 0;
  let lastWallTime = 0;
  let lastSeekAt = 0;
  let timelineAnomalies = [];
  let stallEvents = [];

  function toast(message) {
    const node = $('#toast');
    if (!node || !message) return;
    node.textContent = message;
    node.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => node.classList.remove('show'), 2400);
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

  function extOf(path) {
    const name = String(path || '').split('/').pop() || '';
    const dot = name.lastIndexOf('.');
    return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
  }

  function mediaUrl(path) {
    return '/media/' + String(path || '').split('/').map(part => encodeURIComponent(part)).join('/');
  }

  function isDirectSource() {
    const src = video.currentSrc || video.src || '';
    return src.includes('/media/');
  }

  function isCompatSource() {
    const src = video.currentSrc || video.src || '';
    return src.includes('/api/compat/file');
  }

  function showPlayerNotice(title, text = '', progress = null) {
    if (!notice) return;
    if (noticeTitle) noticeTitle.textContent = title;
    if (noticeText) noticeText.textContent = text;
    notice.classList.remove('hidden');
    if (compatProgress) {
      if (progress == null) compatProgress.classList.add('hidden');
      else {
        compatProgress.classList.remove('hidden');
        const bar = compatProgress.querySelector('i');
        if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(progress) || 0))}%`;
      }
    }
  }

  function resetWatchdog() {
    lastMediaTime = Number(video.currentTime) || 0;
    lastWallTime = performance.now();
    lastSeekAt = performance.now();
    timelineAnomalies = [];
    stallEvents = [];
  }

  // Stop the direct browser source without closing the viewer. The original
  // smart_ui loadedmetadata listener remains attached, so a later approved
  // source still restores watch progress normally.
  function holdNativeSource() {
    if (gateHolding || !isDirectSource()) return;
    gateHolding = true;
    try {
      video.pause();
      video.removeAttribute('src');
      video.load();
    } catch {}
    finally { gateHolding = false; }
  }

  function approveNative(path, token) {
    if (token !== probeToken || currentPath() !== path || !viewer.open) return;
    gatePending = false;
    gatePath = path;
    if (isCompatSource() || isDirectSource()) return;
    try {
      video.src = mediaUrl(path);
      video.load();
    } catch {}
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

    gatePath = path;
    gatePending = GATED_EXTS.has(extOf(path));
    if (gatePending) holdNativeSource();

    try {
      const data = await json(`/api/media/probe?path=${encodeURIComponent(path)}`);
      if (token !== probeToken || !viewer.open || currentPath() !== path) return;
      const p = data.probe || {};
      currentProbe = p;
      applyOrientation(p.displayWidth || p.width, p.displayHeight || p.height);

      if (p.systemPreferred || p.autoCompatBlocked) {
        gatePending = true;
        holdNativeSource();
        viewer.classList.add('lh-system-preferred');
        systemBtn?.classList.add('lh-recommended');
        if (playMode) playMode.textContent = '媒体风险较高 · 系统播放优先';
        if (compatBtn) compatBtn.textContent = '系统播放器';
        const reason = p.autoCompatBlockReason || p.reason || '该文件不适合自动交给浏览器处理';
        showPlayerNotice('系统播放器优先', reason);
        return;
      }

      if (p.browserSafe === true && p.strategy === 'native') {
        if (compatBtn) compatBtn.textContent = '兼容播放';
        approveNative(path, token);
        return;
      }

      // Never release an uncertain file to Chromium. smart_ui already starts
      // compatibility automatically for strategy=compat. Conditional files
      // (HEVC/MOV quirks, etc.) are proactively routed through a real transcode
      // rather than being allowed to sit with an empty/half-loaded video source.
      gatePending = true;
      holdNativeSource();
      if (p.strategy === 'conditional') {
        setTimeout(() => {
          if (token === probeToken && viewer.open && currentPath() === path && !isCompatSource()) {
            startForcedTranscode('当前编码/容器对浏览器兼容性不稳定');
          }
        }, 80);
      }
    } catch (error) {
      if (token !== probeToken || currentPath() !== path) return;
      gatePending = true;
      holdNativeSource();
      viewer.classList.add('lh-system-preferred');
      systemBtn?.classList.add('lh-recommended');
      showPlayerNotice('媒体信息读取失败', `${error.message || error}。为避免卡住网页，LocalHub 没有直接加载该文件。`);
    }
  }

  video.addEventListener('loadedmetadata', () => {
    fromIntrinsicSize();
    requestAnimationFrame(fromIntrinsicSize);
    resetWatchdog();
  });
  video.addEventListener('loadeddata', fromIntrinsicSize);
  video.addEventListener('resize', fromIntrinsicSize);
  video.addEventListener('seeking', () => { lastSeekAt = performance.now(); });
  video.addEventListener('seeked', () => { lastSeekAt = performance.now(); resetWatchdog(); });
  video.addEventListener('emptied', resetWatchdog);

  // If smart_ui managed to issue the network load in the same task that changed
  // #viewerPath, the mutation observer runs before media decoding proceeds and
  // cancels that direct source. loadstart is a second safety net.
  video.addEventListener('loadstart', () => {
    if (gatePending && gatePath === currentPath() && isDirectSource()) {
      setTimeout(() => {
        if (gatePending && gatePath === currentPath()) holdNativeSource();
      }, 0);
    }
  });

  // Large/long files are intentionally routed to the Windows-associated player
  // instead of launching a multi-gigabyte background conversion from an innocent
  // compatibility button click.
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

  function stopForcedCompat() {
    forcedCompatToken++;
    clearTimeout(forcedCompatTimer);
    forcedCompatTimer = null;
  }

  async function startForcedTranscode(reason = '检测到浏览器播放时间轴异常') {
    const path = currentPath();
    if (!path || !viewer.open) return;
    if (Date.now() - runtimeFallbackAt < 2500) return;
    runtimeFallbackAt = Date.now();
    const token = ++forcedCompatToken;
    const restore = Number(video.currentTime) || 0;

    try {
      video.pause();
      video.removeAttribute('src');
      video.load();
    } catch {}
    if (compatBtn) compatBtn.disabled = true;
    if (playMode) playMode.textContent = '正在重建时间轴';
    showPlayerNotice('正在重建兼容视频', `${reason}。LocalHub 会生成临时 H.264/AAC 文件，原视频不会修改。`, 0);

    try {
      const started = await json('/api/compat/start', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({path, mode:'transcode'}),
      });
      if (token !== forcedCompatToken || currentPath() !== path || !viewer.open) return;
      let job = started.job || {};

      const poll = async () => {
        if (token !== forcedCompatToken || currentPath() !== path || !viewer.open) return;
        if (job.id && !['ready','error'].includes(job.status)) {
          const status = await json(`/api/compat/status?id=${encodeURIComponent(job.id)}`);
          job = status.job || job;
        }
        if (token !== forcedCompatToken || currentPath() !== path || !viewer.open) return;

        if (job.status === 'ready' && job.url) {
          if (compatBtn) compatBtn.disabled = false;
          if (playMode) playMode.textContent = '兼容转码';
          notice?.classList.add('hidden');
          gatePending = false;
          try {
            video.src = job.url;
            video.load();
            const restoreOnce = () => {
              video.removeEventListener('loadedmetadata', restoreOnce);
              const d = Number(video.duration) || 0;
              if (restore > 0 && (!d || restore < d - 1)) {
                try { video.currentTime = restore; } catch {}
              }
              video.play().catch(() => {});
            };
            video.addEventListener('loadedmetadata', restoreOnce);
          } catch {}
          resetWatchdog();
          return;
        }

        if (job.status === 'error') {
          if (compatBtn) compatBtn.disabled = false;
          const message = job.error || '兼容处理失败';
          if (/系统播放器|阻止自动|无法可靠读取/.test(message)) {
            viewer.classList.add('lh-system-preferred');
            systemBtn?.classList.add('lh-recommended');
            if (compatBtn) compatBtn.textContent = '系统播放器';
          }
          showPlayerNotice('兼容处理未启动', message);
          toast(message);
          return;
        }

        if (playMode) playMode.textContent = `正在重建时间轴 ${Math.round(Number(job.progress) || 0)}%`;
        showPlayerNotice('正在重建兼容视频', `${reason}。`, Number(job.progress) || 0);
        forcedCompatTimer = setTimeout(() => poll().catch(() => {}), 650);
      };

      await poll();
    } catch (error) {
      if (token !== forcedCompatToken) return;
      if (compatBtn) compatBtn.disabled = false;
      showPlayerNotice('兼容处理失败', error.message || String(error));
    }
  }

  function trimRecent(rows, now, windowMs) {
    while (rows.length && now - rows[0] > windowMs) rows.shift();
  }

  function noteTimelineAnomaly(reason) {
    if (!viewer.open || !isDirectSource() || video.seeking || performance.now() - lastSeekAt < 1200) return;
    const now = performance.now();
    timelineAnomalies.push(now);
    trimRecent(timelineAnomalies, now, 6500);
    if (timelineAnomalies.length >= 2) {
      timelineAnomalies = [];
      startForcedTranscode(reason);
    }
  }

  // Runtime watchdog catches files whose headers look normal but whose decoded
  // timeline jumps backwards/forwards once playback actually starts. This is the
  // class that produces "frames bouncing around" while PotPlayer still copes.
  video.addEventListener('timeupdate', () => {
    if (!viewer.open || !isDirectSource() || video.paused || video.seeking) {
      lastMediaTime = Number(video.currentTime) || 0;
      lastWallTime = performance.now();
      return;
    }
    const now = performance.now();
    const mediaNow = Number(video.currentTime) || 0;
    if (lastWallTime > 0) {
      const wallDelta = Math.max(0.001, (now - lastWallTime) / 1000);
      const mediaDelta = mediaNow - lastMediaTime;
      const expected = wallDelta * Math.max(0.25, Number(video.playbackRate) || 1);
      if (mediaDelta < -1.25) noteTimelineAnomaly('检测到播放时间反复倒退');
      else if (mediaDelta > Math.max(7, expected * 6 + 2)) noteTimelineAnomaly('检测到播放时间异常跳跃');
    }
    lastMediaTime = mediaNow;
    lastWallTime = now;
  });

  function noteStall() {
    if (!viewer.open || !isDirectSource() || video.paused || video.seeking) return;
    const now = performance.now();
    stallEvents.push(now);
    trimRecent(stallEvents, now, 12000);
    if (stallEvents.length >= 3 && video.readyState < 3) {
      stallEvents = [];
      startForcedTranscode('浏览器连续无法稳定读取该视频');
    }
  }
  video.addEventListener('stalled', noteStall);
  video.addEventListener('waiting', noteStall);

  const inspectPath = () => {
    const next = currentPath();
    if (lastPath && next && lastPath !== next) cancelCompat(lastPath);
    lastPath = next;
    stopForcedCompat();
    probeToken++;
    currentProbe = null;
    gatePath = next;
    gatePending = GATED_EXTS.has(extOf(next));
    if (gatePending) holdNativeSource();
    viewer.classList.remove('lh-player-portrait','lh-player-landscape','lh-system-preferred');
    stage.classList.remove('lh-stage-portrait');
    if (compatBtn) {
      compatBtn.disabled = false;
      compatBtn.textContent = '兼容播放';
    }
    resetWatchdog();
    if (next) setTimeout(refreshProbe, 0);
  };
  new MutationObserver(inspectPath).observe(pathNode, {subtree:true,childList:true,characterData:true});

  viewer.addEventListener('close', () => {
    const path = currentPath() || lastPath;
    probeToken++;
    stopForcedCompat();
    cancelCompat(path);
    stopRecHover(true);
    gatePending = false;
    gatePath = '';
    viewer.classList.remove('lh-player-portrait','lh-player-landscape','lh-system-preferred');
    stage.classList.remove('lh-stage-portrait');
    if (compatBtn) {
      compatBtn.disabled = false;
      compatBtn.textContent = '兼容播放';
    }
    resetWatchdog();
  });
  addEventListener('pagehide', () => {
    stopForcedCompat();
    cancelCompat(currentPath() || lastPath);
  });

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
