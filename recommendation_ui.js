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
    .lh-recommend-strip{height:122px;flex:0 0 122px;border-top:1px solid #242428;background:#0d0d0f;padding:8px 14px 10px;overflow:hidden}
    .lh-recommend-head{height:20px;display:flex;align-items:center;justify-content:space-between;color:#8d8d94;font-size:10px}
    .lh-recommend-head strong{color:#d8d8dc;font-size:11px;letter-spacing:.02em}.lh-recommend-head span{color:#55555d;font-size:9px}
    .lh-recommend-row{height:82px;display:flex;gap:9px;overflow-x:auto;overflow-y:hidden;padding:3px 0 2px;scrollbar-width:thin;scrollbar-color:#333 transparent}
    .lh-rec-card{width:132px;min-width:132px;border:0;background:transparent;color:inherit;text-align:left;padding:0;cursor:pointer;display:grid;grid-template-columns:72px 1fr;grid-template-rows:41px 18px;column-gap:7px;align-items:start}
    .lh-rec-thumb{grid-row:1/3;width:72px;height:59px;border:1px solid #29292e;border-radius:6px;overflow:hidden;background:#171719;position:relative}
    .lh-rec-thumb img{width:100%;height:100%;display:block;object-fit:cover;opacity:0;transition:opacity .15s}.lh-rec-thumb img.loaded{opacity:1}
    .lh-rec-thumb::after{content:'▶';position:absolute;inset:0;display:grid;place-items:center;color:#aaa;font-size:13px;background:linear-gradient(transparent,rgba(0,0,0,.22));pointer-events:none}
    .lh-rec-card:hover .lh-rec-thumb{border-color:#55555c}.lh-rec-card:hover .lh-rec-title{color:#fff}
    .lh-rec-title{font-size:10px;line-height:1.28;color:#c4c4c9;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-all}
    .lh-rec-meta{font-size:8.5px;color:#66666d;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-top:2px}
    .lh-rec-empty{height:75px;display:flex;align-items:center;color:#55555d;font-size:10px}
    #viewer.lh-rec-visible .player-shell{height:calc(100% - 286px)!important}
    #viewer.lh-probe-portrait.lh-rec-visible .player-shell{height:calc(100% - 286px)!important;min-height:420px}
    @media(max-height:720px){.lh-recommend-strip{display:none!important}#viewer.lh-rec-visible .player-shell{height:calc(100% - 164px)!important}}
    @media(max-width:700px){.lh-recommend-strip{height:112px;flex-basis:112px;padding-left:10px;padding-right:10px}.lh-rec-card{width:122px;min-width:122px;grid-template-columns:66px 1fr}.lh-rec-thumb{width:66px;height:54px}#viewer.lh-rec-visible .player-shell,#viewer.lh-probe-portrait.lh-rec-visible .player-shell{height:calc(100% - 276px)!important}}
  `;
  document.head.appendChild(style);

  const panel = document.createElement('section');
  panel.id = 'lhRecommendations';
  panel.className = 'lh-recommend-strip hidden';
  panel.innerHTML = '<div class="lh-recommend-head"><strong>猜你想看</strong><span>本地推荐 · 不联网</span></div><div class="lh-recommend-row"></div>';
  info.insertAdjacentElement('afterend', panel);
  const row = panel.querySelector('.lh-recommend-row');

  let token = 0;
  let controller = null;
  let timer = 0;
  let currentItems = [];

  function hide() {
    token++;
    clearTimeout(timer);
    if (controller) { controller.abort(); controller = null; }
    currentItems = [];
    row.innerHTML = '';
    panel.classList.add('hidden');
    viewer.classList.remove('lh-rec-visible');
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

  function render(items) {
    currentItems = items;
    if (!items.length) { hide(); return; }
    row.innerHTML = items.map((item, index) => `
      <button class="lh-rec-card" type="button" data-rec-index="${index}" title="${esc(item.name)}">
        <span class="lh-rec-thumb"><img loading="lazy" decoding="async" src="${esc(item.thumb || '')}" alt=""></span>
        <span class="lh-rec-title">${esc(item.name)}</span>
        <span class="lh-rec-meta">${esc(item.folder || '根目录')} · ${esc(String(item.ext || '').toUpperCase())}</span>
      </button>`).join('');
    panel.classList.remove('hidden');
    viewer.classList.add('lh-rec-visible');
    panel.querySelectorAll('img').forEach(img => {
      img.addEventListener('load', () => img.classList.add('loaded'), {once:true});
      img.addEventListener('error', () => img.removeAttribute('src'), {once:true});
    });
    noteExposure(items);
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
        body:JSON.stringify({
          path,
          limit:8,
          history:compactHistory(),
          exposure:compactExposure(),
          favorites:read('localhub:favorites', [])
        })
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
    panel.classList.add('hidden');
    viewer.classList.remove('lh-rec-visible');
    timer = setTimeout(() => loadFor(path), 90);
  }

  row.addEventListener('click', e => {
    const card = e.target.closest('.lh-rec-card');
    if (!card) return;
    const item = currentItems[Number(card.dataset.recIndex) || 0];
    if (!item) return;
    if (typeof window.LocalHubOpenVideo === 'function') {
      window.LocalHubOpenVideo(item);
      return;
    }
    // Compatibility fallback for an unexpected stale smart_ui.js build.
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

  new MutationObserver(schedule).observe(pathNode, {subtree:true, childList:true, characterData:true});
  viewer.addEventListener('close', hide);
  viewer.addEventListener('cancel', hide);
  schedule();
})();
