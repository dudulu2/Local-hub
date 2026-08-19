(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const video = $('#videoPlayer');
  const viewer = $('#viewer');
  const pathNode = $('#viewerPath');
  const compatBtn = $('#compatBtn');
  const playMode = $('#playMode');
  const toast = $('#toast');
  if (!video || !viewer || !pathNode || !compatBtn) return;

  let session = 0;
  let jobId = '';
  let aborter = null;
  let objectUrl = '';
  let mediaSource = null;
  let sourceBuffer = null;
  let queue = [];
  let queueBytes = 0;
  let streamDone = false;
  let starting = false;

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const currentPath = () => String(pathNode.textContent || '').trim();
  const showToast = text => {
    if (!toast) return;
    toast.textContent = text;
    toast.classList.add('show');
    clearTimeout(showToast.t);
    showToast.t = setTimeout(() => toast.classList.remove('show'), 2200);
  };
  const api = async (url, opt = {}) => {
    const response = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };

  function installButton() {
    if ($('#mseTrialBtn')) return $('#mseTrialBtn');
    const button = document.createElement('button');
    button.id = 'mseTrialBtn';
    button.className = 'control-text';
    button.type = 'button';
    button.textContent = 'MSE 试播';
    button.title = '实验：FFmpeg 生成 fMP4 分片，由浏览器 MediaSource 直接缓冲播放';
    compatBtn.insertAdjacentElement('afterend', button);
    return button;
  }
  const mseBtn = installButton();

  function setMode(active) {
    video.toggleAttribute('data-localhub-mse', active);
    mseBtn.classList.toggle('recommended', active);
    if (active && playMode) {
      playMode.textContent = '兼容 · MSE';
      playMode.classList.add('compat');
    }
  }

  async function cancelSession(cancelJob = true) {
    session++;
    starting = false;
    streamDone = false;
    queue = [];
    queueBytes = 0;
    try { aborter?.abort(); } catch {}
    aborter = null;
    const oldJob = jobId;
    jobId = '';
    if (sourceBuffer) {
      try { sourceBuffer.abort(); } catch {}
    }
    sourceBuffer = null;
    mediaSource = null;
    if (objectUrl) {
      try { URL.revokeObjectURL(objectUrl); } catch {}
      objectUrl = '';
    }
    setMode(false);
    mseBtn.disabled = false;
    mseBtn.textContent = 'MSE 试播';
    if (cancelJob && oldJob) {
      fetch('/api/mse/cancel', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({id:oldJob}), cache:'no-store', keepalive:true
      }).catch(() => {});
    }
  }

  function concatChunks(chunks, total) {
    const out = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      out.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return out;
  }

  function h2(n) { return Number(n).toString(16).padStart(2, '0').toUpperCase(); }
  function avcCodec(bytes) {
    // avcC payload = configurationVersion, profile, compatibility, level ...
    for (let i = 4; i + 8 < bytes.length; i++) {
      if (bytes[i] === 0x61 && bytes[i+1] === 0x76 && bytes[i+2] === 0x63 && bytes[i+3] === 0x43) {
        if (bytes[i+4] !== 1) continue;
        return `avc1.${h2(bytes[i+5])}${h2(bytes[i+6])}${h2(bytes[i+7])}`;
      }
    }
    return '';
  }

  function bufferedAhead() {
    const t = video.currentTime || 0;
    try {
      for (let i = 0; i < video.buffered.length; i++) {
        if (video.buffered.start(i) <= t + .2 && video.buffered.end(i) >= t) return video.buffered.end(i) - t;
      }
    } catch {}
    return 0;
  }

  function maybeEnd() {
    if (!streamDone || queue.length || sourceBuffer?.updating || mediaSource?.readyState !== 'open') return;
    try { mediaSource.endOfStream(); } catch {}
  }

  function pump() {
    if (!sourceBuffer || sourceBuffer.updating || !queue.length) {
      maybeEnd();
      return;
    }
    const chunk = queue.shift();
    queueBytes = Math.max(0, queueBytes - chunk.byteLength);
    try {
      sourceBuffer.appendBuffer(chunk);
    } catch (e) {
      if (e?.name === 'QuotaExceededError') {
        queue.unshift(chunk);
        queueBytes += chunk.byteLength;
        const cutoff = Math.max(0, (video.currentTime || 0) - 30);
        if (cutoff > 1 && !sourceBuffer.updating) {
          try { sourceBuffer.remove(0, cutoff); return; } catch {}
        }
      }
      throw e;
    }
  }

  async function waitSourceOpen(ms, mine) {
    const started = Date.now();
    while (mine === session && mediaSource?.readyState !== 'open') {
      if (Date.now() - started > ms) throw new Error('MediaSource 打开超时');
      await sleep(25);
    }
  }

  async function waitStreamReady(mine, id) {
    const started = Date.now();
    while (mine === session) {
      const data = await api(`/api/mse/status?id=${encodeURIComponent(id)}`);
      const job = data.job || {};
      mseBtn.textContent = `MSE ${Math.round(Number(job.progress)||0)}%`;
      if (job.status === 'error') throw new Error(job.error || 'MSE 生成失败');
      if (job.streamReady && job.url) return job;
      if (Date.now() - started > 30000) throw new Error('MSE 首段生成超时');
      await sleep(120);
    }
    throw new Error('MSE 已取消');
  }

  async function startMSE() {
    if (starting || !viewer.open) return;
    if (!('MediaSource' in window)) {
      showToast('当前浏览器不支持 MediaSource');
      return;
    }
    const path = currentPath();
    if (!path) return;

    await cancelSession(true);
    const mine = session;
    starting = true;
    mseBtn.disabled = true;
    mseBtn.textContent = 'MSE 准备中';
    const resume = Math.max(0, video.currentTime || 0);
    const wasPaused = video.paused;
    const rate = video.playbackRate || 1;
    const volume = video.volume;
    const muted = video.muted;

    try {
      // Do not let an older compat/remux experiment keep running in parallel.
      fetch('/api/compat/cancel', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({path}), cache:'no-store'
      }).catch(() => {});

      const started = await api('/api/mse/start', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({path})
      });
      if (mine !== session) return;
      jobId = started.job?.id || '';
      if (!jobId) throw new Error('MSE 任务启动失败');
      const job = await waitStreamReady(mine, jobId);
      if (mine !== session) return;

      mediaSource = new MediaSource();
      objectUrl = URL.createObjectURL(mediaSource);
      video.pause();
      video.src = objectUrl;
      video.load();
      setMode(true);
      await waitSourceOpen(5000, mine);

      aborter = new AbortController();
      const response = await fetch(job.url, {cache:'no-store', signal:aborter.signal});
      if (!response.ok || !response.body) throw new Error(`MSE 流 HTTP ${response.status}`);
      const reader = response.body.getReader();
      const initial = [];
      let initialBytes = 0;
      let codec = '';

      while (mine === session && !codec) {
        const result = await reader.read();
        if (result.done) throw new Error('MSE 初始化数据不完整');
        initial.push(result.value);
        initialBytes += result.value.byteLength;
        if (initialBytes > 2 * 1024 * 1024) throw new Error('无法识别 H.264 avcC 初始化信息');
        codec = avcCodec(concatChunks(initial, initialBytes));
      }
      if (mine !== session) return;

      const mime = job.hasAudio
        ? `video/mp4; codecs="${codec}, mp4a.40.2"`
        : `video/mp4; codecs="${codec}"`;
      if (!MediaSource.isTypeSupported(mime)) throw new Error(`浏览器不支持 ${mime}`);
      sourceBuffer = mediaSource.addSourceBuffer(mime);
      sourceBuffer.mode = 'segments';
      sourceBuffer.addEventListener('updateend', pump);
      sourceBuffer.addEventListener('error', () => showToast('MSE SourceBuffer 解码失败'));

      const first = concatChunks(initial, initialBytes);
      queue.push(first); queueBytes += first.byteLength; pump();
      mseBtn.disabled = false;
      mseBtn.textContent = 'MSE 试播';
      starting = false;

      const restore = () => {
        video.removeEventListener('loadedmetadata', restore);
        video.playbackRate = rate;
        video.volume = volume;
        video.muted = muted;
        try {
          if (resume > 0 && video.buffered.length && resume <= video.buffered.end(video.buffered.length - 1)) video.currentTime = resume;
        } catch {}
        if (!wasPaused) video.play().catch(() => {});
      };
      video.addEventListener('loadedmetadata', restore);
      video.play().catch(() => {});
      showToast('MSE 实验播放已启动');

      while (mine === session) {
        while (mine === session && (queueBytes > 12 * 1024 * 1024 || bufferedAhead() > 90)) await sleep(120);
        const result = await reader.read();
        if (result.done) break;
        queue.push(result.value);
        queueBytes += result.value.byteLength;
        pump();
      }
      if (mine === session) {
        streamDone = true;
        maybeEnd();
      }
    } catch (e) {
      if (mine === session) {
        showToast(e?.message || 'MSE 试播失败');
        await cancelSession(true);
      }
    } finally {
      if (mine === session) {
        starting = false;
        mseBtn.disabled = false;
        if (!video.hasAttribute('data-localhub-mse')) mseBtn.textContent = 'MSE 试播';
      }
    }
  }

  mseBtn.addEventListener('click', () => { void startMSE(); });
  viewer.addEventListener('close', () => { void cancelSession(true); });
  new MutationObserver(() => {
    if (jobId && currentPath()) void cancelSession(true);
  }).observe(pathNode, {subtree:true, childList:true, characterData:true});
})();
