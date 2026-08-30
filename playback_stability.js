(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const video = $('#videoPlayer');
  const viewer = $('#viewer');
  const stage = $('#viewerStage');
  const pathNode = $('#viewerPath');
  const compatBtn = $('#compatBtn');
  const notice = $('#playerNotice');
  const noticeTitle = $('#playerNoticeTitle');
  const noticeText = $('#playerNoticeText');
  if (!video || !viewer || !stage || !pathNode) return;

  // This file is deliberately NOT a second player controller. smart_ui.js owns
  // media probing, source selection, video.src and compatibility jobs. Keeping
  // one source owner avoids src/load/probe races that can wedge Chromium.

  let lastMediaTime = 0;
  let lastWallTime = 0;
  let lastSeekAt = 0;
  let anomalies = [];
  let stalls = [];
  let unstableNotifiedAt = 0;

  // Chromium's intrinsic videoWidth/videoHeight can describe the coded frame
  // instead of the rotated/display frame for some phone MP4/MOV files. Keep a
  // separate display geometry, preferably from LocalHub's FFmpeg probe, and fit
  // the element box explicitly so a 9:16 clip can never be cropped by a 16:9
  // player shell.
  let displayWidth = 0;
  let displayHeight = 0;
  let displaySource = '';
  let orientationRequest = 0;

  function showPassiveNotice(title, text) {
    if (!notice) return;
    if (noticeTitle) noticeTitle.textContent = title;
    if (noticeText) noticeText.textContent = text;
    notice.classList.remove('hidden');
    compatBtn?.classList.add('recommended');
  }

  function resetWatchdog() {
    lastMediaTime = Number(video.currentTime) || 0;
    lastWallTime = performance.now();
    lastSeekAt = performance.now();
    anomalies = [];
    stalls = [];
  }

  function markUnstable(reason) {
    if (!viewer.open || video.seeking) return;
    const now = performance.now();
    if (now - unstableNotifiedAt < 6000) return;
    unstableNotifiedAt = now;
    try { video.pause(); } catch {}
    showPassiveNotice('浏览器播放时间轴不稳定', `${reason}。建议使用“兼容播放”或系统播放器，LocalHub 不会自动启动后台转码。`);
  }

  function clearVideoBox() {
    for (const property of ['width', 'height', 'max-width', 'max-height', 'aspect-ratio']) {
      video.style.removeProperty(property);
    }
  }

  function fitVideoBox() {
    const width = Number(displayWidth) || 0;
    const height = Number(displayHeight) || 0;
    const stageWidth = stage.clientWidth || 0;
    const stageHeight = stage.clientHeight || 0;
    if (!viewer.open || !width || !height || !stageWidth || !stageHeight) return;

    const scale = Math.min(stageWidth / width, stageHeight / height);
    if (!Number.isFinite(scale) || scale <= 0) return;
    const fittedWidth = Math.max(1, Math.floor(width * scale));
    const fittedHeight = Math.max(1, Math.floor(height * scale));

    // Explicit pixel geometry avoids relying on a replaced element's coded
    // intrinsic ratio when rotation metadata says the display ratio is different.
    video.style.setProperty('width', `${fittedWidth}px`, 'important');
    video.style.setProperty('height', `${fittedHeight}px`, 'important');
    video.style.setProperty('max-width', '100%', 'important');
    video.style.setProperty('max-height', '100%', 'important');
    video.style.setProperty('aspect-ratio', `${width} / ${height}`, 'important');
    video.style.setProperty('object-fit', 'contain', 'important');
    video.style.setProperty('object-position', 'center center', 'important');
  }

  function applyOrientation(width, height, source = 'intrinsic') {
    width = Number(width) || 0;
    height = Number(height) || 0;
    if (!width || !height) return;

    // A successful FFmpeg display-size probe is authoritative. Do not let a
    // later Chromium intrinsic resize event overwrite a rotated portrait ratio.
    if (displaySource === 'probe' && source !== 'probe') {
      fitVideoBox();
      return;
    }

    displayWidth = width;
    displayHeight = height;
    displaySource = source;
    const portrait = height > width * 1.08;
    viewer.classList.toggle('lh-player-portrait', portrait);
    viewer.classList.toggle('lh-player-landscape', !portrait);
    stage.classList.toggle('lh-stage-portrait', portrait);
    stage.style.setProperty('--lh-media-aspect', `${width}/${height}`);

    // The class changes the dialog/player-shell dimensions, so fit after layout
    // has settled as well as once immediately.
    fitVideoBox();
    requestAnimationFrame(() => {
      fitVideoBox();
      requestAnimationFrame(fitVideoBox);
    });
  }

  function fitIntrinsic() {
    if (video.videoWidth && video.videoHeight) {
      applyOrientation(video.videoWidth, video.videoHeight, 'intrinsic');
    }
  }

  async function fitFromProbe(path) {
    const clean = String(path || '').trim();
    if (!clean) return;
    const request = ++orientationRequest;
    try {
      const response = await fetch(`/api/media/probe?path=${encodeURIComponent(clean)}`, {cache:'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      if (request !== orientationRequest || !viewer.open || pathNode.textContent.trim() !== clean) return;
      const probe = data?.probe || {};
      const width = Number(probe.displayWidth || probe.width) || 0;
      const height = Number(probe.displayHeight || probe.height) || 0;
      if (width && height) applyOrientation(width, height, 'probe');
    } catch {
      // Orientation is best-effort; intrinsic dimensions remain the fallback.
    }
  }

  // Normal web-player interaction. No media source mutation happens here.
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

  video.addEventListener('loadedmetadata', () => {
    fitIntrinsic();
    const path = pathNode.textContent.trim();
    if (path) fitFromProbe(path);
    requestAnimationFrame(fitIntrinsic);
    resetWatchdog();
  });
  video.addEventListener('loadeddata', () => {
    fitIntrinsic();
    fitVideoBox();
  });
  video.addEventListener('resize', () => {
    fitIntrinsic();
    fitVideoBox();
  });
  video.addEventListener('seeking', () => { lastSeekAt = performance.now(); });
  video.addEventListener('seeked', resetWatchdog);
  video.addEventListener('emptied', resetWatchdog);

  new MutationObserver(() => {
    displayWidth = 0;
    displayHeight = 0;
    displaySource = '';
    clearVideoBox();
    const path = pathNode.textContent.trim();
    if (path && viewer.open) fitFromProbe(path);
  }).observe(pathNode, {subtree:true, childList:true, characterData:true});

  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(() => fitVideoBox()).observe(stage);
  } else {
    window.addEventListener('resize', fitVideoBox);
  }

  // Runtime guard only OBSERVES playback. It never changes src and never starts
  // FFmpeg. Two clear timestamp jumps in a short window pause playback and offer
  // the existing compatibility path instead of letting a broken file loop frames.
  video.addEventListener('timeupdate', () => {
    if (!viewer.open || video.paused || video.seeking) {
      lastMediaTime = Number(video.currentTime) || 0;
      lastWallTime = performance.now();
      return;
    }
    const now = performance.now();
    const mediaNow = Number(video.currentTime) || 0;
    if (lastWallTime > 0 && now - lastSeekAt > 1200) {
      const wallDelta = Math.max(0.001, (now - lastWallTime) / 1000);
      const mediaDelta = mediaNow - lastMediaTime;
      const expected = wallDelta * Math.max(0.25, Number(video.playbackRate) || 1);
      if (mediaDelta < -1.25 || mediaDelta > Math.max(7, expected * 6 + 2)) {
        anomalies.push(now);
        anomalies = anomalies.filter(t => now - t < 6500);
        if (anomalies.length >= 2) {
          anomalies = [];
          markUnstable(mediaDelta < 0 ? '检测到播放时间反复倒退' : '检测到播放时间异常跳跃');
        }
      }
    }
    lastMediaTime = mediaNow;
    lastWallTime = now;
  });

  function noteStall() {
    if (!viewer.open || video.paused || video.seeking) return;
    const now = performance.now();
    stalls.push(now);
    stalls = stalls.filter(t => now - t < 9000);
    // A single buffering event is normal. Repeated events are only surfaced as
    // a recommendation; they do not trigger compatibility work automatically.
    if (stalls.length >= 5) {
      stalls = [];
      markUnstable('浏览器连续多次等待视频数据');
    }
  }
  video.addEventListener('waiting', noteStall);
  video.addEventListener('stalled', noteStall);

  async function cancelCompat(path) {
    if (!path) return;
    try {
      await fetch('/api/compat/cancel', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({path}),
        cache: 'no-store',
        keepalive: true,
      });
    } catch {}
  }

  viewer.addEventListener('close', () => {
    const path = (pathNode.textContent || '').trim();
    orientationRequest++;
    displayWidth = 0;
    displayHeight = 0;
    displaySource = '';
    clearVideoBox();
    resetWatchdog();
    viewer.classList.remove('lh-player-portrait','lh-player-landscape');
    stage.classList.remove('lh-stage-portrait');
    stage.style.removeProperty('--lh-media-aspect');
    cancelCompat(path);
    clearRecommendationHover();
  });

  // Recommendation hover: explicit user interaction only, maximum 3 frames,
  // sequential requests. The backend itself yields during seeking.
  let rec = null;
  let recToken = 0;
  const recUrls = new Set();

  function clearRecommendationHover(card = null) {
    recToken++;
    const state = rec;
    if (state?.controller) state.controller.abort();
    if (state?.timer) clearTimeout(state.timer);
    const target = card || state?.card;
    if (target) {
      const img = target.querySelector('img[data-rec-thumb]');
      if (img?.dataset.baseRecSrc) img.src = img.dataset.baseRecSrc;
      target.classList.remove('hover-previewing');
    }
    for (const url of recUrls) URL.revokeObjectURL(url);
    recUrls.clear();
    rec = null;
  }

  async function fetchRecFrame(path, slot, state, token) {
    if (!state || token !== recToken || rec !== state || !state.card.matches(':hover')) return null;
    const controller = new AbortController();
    state.controller = controller;
    try {
      const response = await fetch(`/api/smart/hover-interactive?path=${encodeURIComponent(path)}&slot=${slot}`, {
        cache:'no-store', signal:controller.signal,
      });
      if (response.status === 204 || !response.ok) return null;
      const blob = await response.blob();
      if (token !== recToken || rec !== state || !state.card.matches(':hover')) return null;
      const url = URL.createObjectURL(blob);
      recUrls.add(url);
      return url;
    } catch { return null; }
    finally { if (state.controller === controller) state.controller = null; }
  }

  function startRecommendationHover(card) {
    const path = card?.dataset.recId || '';
    const img = card?.querySelector('img[data-rec-thumb]');
    if (!path || !img) return;
    clearRecommendationHover();
    if (!img.dataset.baseRecSrc) img.dataset.baseRecSrc = img.currentSrc || img.src || '';
    const state = {card, controller:null, timer:null};
    rec = state;
    const token = ++recToken;
    state.timer = setTimeout(async () => {
      const frames = [];
      for (const slot of [0, 2, 4]) {
        if (token !== recToken || rec !== state || !card.matches(':hover')) return;
        const url = await fetchRecFrame(path, slot, state, token);
        if (url) {
          frames.push(url);
          img.src = url;
          card.classList.add('hover-previewing');
        }
      }
      if (frames.length < 2) return;
      let index = 0;
      while (token === recToken && rec === state && card.matches(':hover')) {
        img.src = frames[index++ % frames.length];
        await new Promise(resolve => state.timer = setTimeout(resolve, 680));
      }
    }, 520);
  }

  document.addEventListener('mouseover', event => {
    const card = event.target.closest?.('.v23-rec-card');
    if (!card || card.contains(event.relatedTarget)) return;
    startRecommendationHover(card);
  });
  document.addEventListener('mouseout', event => {
    const card = event.target.closest?.('.v23-rec-card');
    if (!card || card.contains(event.relatedTarget)) return;
    if (rec?.card === card) clearRecommendationHover(card);
  });
})();
