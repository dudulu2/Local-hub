(() => {
  'use strict';

  const viewer = document.querySelector('#viewer');
  const pathNode = document.querySelector('#viewerPath');
  const info = document.querySelector('.viewer-info');
  if (!viewer || !pathNode || !info) return;

  const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); } catch { return fallback; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} };

  const style = document.createElement('style');
  style.id = 'lhRecommendationStyles';
  style.textContent = `
    html.lh-viewer-modal-lock,html.lh-viewer-modal-lock body{overflow:hidden!important}
    #viewer.lh-rec-page{overflow-x:hidden!important;overflow-y:auto!important;overscroll-behavior:contain!important;scrollbar-gutter:stable}
    .lh-recommend-page{border-top:1px solid #242428;background:#0d0d0f;padding:18px 18px 24px;min-height:210px}
    .lh-recommend-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:14px;color:#8d8d94}
    .lh-recommend-head strong{color:#eeeeef;font-size:15px;line-height:1;font-weight:850;letter-spacing:-.02em}
    .lh-recommend-head span{color:#65656d;font-size:9px;white-space:nowrap}
    .lh-recommend-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:15px 12px;overflow:visible}
    .lh-rec-card{min-width:0;border:0;background:transparent;color:inherit;text-align:left;padding:0;cursor:pointer;display:block}
    .lh-rec-thumb{width:100%;aspect-ratio:16/9;border:1px solid #29292e;border-radius:8px;overflow:hidden;background:linear-gradient(135deg,#19191c,#101012);position:relative;display:block}
    .lh-rec-thumb img{position:absolute;inset:0;width:100%;height:100%;display:block;object-fit:cover;opacity:0;transition:opacity .12s ease}
    .lh-rec-thumb img.loaded{opacity:1}
    .lh-rec-thumb::after{content:'▶';position:absolute;inset:0;display:grid;place-items:center;color:#b8b8be;font-size:18px;background:linear-gradient(transparent 58%,rgba(0,0,0,.38));pointer-events:none;transition:opacity .12s}
    .lh-rec-thumb:has(img.loaded)::after{opacity:.15}
    .lh-rec-card.hover-previewing .lh-rec-thumb::after{opacity:0}
    .lh-rec-card:hover .lh-rec-thumb{border-color:#56565e}.lh-rec-card:hover .lh-rec-title{color:#fff}
    .lh-rec-title{display:block;margin-top:7px;color:#d2d2d6;font-size:11px;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .lh-rec-meta{display:block;margin-top:3px;color:#686870;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    @media(max-width:980px){.lh-recommend-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
    @media(max-width:680px){.lh-recommend-page{padding:15px 11px 20px}.lh-recommend-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:13px 9px}.lh-recommend-head{margin-bottom:11px}.lh-rec-title{font-size:10px}}
  `;
  document.head.appendChild(style);

  const panel = document.createElement('section');
  panel.id = 'lhRecommendations';
  panel.className = 'lh-recommend-page hidden';
  panel.innerHTML = '<div class="lh-recommend-head"><strong>猜你想看</strong><span>本地推荐 · 缓存预览</span></div><div class="lh-recommend-grid"></div>';
  info.insertAdjacentElement('afterend', panel);
  const grid = panel.querySelector('.lh-recommend-grid');

  let token = 0;
  let controller = null;
  let thumbController = null;
  let previewController = null;
  let previewTimer = 0;
  let previewLoopToken = 0;
  let timer = 0;
  let currentItems = [];
  const objectUrls = new Set();

  function lockBackground() {
    if (viewer.open) document.documentElement.classList.add('lh-viewer-modal-lock');
  }

  function stopPreview(restore = true) {
    previewLoopToken++;
    clearTimeout(previewTimer);
    previewTimer = 0;
    if (previewController) { previewController.abort(); previewController = null; }
    const active = grid.querySelector('.lh-rec-card.hover-previewing');
    if (active) {
      active.classList.remove('hover-previewing');
      const img = active.querySelector('img');
      if (restore && img?.dataset.baseSrc) img.src = img.dataset.baseSrc;
    }
  }

  function releaseThumbs() {
    stopPreview(false);
    if (thumbController) { thumbController.abort(); thumbController = null; }
    for (const url of objectUrls) URL.revokeObjectURL(url);
    objectUrls.clear();
  }

  function hide() {
    token++;
    clearTimeout(timer);
    if (controller) { controller.abort(); controller = null; }
    releaseThumbs();
    currentItems = [];
    grid.innerHTML = '';
    panel.classList.add('hidden');
    if (!viewer.open) {
      viewer.classList.remove('lh-rec-page');
      document.documentElement.classList.remove('lh-viewer-modal-lock');
    }
  }

  function compactHistory() {
    const raw = read('localhub:progress', {});
    const rows = Object.entries(raw || {}).sort((a,b) => (b[1]?.at || 0) - (a[1]?.at || 0)).slice(0, 160);
    return Object.fromEntries(rows);
  }

  function compactExposure() {
    const raw = read('localhub:recExposure', {});
    const now = Date.now();
    const rows = Object.entries(raw || {}).filter(([,v]) => v && now - (Number(v.at) || 0) < 45 * 86400000).slice(-240);
    return Object.fromEntries(rows);
  }

  function noteExposure(items) {
    const exposure = compactExposure();
    const now = Date.now();
    for (const item of items) {
      const old = exposure[item.id] || {};
      exposure[item.id] = {at: now, count: Math.min(99, (Number(old.count) || 0) + 1)};
    }
    write('localhub:recExposure', exposure);
  }

  function queueWarm(items) {
    const paths = items.map(item => item.id).filter(Boolean).slice(0, 16);
    if (!paths.length) return;
    fetch('/api/stable2/warm', {
      method:'POST', cache:'no-store',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({paths, includeHover:true}),
    }).catch(() => {});
  }

  async function loadThumb(img, item, signal) {
    try {
      const response = await fetch(item.thumb || `/api/recommend/thumb?path=${encodeURIComponent(item.id || '')}`, {cache:'no-store', signal});
      if (!response.ok || response.status === 204) return;
      const blob = await response.blob();
      if (!blob.size || signal.aborted) return;
      const url = URL.createObjectURL(blob);
      objectUrls.add(url);
      img.onload = () => img.classList.add('loaded');
      img.dataset.baseSrc = url;
      img.src = url;
    } catch (e) {
      if (e?.name !== 'AbortError') console.debug('[LocalHub recommendation thumb]', e);
    }
  }

  async function loadThumbQueue(items) {
    thumbController = new AbortController();
    const signal = thumbController.signal;
    const jobs = [...grid.querySelectorAll('.lh-rec-card')].map((card, index) => ({img: card.querySelector('img'), item: items[index]})).filter(x => x.img && x.item);
    let cursor = 0;
    const worker = async () => {
      while (cursor < jobs.length && !signal.aborted) {
        const job = jobs[cursor++];
        await loadThumb(job.img, job.item, signal);
      }
    };
    await Promise.all([worker(), worker(), worker(), worker()]);
  }

  async function cachedFrame(item, slot, signal) {
    const response = await fetch(`/api/recommend/hover?path=${encodeURIComponent(item.id || '')}&slot=${slot}`, {cache:'no-store', signal});
    if (!response.ok || response.status === 204) return null;
    const blob = await response.blob();
    if (!blob.size || signal.aborted) return null;
    const url = URL.createObjectURL(blob);
    objectUrls.add(url);
    return url;
  }

  function schedulePreview(card, item) {
    stopPreview(true);
    const myLoop = ++previewLoopToken;
    previewTimer = window.setTimeout(async () => {
      if (myLoop !== previewLoopToken || !card.matches(':hover')) return;
      previewController = new AbortController();
      const signal = previewController.signal;
      let frames = [];
      try {
        frames = (await Promise.all([...Array(6)].map((_, slot) => cachedFrame(item, slot, signal)))).filter(Boolean);
      } catch {}
      if (signal.aborted || myLoop !== previewLoopToken || !card.matches(':hover') || frames.length < 2) return;
      const img = card.querySelector('img');
      if (!img) return;
      card.classList.add('hover-previewing');
      let i = 0;
      while (myLoop === previewLoopToken && card.matches(':hover')) {
        img.src = frames[i++ % frames.length];
        img.classList.add('loaded');
        await new Promise(resolve => previewTimer = window.setTimeout(resolve, 620));
      }
    }, 480);
  }

  function render(items) {
    releaseThumbs();
    currentItems = items;
    if (!items.length) { hide(); return; }
    grid.innerHTML = items.map((item, index) => `
      <button class="lh-rec-card" type="button" data-rec-index="${index}" data-rec-id="${esc(item.id)}" title="${esc(item.name)}">
        <span class="lh-rec-thumb"><img alt="" decoding="async"></span>
        <span class="lh-rec-title">${esc(item.name)}</span>
        <span class="lh-rec-meta">${esc(item.folder || '根目录')} · ${esc(String(item.ext || '').toUpperCase())}</span>
      </button>`).join('');
    panel.classList.remove('hidden');
    viewer.classList.add('lh-rec-page');
    lockBackground();
    noteExposure(items);
    queueWarm(items);
    loadThumbQueue(items).catch(() => {});
  }

  async function loadFor(path) {
    const myToken = ++token;
    if (controller) controller.abort();
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 1800);
    try {
      const response = await fetch('/api/recommend', {
        method:'POST', cache:'no-store', signal:controller.signal,
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({path, limit:8, history:compactHistory(), exposure:compactExposure(), favorites:read('localhub:favorites', [])})
      });
      if (!response.ok) return;
      const data = await response.json();
      if (myToken !== token || !viewer.open || (pathNode.textContent || '').trim() !== path) return;
      const items = Array.isArray(data.items) ? data.items.filter(x => x && x.kind === 'video' && x.id !== path) : [];
      render(items.slice(0, 8));
    } catch (e) {
      if (e?.name !== 'AbortError' && myToken === token) hide();
    } finally {
      clearTimeout(timeout);
      if (myToken === token) controller = null;
    }
  }

  function schedule() {
    clearTimeout(timer);
    const path = (pathNode.textContent || '').trim();
    if (!viewer.open || !path) { hide(); return; }
    viewer.classList.add('lh-rec-page');
    lockBackground();
    panel.classList.add('hidden');
    releaseThumbs();
    currentItems = [];
    grid.innerHTML = '';
    viewer.scrollTop = 0;
    timer = setTimeout(() => loadFor(path), 90);
  }

  grid.addEventListener('pointerover', e => {
    const card = e.target.closest('.lh-rec-card');
    if (!card || card.contains(e.relatedTarget)) return;
    const item = currentItems[Number(card.dataset.recIndex) || 0];
    if (item) schedulePreview(card, item);
  });
  grid.addEventListener('pointerout', e => {
    const card = e.target.closest('.lh-rec-card');
    if (!card || card.contains(e.relatedTarget)) return;
    stopPreview(true);
  });

  grid.addEventListener('click', e => {
    const card = e.target.closest('.lh-rec-card');
    if (!card) return;
    const item = currentItems[Number(card.dataset.recIndex) || 0];
    if (!item) return;
    viewer.scrollTop = 0;
    if (typeof window.LocalHubOpenVideo === 'function') {
      window.LocalHubOpenVideo(item);
      return;
    }
    const close = document.querySelector('#closeViewer');
    const search = document.querySelector('#searchInput');
    close?.click();
    if (!search) return;
    search.value = item.name || item.id;
    search.dispatchEvent(new Event('input', {bubbles:true}));
    const deadline = Date.now() + 3500;
    const poll = setInterval(() => {
      const target = [...document.querySelectorAll('.card[data-id]')].find(node => node.dataset.id === item.id);
      if (target) { clearInterval(poll); target.click(); }
      else if (Date.now() > deadline) clearInterval(poll);
    }, 120);
  });

  viewer.addEventListener('wheel', e => {
    if (!viewer.open || e.target.closest('input[type="range"],select')) return;
    const max = Math.max(0, viewer.scrollHeight - viewer.clientHeight);
    if (!max) return;
    viewer.scrollTop = Math.max(0, Math.min(max, viewer.scrollTop + e.deltaY));
    e.preventDefault();
  }, {passive:false});

  new MutationObserver(schedule).observe(pathNode, {subtree:true, childList:true, characterData:true});
  viewer.addEventListener('close', () => {
    hide();
    viewer.scrollTop = 0;
    document.documentElement.classList.remove('lh-viewer-modal-lock');
  });
  viewer.addEventListener('cancel', () => {
    hide();
    viewer.scrollTop = 0;
    document.documentElement.classList.remove('lh-viewer-modal-lock');
  });
  schedule();
})();
