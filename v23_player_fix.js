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
