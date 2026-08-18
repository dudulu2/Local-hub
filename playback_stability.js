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

  function fitIntrinsic() {
    if (video.videoWidth && video.videoHeight) {
      applyOrientation(video.videoWidth, video.videoHeight);
    }
  }

  video.addEventListener('loadedmetadata', () => {
    fitIntrinsic();
    requestAnimationFrame(fitIntrinsic);
    resetWatchdog();
  });
  video.addEventListener('loadeddata', fitIntrinsic);
  video.addEventListener('resize', fitIntrinsic);
  video.addEventListener('seeking', () => { lastSeekAt = performance.now(); });
  video.addEventListener('seeked', resetWatchdog);
  video.addEventListener('emptied', resetWatchdog);

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
    resetWatchdog();
    viewer.classList.remove('lh-player-portrait','lh-player-landscape');
    stage.classList.remove('lh-stage-portrait');
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
