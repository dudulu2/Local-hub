(() => {
  'use strict';

  if (!window.videojs) {
    console.error('[LocalHub V4] Video.js is not available');
    return;
  }

  const videojs = window.videojs;
  const viewer = document.querySelector('#viewer');
  const stage = document.querySelector('#viewerStage');
  const legacyVideo = document.querySelector('#videoPlayer');
  const viewerPath = document.querySelector('#viewerPath');
  const playMode = document.querySelector('#playMode');
  if (!viewer || !stage || !legacyVideo || !viewerPath) return;

  // Stable 2.2.3 keeps useful library/organizer state in smart_ui.js, so V4
  // deliberately leaves that code alive while removing its media element from
  // the visible DOM. All legacy media listeners keep pointing at this detached
  // node and can no longer interfere with the actual player.
  const videoEl = legacyVideo.cloneNode(false);
  videoEl.id = 'videoPlayer';
  videoEl.removeAttribute('src');
  videoEl.setAttribute('playsinline', '');
  videoEl.setAttribute('preload', 'none');
  videoEl.className = 'video-js vjs-default-skin vjs-big-play-centered';
  legacyVideo.replaceWith(videoEl);

  try { legacyVideo.pause(); } catch {}
  try { legacyVideo.removeAttribute('src'); legacyVideo.preload = 'none'; } catch {}
  try { legacyVideo.load = () => {}; } catch {}
  try { legacyVideo.pause = () => {}; } catch {}
  try { legacyVideo.play = () => Promise.resolve(); } catch {}
  try {
    Object.defineProperty(legacyVideo, 'src', {
      configurable: true,
      get: () => '',
      set: () => {},
    });
  } catch {}

  // Kill the old whole-file compatibility pipeline at its entrance. It remains
  // available in the stable source tree for rollback, but is not part of V4.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes('/api/compat/start')) {
      return Promise.reject(new Error('Player V4 owns compatibility playback'));
    }
    return nativeFetch(input, init);
  };

  const status = document.createElement('div');
  status.className = 'v4-player-status';
  stage.appendChild(status);

  let engineBase = '';
  let activePath = '';
  let activeProbe = null;
  let probePromise = null;
  let sourceKind = 'none';
  let transcodeMode = 'transcode';
  let logicalDuration = 0;
  let pendingResume = 0;
  let saveAt = 0;
  let switching = false;
  let streamGeneration = 0;
  let seekReloadTimer = 0;

  const progressKey = 'localhub:progress';

  function showStatus(text, isError = false) {
    status.textContent = text || '';
    status.classList.toggle('error', !!isError);
    status.classList.toggle('show', !!text);
  }

  function hideStatus() {
    status.classList.remove('show', 'error');
  }

  function setMode(label, stream = false) {
    if (!playMode) return;
    playMode.textContent = label;
    playMode.classList.toggle('compat', stream);
    playMode.classList.toggle('v4-stream', stream);
  }

  function readProgress(path) {
    try {
      const data = JSON.parse(localStorage.getItem(progressKey) || '{}');
      const item = data[path];
      return item && Number.isFinite(Number(item.time)) ? Number(item.time) : 0;
    } catch {
      return 0;
    }
  }

  function writeProgress(force = false) {
    if (!activePath || sourceKind === 'none') return;
    const now = Date.now();
    if (!force && now - saveAt < 2500) return;
    saveAt = now;
    const time = Number(player.currentTime()) || 0;
    const duration = Number(player.duration()) || logicalDuration || 0;
    if (!(duration > 0)) return;
    try {
      const data = JSON.parse(localStorage.getItem(progressKey) || '{}');
      data[activePath] = { time, duration, at: now };
      localStorage.setItem(progressKey, JSON.stringify(data));
    } catch {}
  }

  function mimeForPath(path) {
    const ext = String(path).split('.').pop().toLowerCase();
    if (['mp4', 'm4v', 'mov'].includes(ext)) return 'video/mp4';
    if (ext === 'webm') return 'video/webm';
    if (['ogv', 'ogg'].includes(ext)) return 'video/ogg';
    if (ext === 'ts') return 'video/mp2t';
    if (ext === 'mkv') return 'video/x-matroska';
    if (ext === 'avi') return 'video/x-msvideo';
    if (['mpeg', 'mpg'].includes(ext)) return 'video/mpeg';
    return 'video/mp4';
  }

  async function getEngineBase() {
    if (engineBase) return engineBase;
    const r = await nativeFetch('/api/media-engine', { cache: 'no-store' });
    const data = await r.json();
    if (!r.ok || !data.ok || !data.baseUrl) throw new Error(data.error || '媒体引擎不可用');
    engineBase = String(data.baseUrl).replace(/\/$/, '');
    return engineBase;
  }

  function engineURL(endpoint, path, extra = {}) {
    const url = new URL(engineBase + endpoint);
    url.searchParams.set('path', path);
    for (const [key, value] of Object.entries(extra)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
    return url.toString();
  }

  async function loadProbe(path) {
    try {
      const r = await nativeFetch(`/api/media/probe?path=${encodeURIComponent(path)}`, { cache: 'no-store' });
      const data = await r.json();
      if (!r.ok || !data.ok) return null;
      const probe = data.probe || null;
      if (probe && activePath === path) {
        activeProbe = probe;
        const duration = Number(probe.duration);
        if (duration > 0) logicalDuration = duration;
        transcodeMode = String(probe.videoCodec || '').toLowerCase() === 'h264' ? 'remux' : 'transcode';
      }
      return probe;
    } catch {
      return null;
    }
  }

  function makeDirectSource(path) {
    return {
      src: engineURL('/direct', path),
      type: mimeForPath(path),
    };
  }

  function makeTranscodeSource(path, start) {
    return {
      src: engineURL('/transcode.mp4', path, {
        start: Math.max(0, Number(start) || 0).toFixed(3),
        mode: transcodeMode,
      }),
      type: 'video/mp4',
      localhubV4: true,
      localhubOffset: Math.max(0, Number(start) || 0),
      localhubDuration: logicalDuration || Number(activeProbe && activeProbe.duration) || 0,
    };
  }

  // Clean-room implementation of the same useful idea used by mature media
  // servers: a live transcode beginning at T seconds still exposes the original
  // full-file clock. Seeking outside the current streamed buffer restarts FFmpeg
  // at the requested logical timestamp after a short debounce.
  videojs.use('*', function localHubOffsetMiddleware(middlewarePlayer) {
    let tech = null;
    let source = null;
    let offset = 0;
    let fullDuration = 0;

    function hasOffset() {
      return !!(source && source.localhubV4);
    }

    function scheduleReload(seconds) {
      clearTimeout(seekReloadTimer);
      const target = Math.max(0, Math.min(fullDuration || seconds, Number(seconds) || 0));
      seekReloadTimer = window.setTimeout(() => {
        if (middlewarePlayer !== player || sourceKind !== 'transcode' || !activePath) return;
        reloadTranscode(target);
      }, 200);
    }

    return {
      setTech(nextTech) {
        tech = nextTech;
      },
      setSource(srcObj, next) {
        source = srcObj;
        if (srcObj && srcObj.localhubV4) {
          offset = Number(srcObj.localhubOffset) || 0;
          fullDuration = Number(srcObj.localhubDuration) || logicalDuration || 0;
        } else {
          offset = 0;
          fullDuration = 0;
        }
        next(null, srcObj);
      },
      duration(seconds) {
        return hasOffset() && fullDuration > 0 ? fullDuration : seconds;
      },
      currentTime(seconds) {
        return hasOffset() ? offset + seconds : seconds;
      },
      buffered(ranges) {
        if (!hasOffset() || !ranges) return ranges;
        const shifted = [];
        for (let i = 0; i < ranges.length; i++) {
          shifted.push([ranges.start(i) + offset, ranges.end(i) + offset]);
        }
        return videojs.createTimeRanges(shifted);
      },
      setCurrentTime(seconds) {
        if (!hasOffset() || !tech) return seconds;
        const target = Number(seconds) || 0;
        const local = target - offset;
        const ranges = tech.buffered && tech.buffered();
        if (ranges) {
          for (let i = 0; i < ranges.length; i++) {
            if (local >= ranges.start(i) && local <= ranges.end(i)) return local;
          }
        }
        scheduleReload(target);
        return 0;
      },
    };
  });

  const player = videojs(videoEl, {
    controls: true,
    preload: 'none',
    playsinline: true,
    inactivityTimeout: 900,
    playbackRates: [0.5, 0.75, 1, 1.25, 1.5, 2],
    controlBar: {
      pictureInPictureToggle: false,
      volumePanel: { inline: false },
    },
  });

  async function startDirect(path) {
    await getEngineBase();
    sourceKind = 'direct';
    switching = true;
    setMode('原生 · V4', false);
    showStatus('正在打开原始视频…');
    try { player.error(null); } catch {}
    player.src(makeDirectSource(path));
    player.load();
    player.one('loadedmetadata', () => {
      if (activePath !== path || sourceKind !== 'direct') return;
      const d = Number(player.duration());
      if (d > 0) logicalDuration = d;
      if (pendingResume > 0 && (!d || pendingResume < d - 1)) {
        try { player.currentTime(pendingResume); } catch {}
      }
      pendingResume = 0;
    });
    try { await player.play(); } catch {}
    switching = false;
  }

  async function switchToTranscode(startAt, reason = '') {
    if (!activePath || sourceKind === 'transcode' || switching) return;
    switching = true;
    sourceKind = 'transcode';
    const generation = ++streamGeneration;
    showStatus(reason || '原始格式无法直接解码，正在切换实时兼容流…');
    setMode(transcodeMode === 'remux' ? '实时封装 · V4' : '实时转码 · V4', true);
    if (probePromise) await probePromise;
    if (generation !== streamGeneration || !activePath) return;
    try { player.error(null); } catch {}
    const start = Math.max(0, Number(startAt) || pendingResume || 0);
    player.src(makeTranscodeSource(activePath, start));
    player.load();
    const wasPlaying = !player.paused();
    player.one('canplay', () => {
      if (generation !== streamGeneration || sourceKind !== 'transcode') return;
      hideStatus();
      if (wasPlaying || pendingResume > 0) player.play().catch(() => {});
      pendingResume = 0;
    });
    player.play().catch(() => {});
    switching = false;
  }

  function reloadTranscode(target) {
    if (!activePath || sourceKind !== 'transcode') return;
    const generation = ++streamGeneration;
    const wasPaused = player.paused();
    const rate = Number(player.playbackRate()) || 1;
    showStatus(`正在跳转到 ${Math.floor(target / 60)}:${String(Math.floor(target % 60)).padStart(2, '0')}…`);
    try { player.error(null); } catch {}
    player.src(makeTranscodeSource(activePath, target));
    player.load();
    player.playbackRate(rate);
    player.one('canplay', () => {
      if (generation !== streamGeneration || sourceKind !== 'transcode') return;
      hideStatus();
      player.playbackRate(rate);
      if (!wasPaused) player.play().catch(() => {});
      else player.pause();
    });
    if (!wasPaused) player.play().catch(() => {});
  }

  async function openCurrentViewer() {
    const path = (viewerPath.textContent || '').trim();
    if (!path || path === activePath) return;
    streamGeneration++;
    clearTimeout(seekReloadTimer);
    activePath = path;
    activeProbe = null;
    logicalDuration = 0;
    transcodeMode = 'transcode';
    pendingResume = readProgress(path);
    probePromise = loadProbe(path);
    try {
      await startDirect(path);
    } catch (e) {
      showStatus(`媒体引擎启动失败：${e.message || e}`, true);
      sourceKind = 'none';
    }
  }

  function closeCurrentViewer() {
    writeProgress(true);
    streamGeneration++;
    clearTimeout(seekReloadTimer);
    activePath = '';
    activeProbe = null;
    probePromise = null;
    logicalDuration = 0;
    pendingResume = 0;
    sourceKind = 'none';
    switching = false;
    hideStatus();
    try { player.pause(); } catch {}
    try { player.reset(); } catch {}
    setMode('原生', false);
  }

  player.on('playing', () => {
    hideStatus();
  });

  player.on('timeupdate', () => {
    writeProgress(false);
  });

  player.on('loadedmetadata', () => {
    if (sourceKind !== 'direct') return;
    window.setTimeout(() => {
      if (sourceKind !== 'direct' || !activePath) return;
      const width = Number(player.videoWidth && player.videoWidth()) || 0;
      const height = Number(player.videoHeight && player.videoHeight()) || 0;
      if (!width && !height && !player.error()) {
        switchToTranscode(pendingResume || Number(player.currentTime()) || 0, '原始视频轨道无法解码，正在切换实时兼容流…');
      }
    }, 80);
  });

  player.on('error', () => {
    if (!activePath) return;
    const error = player.error();
    const code = error && Number(error.code);
    if (sourceKind === 'direct' && (code === 3 || code === 4)) {
      const startAt = pendingResume || Number(player.currentTime()) || 0;
      switchToTranscode(startAt);
      return;
    }
    if (sourceKind === 'transcode') {
      showStatus(`实时兼容流播放失败${error && error.message ? `：${error.message}` : ''}`, true);
      setMode('兼容失败 · V4', true);
    }
  });

  const viewerObserver = new MutationObserver(() => {
    if (viewer.open) {
      queueMicrotask(() => openCurrentViewer());
    } else if (activePath) {
      closeCurrentViewer();
    }
  });
  viewerObserver.observe(viewer, { attributes: true, attributeFilter: ['open'] });

  viewer.addEventListener('close', () => {
    // Stable 2.2.3 writes progress from its detached legacy element while
    // closing. V4 writes afterwards so the real playback position wins.
    writeProgress(true);
    if (activePath) closeCurrentViewer();
  });

  window.addEventListener('beforeunload', () => writeProgress(true));
})();
