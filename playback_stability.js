(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const video = $('#videoPlayer');
  const viewer = $('#viewer');
  const stage = $('#viewerStage');
  const pathNode = $('#viewerPath');
  const diagnostics = $('#mediaDiagnostics');
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

  function hideInitialAnalysisNotice() {
    // smart_ui starts safe browser-native files immediately while probing in the
    // background. The diagnostic probe must never become a visual blocker for a
    // source that Chromium is already loading. Real playback errors use different
    // notice titles and are therefore left untouched.
    if (notice && (noticeTitle?.textContent || '').trim() === '正在分析媒体') {
      notice.classList.add('hidden');
    }
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

  // ----- portrait / rotation-safe fitting ---------------------------------
  // smart_ui already performs the only authoritative FFmpeg probe. This layer
  // consumes the dimensions already rendered in #mediaDiagnostics and falls back
  // to Chromium's intrinsic dimensions. It never starts another probe process.
  let diagnosticGeometry = null;
  let intrinsicGeometry = null;

  function geometry(width, height, source) {
    width = Number(width) || 0;
    height = Number(height) || 0;
    if (!width || !height) return null;
    return {width, height, source, portrait: height > width * 1.08};
  }

  function clearVideoBox() {
    for (const property of ['width', 'height', 'max-width', 'max-height', 'aspect-ratio']) {
      video.style.removeProperty(property);
    }
  }

  function chooseGeometry() {
    const a = diagnosticGeometry;
    const b = intrinsicGeometry;
    if (a && b && a.portrait !== b.portrait) {
      // When container rotation metadata and Chromium's coded dimensions disagree,
      // prefer the portrait interpretation. contain then letterboxes safely rather
      // than cropping real image content.
      return a.portrait ? a : b;
    }
    return a || b || null;
  }

  function fitVideoBox() {
    const chosen = chooseGeometry();
    if (!viewer.open || !chosen) return;

    const stageWidth = stage.clientWidth || 0;
    const stageHeight = stage.clientHeight || 0;
    if (!stageWidth || !stageHeight) return;

    const scale = Math.min(stageWidth / chosen.width, stageHeight / chosen.height);
    if (!Number.isFinite(scale) || scale <= 0) return;
    const fittedWidth = Math.max(1, Math.floor(chosen.width * scale));
    const fittedHeight = Math.max(1, Math.floor(chosen.height * scale));

    viewer.classList.toggle('lh-player-portrait', chosen.portrait);
    viewer.classList.toggle('lh-player-landscape', !chosen.portrait);
    stage.classList.toggle('lh-stage-portrait', chosen.portrait);
    stage.style.setProperty('--lh-media-aspect', `${chosen.width}/${chosen.height}`);

    video.style.setProperty('width', `${fittedWidth}px`, 'important');
    video.style.setProperty('height', `${fittedHeight}px`, 'important');
    video.style.setProperty('max-width', '100%', 'important');
    video.style.setProperty('max-height', '100%', 'important');
    video.style.setProperty('aspect-ratio', `${chosen.width} / ${chosen.height}`, 'important');
    video.style.setProperty('object-fit', 'contain', 'important');
    video.style.setProperty('object-position', 'center center', 'important');

    requestAnimationFrame(() => {
      const current = chooseGeometry();
      if (!viewer.open || !current) return;
      const sw = stage.clientWidth || 0;
      const sh = stage.clientHeight || 0;
      if (!sw || !sh) return;
      const nextScale = Math.min(sw / current.width, sh / current.height);
      if (!Number.isFinite(nextScale) || nextScale <= 0) return;
      video.style.setProperty('width', `${Math.max(1, Math.floor(current.width * nextScale))}px`, 'important');
      video.style.setProperty('height', `${Math.max(1, Math.floor(current.height * nextScale))}px`, 'important');
    });
  }

  function readDiagnosticGeometry() {
    const text = (diagnostics?.textContent || '').trim();
    const match = text.match(/(\d{2,5})\s*[×x]\s*(\d{2,5})/i);
    diagnosticGeometry = match ? geometry(match[1], match[2], 'diagnostics') : null;
    fitVideoBox();
  }

  function readIntrinsicGeometry() {
    if (video.videoWidth && video.videoHeight) {
      intrinsicGeometry = geometry(video.videoWidth, video.videoHeight, 'intrinsic');
      fitVideoBox();
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

  video.addEventListener('loadstart', hideInitialAnalysisNotice);
  video.addEventListener('loadedmetadata', () => {
    hideInitialAnalysisNotice();
    readIntrinsicGeometry();
    readDiagnosticGeometry();
    resetWatchdog();
  });
  video.addEventListener('loadeddata', () => {
    hideInitialAnalysisNotice();
    readIntrinsicGeometry();
    fitVideoBox();
  });
  video.addEventListener('resize', () => {
    readIntrinsicGeometry();
    fitVideoBox();
  });
  video.addEventListener('seeking', () => { lastSeekAt = performance.now(); });
  video.addEventListener('seeked', resetWatchdog);
  video.addEventListener('emptied', resetWatchdog);

  new MutationObserver(() => {
    diagnosticGeometry = null;
    intrinsicGeometry = null;
    clearVideoBox();
  }).observe(pathNode, {subtree:true, childList:true, characterData:true});

  if (diagnostics) {
    new MutationObserver(readDiagnosticGeometry).observe(
      diagnostics,
      {subtree:true, childList:true, characterData:true}
    );
  }

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
    diagnosticGeometry = null;
    intrinsicGeometry = null;
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

// LH_PORTRAIT_HARD_FIT_V2
(() => {
  'use strict';
  const viewer = document.querySelector('#viewer');
  const stage = document.querySelector('#viewerStage');
  const video = document.querySelector('#videoPlayer');
  const diagnostics = document.querySelector('#mediaDiagnostics');
  const pathNode = document.querySelector('#viewerPath');
  if (!viewer || !stage || !video || !pathNode) return;

  let hardApplied = false;
  let scheduled = 0;

  function diagnosticGeometry() {
    const text = (diagnostics?.textContent || '').trim();
    const match = text.match(/(\d{2,5})\s*[×x]\s*(\d{2,5})/i);
    if (!match) return null;
    const width = Number(match[1]) || 0;
    const height = Number(match[2]) || 0;
    return width && height ? {width, height} : null;
  }

  function intrinsicGeometry() {
    const width = Number(video.videoWidth) || 0;
    const height = Number(video.videoHeight) || 0;
    return width && height ? {width, height} : null;
  }

  function clearHardFit() {
    if (!hardApplied) return;
    hardApplied = false;
    stage.classList.remove('lh-hard-portrait');
    for (const prop of ['position','left','top','transform','margin','min-width','min-height']) video.style.removeProperty(prop);
    for (const prop of ['width','height','max-width','max-height','aspect-ratio','object-fit','object-position']) video.style.removeProperty(prop);
  }

  function applyHardPortrait() {
    scheduled = 0;
    if (!viewer.open) return;
    const diagnostic = diagnosticGeometry();
    const intrinsic = intrinsicGeometry();
    const g = diagnostic || intrinsic;
    if (!g || g.height <= g.width * 1.08) return;

    const widthAvailable = Math.max(1, stage.clientWidth || 0);
    const heightAvailable = Math.max(1, stage.clientHeight || 0);
    if (widthAvailable <= 1 || heightAvailable <= 1) return;

    const scale = Math.min(widthAvailable / g.width, heightAvailable / g.height);
    if (!Number.isFinite(scale) || scale <= 0) return;
    const fittedWidth = Math.max(1, Math.floor(g.width * scale));
    const fittedHeight = Math.max(1, Math.floor(g.height * scale));

    hardApplied = true;
    stage.classList.add('lh-hard-portrait');
    stage.style.setProperty('position', 'relative', 'important');
    stage.style.setProperty('overflow', 'hidden', 'important');
    video.style.setProperty('position', 'absolute', 'important');
    video.style.setProperty('left', '50%', 'important');
    video.style.setProperty('top', '50%', 'important');
    video.style.setProperty('transform', 'translate(-50%, -50%)', 'important');
    video.style.setProperty('margin', '0', 'important');
    video.style.setProperty('min-width', '0', 'important');
    video.style.setProperty('min-height', '0', 'important');
    video.style.setProperty('width', `${fittedWidth}px`, 'important');
    video.style.setProperty('height', `${fittedHeight}px`, 'important');
    video.style.setProperty('max-width', 'none', 'important');
    video.style.setProperty('max-height', 'none', 'important');
    video.style.setProperty('aspect-ratio', `${g.width} / ${g.height}`, 'important');
    video.style.setProperty('object-fit', 'contain', 'important');
    video.style.setProperty('object-position', 'center center', 'important');
    stage.dataset.lhPortraitFit = `${g.width}x${g.height}:${fittedWidth}x${fittedHeight}`;
  }

  function scheduleFit() {
    if (scheduled) cancelAnimationFrame(scheduled);
    scheduled = requestAnimationFrame(() => {
      requestAnimationFrame(applyHardPortrait);
      setTimeout(applyHardPortrait, 80);
      setTimeout(applyHardPortrait, 260);
    });
  }

  video.addEventListener('loadedmetadata', scheduleFit);
  video.addEventListener('loadeddata', scheduleFit);
  video.addEventListener('resize', scheduleFit);
  if (diagnostics) new MutationObserver(scheduleFit).observe(diagnostics, {subtree:true, childList:true, characterData:true});

  new MutationObserver(() => {
    clearHardFit();
    delete stage.dataset.lhPortraitFit;
    scheduleFit();
  }).observe(pathNode, {subtree:true, childList:true, characterData:true});

  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(scheduleFit).observe(stage);
  else window.addEventListener('resize', scheduleFit);

  viewer.addEventListener('close', () => {
    clearHardFit();
    delete stage.dataset.lhPortraitFit;
  });
})();
