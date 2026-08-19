(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const video = $('#videoPlayer');
  const viewer = $('#viewer');
  const pathNode = $('#viewerPath');
  const compatBtn = $('#compatBtn');
  const playMode = $('#playMode');
  const notice = $('#playerNotice');
  const noticeTitle = $('#playerNoticeTitle');
  const noticeText = $('#playerNoticeText');
  const noticeProgress = $('#compatProgress');
  const toast = $('#toast');
  if (!video || !viewer || !pathNode || !compatBtn) return;

  let jobId = '';
  let activePath = '';
  let pollTimer = 0;
  let starting = false;

  const currentPath = () => String(pathNode.textContent || '').trim();
  const showToast = text => {
    if (!toast) return;
    toast.textContent = text;
    toast.classList.add('show');
    clearTimeout(showToast.t);
    showToast.t = setTimeout(() => toast.classList.remove('show'), 2800);
  };
  const api = async (url, opt = {}) => {
    const r = await fetch(url, {cache:'no-store', ...opt});
    let d = {};
    try { d = await r.json(); } catch {}
    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
  };
  function setStatus(title, text = '', progress = null) {
    if (!notice || !noticeTitle || !noticeText) return;
    noticeTitle.textContent = title;
    noticeText.textContent = text;
    notice.classList.remove('hidden');
    if (!noticeProgress) return;
    const bar = noticeProgress.querySelector('i');
    if (progress == null) noticeProgress.classList.add('hidden');
    else {
      noticeProgress.classList.remove('hidden');
      if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(progress) || 0))}%`;
    }
  }
  function installButton() {
    if ($('#repairPlayBtn')) return $('#repairPlayBtn');
    const b = document.createElement('button');
    b.id = 'repairPlayBtn';
    b.className = 'control-text';
    b.type = 'button';
    b.textContent = '修复播放';
    b.title = '实验：完整解码后按固定帧率重建时间轴并重新编码 H.264/AAC';
    const mse = $('#mseTrialBtn');
    (mse || compatBtn).insertAdjacentElement('afterend', b);
    return b;
  }
  const btn = installButton();

  async function cancelJob() {
    clearInterval(pollTimer); pollTimer = 0;
    const old = jobId; jobId = ''; activePath = ''; starting = false;
    btn.disabled = false; btn.textContent = '修复播放'; btn.classList.remove('recommended');
    if (old) {
      fetch('/api/repair/cancel', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:old}),cache:'no-store',keepalive:true}).catch(()=>{});
    }
  }

  async function startRepair() {
    if (starting || !viewer.open) return;
    const path = currentPath();
    if (!path) return;
    await cancelJob();
    document.dispatchEvent(new CustomEvent('localhub:repair-start'));
    activePath = path;
    starting = true;
    btn.disabled = true;
    btn.textContent = '修复 0%';
    video.pause();
    const resume = Math.max(0, video.currentTime || 0);
    const wasPaused = video.paused;
    const rate = video.playbackRate || 1;
    const volume = video.volume;
    const muted = video.muted;
    setStatus('修复播放正在重建时间轴', '完整解码视频并生成新的 CFR H.264/AAC 临时文件。原文件不会修改。', 0);
    try {
      const d = await api('/api/repair/start', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
      jobId = d.job?.id || '';
      if (!jobId) throw new Error('修复任务启动失败');
      const poll = async () => {
        if (!jobId || currentPath() !== activePath) return;
        try {
          const s = await api(`/api/repair/status?id=${encodeURIComponent(jobId)}`);
          const j = s.job || {};
          const pct = Math.round(Number(j.progress) || 0);
          btn.textContent = `修复 ${pct}%`;
          setStatus('修复播放正在重建时间轴', `${Number(j.fps||0).toFixed(3)} fps CFR · ${pct}%`, pct);
          if (j.status === 'error') {
            clearInterval(pollTimer); pollTimer = 0;
            btn.disabled = false; btn.textContent = '修复播放';
            setStatus('修复播放失败', j.error || 'FFmpeg 无法生成修复版本');
            showToast('修复播放失败');
            return;
          }
          if (j.status === 'ready' && j.url) {
            clearInterval(pollTimer); pollTimer = 0;
            jobId = '';
            starting = false;
            btn.disabled = false; btn.textContent = '修复播放'; btn.classList.add('recommended');
            video.pause();
            video.src = j.url;
            video.load();
            if (playMode) { playMode.textContent = `修复 · CFR ${Number(j.fps||0).toFixed(3)}fps`; playMode.classList.add('compat'); }
            const onMeta = () => {
              video.removeEventListener('loadedmetadata', onMeta);
              video.playbackRate = rate; video.volume = volume; video.muted = muted;
              const duration = Number.isFinite(video.duration) ? video.duration : 0;
              if (resume > 0 && (!duration || resume < duration - 1)) { try { video.currentTime = resume; } catch {} }
              if (!wasPaused) video.play().catch(()=>{});
            };
            video.addEventListener('loadedmetadata', onMeta);
            setStatus('修复播放已接管', `已重新编码并重建为 ${Number(j.fps||0).toFixed(3)} fps CFR。请观察是否还会闪烁或回退。`);
            showToast('修复版本已开始播放');
          }
        } catch (e) {
          clearInterval(pollTimer); pollTimer = 0;
          btn.disabled = false; btn.textContent = '修复播放';
          setStatus('修复播放失败', e?.message || String(e));
        }
      };
      await poll();
      if (jobId) pollTimer = setInterval(poll, 500);
    } catch (e) {
      starting = false; btn.disabled = false; btn.textContent = '修复播放';
      setStatus('修复播放失败', e?.message || String(e));
    }
  }

  btn.addEventListener('click', () => { void startRepair(); });
  viewer.addEventListener('close', () => { void cancelJob(); });
  document.addEventListener('localhub:mse-start', () => { void cancelJob(); });
  new MutationObserver(() => {
    const next = currentPath();
    if ((jobId || starting) && activePath && next && next !== activePath) void cancelJob();
  }).observe(pathNode, {subtree:true,childList:true,characterData:true});
})();
