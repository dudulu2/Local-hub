(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const readJSON = (k, fallback) => {
    try { return JSON.parse(localStorage.getItem(k) || JSON.stringify(fallback)); }
    catch { return fallback; }
  };

  const PAGE_SIZE = 30;
  const HOVER_SLOTS = 6;
  const UNSAFE_NATIVE_EXTS = new Set(['avi', 'mpg', 'mpeg', 'ts', 'mkv', 'ogv']);

  const state = {
    route: 'home', folder: '', query: '', offset: 0, total: 0, hasMore: false,
    items: [], folders: [], stats: {}, current: null, currentProbe: null,
    pack: null, packIndex: 0, tagTarget: null, requestToken: 0, clientIds: [], clientKind: '',
    playbackMode: 'native', compatJob: null, compatPoll: null, restoreTime: 0,
    favorites: new Set(readJSON('localhub:favorites', [])),
    progress: readJSON('localhub:progress', {})
  };

  const el = {
    grid: $('#grid'), title: $('#pageTitle'), meta: $('#pageMeta'), hint: $('#viewHint'), empty: $('#empty'),
    pager: $('#pager'), prevPage: $('#prevPage'), nextPage: $('#nextPage'), pageInfo: $('#pageInfo'),
    folderNav: $('#folderNav'), search: $('#searchInput'), clearSearch: $('#clearSearch'), rescan: $('#rescanBtn'), brand: $('#brandBtn'),
    viewer: $('#viewer'), closeViewer: $('#closeViewer'), stage: $('#viewerStage'), shell: $('#playerShell'), video: $('#videoPlayer'),
    playerNotice: $('#playerNotice'), playerNoticeTitle: $('#playerNoticeTitle'), playerNoticeText: $('#playerNoticeText'), compatProgress: $('#compatProgress'),
    playBtn: $('#playBtn'), currentTime: $('#currentTime'), seekBar: $('#seekBar'), durationTime: $('#durationTime'), muteBtn: $('#muteBtn'), volumeBar: $('#volumeBar'), speedSelect: $('#speedSelect'), compatBtn: $('#compatBtn'), systemPlayerBtn: $('#systemPlayerBtn'), fullscreenBtn: $('#fullscreenBtn'),
    viewerTitle: $('#viewerTitle'), viewerPath: $('#viewerPath'), viewerTagStrip: $('#viewerTagStrip'), diagnostics: $('#mediaDiagnostics'), playMode: $('#playMode'),
    favorite: $('#favoriteBtn'), manage: $('#manageBtn'), managePanel: $('#managePanel'), manageTags: $('#manageTags'), saveTags: $('#saveTags'), renameInput: $('#renameInput'), renameBtn: $('#renameBtn'), moveInput: $('#moveInput'), moveBtn: $('#moveBtn'),
    reader: $('#reader'), closeReader: $('#closeReader'), readerImage: $('#readerImage'), readerTitle: $('#readerTitle'), readerCounter: $('#readerCounter'), readerPrev: $('#readerPrev'), readerNext: $('#readerNext'),
    tagDialog: $('#tagDialog'), closeTagDialog: $('#closeTagDialog'), cancelTagDialog: $('#cancelTagDialog'), tagDialogName: $('#tagDialogName'), tagDialogInput: $('#tagDialogInput'), saveTagDialog: $('#saveTagDialog'),
    toast: $('#toast')
  };

  let thumbObserver = null, thumbQueue = [], thumbActive = 0, thumbGen = 0, searchTimer = null, lastProgressWrite = 0;
  let hoverTimer = null, hoverToken = 0, hoverCard = null, hoverController = null, hoverUrls = [];
  const controllers = new Set(), objectUrls = new Set(), probeCache = new Map();

  const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const bytes = (n = 0) => { const u=['B','KB','MB','GB','TB']; let x=Number(n)||0,i=0; while(x>=1024&&i<u.length-1){x/=1024;i++;} return `${x>=10||i===0?x.toFixed(0):x.toFixed(1)} ${u[i]}`; };
  const formatTime = sec => {
    sec = Number(sec);
    if (!Number.isFinite(sec) || sec < 0) sec = 0;
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
    return h ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` : `${m}:${String(s).padStart(2,'0')}`;
  };
  const toast = msg => { el.toast.textContent = msg; el.toast.classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(() => el.toast.classList.remove('show'), 2100); };
  const saveFav = () => localStorage.setItem('localhub:favorites', JSON.stringify([...state.favorites]));
  const saveProgress = () => localStorage.setItem('localhub:progress', JSON.stringify(state.progress));

  async function api(url, opt = {}) {
    const r = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await r.json(); } catch {}
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }
  const manage = payload => api('/api/manage', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});

  function showNotice(title, text = '', progress = null) {
    el.playerNoticeTitle.textContent = title;
    el.playerNoticeText.textContent = text;
    el.playerNotice.classList.remove('hidden');
    if (progress == null) {
      el.compatProgress.classList.add('hidden');
    } else {
      el.compatProgress.classList.remove('hidden');
      el.compatProgress.querySelector('i').style.width = `${Math.max(0, Math.min(100, progress))}%`;
    }
  }
  function hideNotice() { el.playerNotice.classList.add('hidden'); }

  function clearHoverPreview(restore = true) {
    hoverToken++;
    clearTimeout(hoverTimer); hoverTimer = null;
    if (hoverController) { hoverController.abort(); controllers.delete(hoverController); hoverController = null; }
    if (hoverCard) {
      const img = hoverCard.querySelector('img[data-thumb]');
      if (restore && img?.dataset.baseSrc) img.src = img.dataset.baseSrc;
      hoverCard.classList.remove('hover-previewing');
    }
    hoverCard = null;
    for (const u of hoverUrls) { URL.revokeObjectURL(u); objectUrls.delete(u); }
    hoverUrls = [];
  }

  function clearThumbWork() {
    clearHoverPreview(false); thumbGen++; thumbQueue = [];
    for (const c of controllers) c.abort(); controllers.clear(); thumbActive = 0;
    if (thumbObserver) { thumbObserver.disconnect(); thumbObserver = null; }
    for (const u of objectUrls) URL.revokeObjectURL(u); objectUrls.clear();
  }

  function ensureObserver() {
    if (thumbObserver) return;
    thumbObserver = new IntersectionObserver(entries => {
      const gen = thumbGen;
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        thumbObserver.unobserve(entry.target);
        thumbQueue.push({img:entry.target, gen});
      }
      pumpThumbs();
    }, {rootMargin:'320px 0px', threshold:.01});
  }

  async function pumpThumbs() {
    while (thumbActive < 2 && thumbQueue.length) {
      const job = thumbQueue.shift();
      if (!job || job.gen !== thumbGen || !job.img.isConnected) continue;
      thumbActive++;
      const c = new AbortController(); controllers.add(c);
      const thumb = job.img.closest('.thumb'); thumb?.classList.add('thumb-loading');
      try {
        const r = await fetch(job.img.dataset.thumb, {cache:'no-store', signal:c.signal});
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        if (job.gen !== thumbGen || !job.img.isConnected) continue;
        const url = URL.createObjectURL(blob); objectUrls.add(url); job.img.src = url;
        try { await job.img.decode(); } catch { throw new Error('decode failed'); }
        if (job.gen !== thumbGen || !job.img.isConnected) continue;
        job.img.dataset.baseSrc = url; job.img.classList.add('loaded');
        thumb?.classList.remove('thumb-loading','thumb-failed'); thumb?.classList.add('thumb-ready');
      } catch (e) {
        if (e.name !== 'AbortError') {
          thumb?.classList.remove('thumb-loading'); thumb?.classList.add('thumb-failed');
          const p = thumb?.querySelector('.thumb-placeholder'); if (p) p.textContent = '预览不可用';
        }
      } finally {
        controllers.delete(c); thumbActive = Math.max(0, thumbActive - 1); pumpThumbs();
      }
    }
  }

  function observeThumbs() {
    ensureObserver();
    el.grid.querySelectorAll('img[data-thumb]').forEach(img => thumbObserver.observe(img));
  }

  async function requestHoverFrame(card, item, slot, token) {
    if (token !== hoverToken || hoverCard !== card || !card.matches(':hover')) return null;
    const img = card.querySelector('img[data-thumb]'); if (!img?.dataset.baseSrc) return null;
    const c = new AbortController(); hoverController = c; controllers.add(c);
    try {
      const r = await fetch(`/api/smart/hover?path=${encodeURIComponent(item.id)}&slot=${slot}`, {cache:'no-store', signal:c.signal});
      if (r.status === 204 || !r.ok) return null;
      const blob = await r.blob();
      if (token !== hoverToken || hoverCard !== card || !card.matches(':hover')) return null;
      const url = URL.createObjectURL(blob); objectUrls.add(url); hoverUrls.push(url);
      return url;
    } catch { return null; }
    finally { controllers.delete(c); if (hoverController === c) hoverController = null; }
  }

  function scheduleHover(card, item) {
    clearHoverPreview(true); hoverCard = card; const token = ++hoverToken;
    hoverTimer = setTimeout(async () => {
      if (token !== hoverToken || hoverCard !== card || !card.matches(':hover')) return;
      const img = card.querySelector('img[data-thumb]'); if (!img?.dataset.baseSrc) return;
      const frames = [];
      for (let slot = 0; slot < HOVER_SLOTS; slot++) {
        if (token !== hoverToken || hoverCard !== card || !card.matches(':hover')) return;
        const url = await requestHoverFrame(card, item, slot, token);
        if (url) {
          frames.push(url); img.src = url; card.classList.add('hover-previewing');
          try { await img.decode(); } catch {}
        }
        await new Promise(resolve => hoverTimer = setTimeout(resolve, slot < 1 ? 520 : 430));
      }
      if (frames.length < 2) return;
      let i = 0;
      while (token === hoverToken && hoverCard === card && card.matches(':hover')) {
        img.src = frames[i % frames.length]; i++;
        await new Promise(resolve => hoverTimer = setTimeout(resolve, 620));
      }
    }, 650);
  }

  function pct(item) {
    const p = state.progress[item.id];
    return p?.duration ? Math.max(0, Math.min(100, p.time / p.duration * 100)) : 0;
  }
  function tagHtml(item) {
    if (!['video','image'].includes(item.kind)) return '';
    const chips = (item.tags || []).slice(0, 3).map(t => `<button class="tag-chip" data-tag="${esc(t)}">#${esc(t)}</button>`).join('');
    return `<div class="tag-strip" data-tag-strip="${esc(item.id)}">${chips || '<span class="no-tags">暂无标签</span>'}<button class="tag-edit" data-edit-tags="${esc(item.id)}">＋</button></div>`;
  }
  function mediaCard(item) {
    const p = pct(item), fav = state.favorites.has(item.id);
    return `<article class="card clickable" data-id="${esc(item.id)}"><div class="thumb ${item.kind==='video'?'video-thumb':''}"><div class="thumb-placeholder">准备预览</div><img data-thumb="${esc(item.thumb)}" alt="" decoding="async"><span class="badge">${item.kind==='video'?'视频':'图片'}</span><span class="badge ext">${esc((item.ext||'').toUpperCase())}</span><button class="favorite-star ${fav?'on':''}" data-fav="${esc(item.id)}">★</button>${p?`<div class="progress"><i style="width:${p}%"></i></div>`:''}</div><div class="card-title" title="${esc(item.name)}">${esc(item.name)}</div>${tagHtml(item)}<div class="card-meta"><span>${bytes(item.size)}</span><span>${esc(item.folder||'根目录')}</span></div></article>`;
  }
  const folderCard = i => `<article class="card folder-card clickable" data-folder="${esc(i.path)}"><div class="thumb"><div class="folder-glyph">▰</div><span class="badge">文件夹</span></div><div class="card-title">${esc(i.name)}</div><div class="card-meta"><span>${i.videos} 视频</span><span>${i.images} 图片</span></div></article>`;
  const packCard = i => `<article class="card pack-card clickable" data-pack="${esc(i.folder)}"><div class="thumb"><div class="thumb-placeholder">图册封面</div><img data-thumb="${esc(i.coverThumb||i.cover)}" alt="" decoding="async"><span class="pack-count">${i.count} 张</span></div><div class="card-title">${esc(i.name)}</div><div class="card-meta"><span>图包 / 图册</span><span>${esc(i.folder||'根目录')}</span></div></article>`;
  const cardHtml = i => i.kind === 'folder' ? folderCard(i) : i.kind === 'pack' ? packCard(i) : mediaCard(i);

  function updatePager() {
    const paged = state.route !== 'home' && state.total > PAGE_SIZE;
    el.pager.classList.toggle('hidden', !paged); if (!paged) return;
    const page = Math.floor(state.offset / PAGE_SIZE) + 1, pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
    el.pageInfo.textContent = `第 ${page} / ${pages} 页`; el.prevPage.disabled = state.offset <= 0; el.nextPage.disabled = !state.hasMore;
  }

  function renderFull() {
    clearThumbWork(); el.grid.innerHTML = state.items.map(cardHtml).join('');
    el.empty.classList.toggle('hidden', state.items.length > 0); bindCards(); observeThumbs(); updatePager();
  }

  function bindCards() {
    el.grid.querySelectorAll('.card:not([data-bound])').forEach(card => {
      card.dataset.bound = '1'; const item = state.items.find(x => x.id === card.dataset.id);
      card.onclick = e => {
        if (e.target.closest('[data-fav],[data-edit-tags],[data-tag]')) return;
        if (card.dataset.folder !== undefined) return openFolder(card.dataset.folder);
        if (card.dataset.pack !== undefined) return openPack(card.dataset.pack);
        if (item) item.kind === 'video' ? openViewer(item) : openSingleImage(item);
      };
      if (item?.kind === 'video') {
        card.addEventListener('mouseenter', () => scheduleHover(card, item));
        card.addEventListener('mouseleave', () => { if (hoverCard === card) clearHoverPreview(true); });
      }
    });
    el.grid.querySelectorAll('[data-fav]:not([data-bound])').forEach(b => {
      b.dataset.bound = '1'; b.onclick = e => { e.stopPropagation(); toggleFavorite(b.dataset.fav); b.classList.toggle('on', state.favorites.has(b.dataset.fav)); };
    });
    el.grid.querySelectorAll('[data-edit-tags]:not([data-bound])').forEach(b => {
      b.dataset.bound = '1'; b.onclick = e => { e.stopPropagation(); const item = state.items.find(x => x.id === b.dataset.editTags); if (item) openTagDialog(item); };
    });
    el.grid.querySelectorAll('[data-tag]:not([data-bound])').forEach(b => {
      b.dataset.bound = '1'; b.onclick = e => { e.stopPropagation(); el.search.value = b.dataset.tag; searchNow(b.dataset.tag); };
    });
  }

  function updateTagStrip(item) {
    const old = [...el.grid.querySelectorAll('[data-tag-strip]')].find(n => n.dataset.tagStrip === item.id);
    if (!old) return; const box = document.createElement('div'); box.innerHTML = tagHtml(item); old.replaceWith(box.firstElementChild); bindCards();
  }

  function navActive(route) {
    $$('.main-nav button').forEach(b => b.classList.toggle('active', b.dataset.route === route));
    $$('.folder-nav button').forEach(b => b.classList.toggle('active', route === 'folder' && b.dataset.folder === state.folder));
  }
  function renderFolders() {
    el.folderNav.innerHTML = state.folders.map(f => {
      const depth = Math.min(2, (f.path.match(/\//g) || []).length);
      return `<button class="depth-${depth}" data-folder="${esc(f.path)}"><span>▸ ${esc(f.name)}</span><small>${f.videos||f.images}</small></button>`;
    }).join('') || '<div class="side-loading">没有文件夹</div>';
    el.folderNav.querySelectorAll('button').forEach(b => b.onclick = () => openFolder(b.dataset.folder));
  }
  const scrollTopFast = () => window.scrollTo({top:0,left:0,behavior:'instant'});

  async function loadHome() {
    const token = ++state.requestToken; state.route='home'; state.folder=''; state.query=''; state.offset=0; state.total=0; state.hasMore=false; state.clientIds=[];
    navActive('home'); el.title.textContent='首页'; el.meta.textContent='正在读取轻量索引…'; el.hint.textContent='最多 15 个视频';
    const d = await api('/api/smart/home'); if (token !== state.requestToken) return;
    state.items=d.items||[]; state.folders=d.folders||[]; state.stats=d.stats||{}; state.total=state.items.length;
    renderFolders(); renderFull(); el.meta.textContent=`${state.stats.videos||0} 个视频 · ${state.stats.images||0} 张图片 · 首页只展示 ${state.items.length} 个视频`;
  }

  async function loadList(view, {offset=0}={}) {
    const token=++state.requestToken; state.route=view; state.offset=Math.max(0,offset);
    let url=`/api/smart/list?view=${encodeURIComponent(view)}&offset=${state.offset}&limit=${PAGE_SIZE}`;
    if (view==='folder') url+=`&folder=${encodeURIComponent(state.folder)}`;
    if (view==='search') url+=`&q=${encodeURIComponent(state.query)}`;
    const d=await api(url); if(token!==state.requestToken)return;
    state.items=d.items||[]; state.total=d.total||0; state.hasMore=!!d.hasMore; el.title.textContent=d.title||'媒体';
    el.meta.textContent=`${state.total} 项 · 当前页只加载 ${state.items.length} 项`; el.hint.textContent=`每页最多 ${PAGE_SIZE} 项`;
    navActive(view); renderFull(); scrollTopFast();
  }
  function openFolder(folder){state.folder=folder;state.query='';el.search.value='';loadList('folder',{offset:0}).catch(e=>toast(e.message));}
  function searchNow(q){const t=String(q||'').trim();if(!t)return loadHome().catch(e=>toast(e.message));state.query=t;state.folder='';loadList('search',{offset:0}).catch(e=>toast(e.message));}

  async function loadClientSubset(kind,{offset=0}={}){
    state.route=kind;state.folder='';state.query='';state.offset=Math.max(0,offset);navActive(kind);
    if(!state.clientIds.length||state.clientKind!==kind){state.clientKind=kind;state.clientIds=kind==='favorite'?[...state.favorites]:Object.entries(state.progress).filter(([,p])=>p?.time>5).sort((a,b)=>(b[1]?.at||0)-(a[1]?.at||0)).map(([id])=>id);}
    state.total=state.clientIds.length;state.hasMore=state.offset+PAGE_SIZE<state.total;el.title.textContent=kind==='favorite'?'收藏':'继续观看';el.meta.textContent=state.total?`共 ${state.total} 项 · 当前页最多 ${PAGE_SIZE} 项`:'这里还没有内容';el.hint.textContent='本机记录';
    if(!state.total){state.items=[];renderFull();return;}
    const ids=state.clientIds.slice(state.offset,state.offset+PAGE_SIZE);const d=await api(`/api/smart/by-ids?ids=${encodeURIComponent(ids.join('\n'))}`);state.items=d.items||[];renderFull();scrollTopFast();
  }
  function changePage(delta){const next=Math.max(0,state.offset+delta*PAGE_SIZE);if(next===state.offset)return;if(state.route==='favorite'||state.route==='continue')loadClientSubset(state.route,{offset:next}).catch(e=>toast(e.message));else loadList(state.route,{offset:next}).catch(e=>toast(e.message));}

  function toggleFavorite(id){state.favorites.has(id)?state.favorites.delete(id):state.favorites.add(id);state.clientIds=[];saveFav();if(state.current?.id===id)updateViewerFav();}
  function updateViewerFav(){el.favorite.textContent=state.current&&state.favorites.has(state.current.id)?'★ 已收藏':'☆ 收藏';}

  function renderViewerTags(item) {
    const tags = item?.tags || [];
    el.viewerTagStrip.innerHTML = `${tags.map(t=>`<button class="viewer-tag-chip" data-viewer-tag="${esc(t)}">#${esc(t)}</button>`).join('') || '<span class="viewer-no-tags">暂无标签</span>'}<button class="viewer-tag-add" id="viewerTagAdd">＋</button>`;
    el.viewerTagStrip.querySelectorAll('[data-viewer-tag]').forEach(b => b.onclick = () => { closeViewer(); el.search.value=b.dataset.viewerTag; searchNow(b.dataset.viewerTag); });
    const add = $('#viewerTagAdd'); if(add) add.onclick=()=>{if(state.current)openTagDialog(state.current);};
  }

  async function getProbe(item) {
    if (probeCache.has(item.id)) return probeCache.get(item.id);
    const d = await api(`/api/media/probe?path=${encodeURIComponent(item.id)}`);
    const probe = d.probe || {}; probeCache.set(item.id, probe); return probe;
  }

  function renderProbe(probe) {
    state.currentProbe = probe;
    if (!probe?.ok) { el.diagnostics.textContent = probe?.error || '媒体信息读取失败'; return; }
    const bits = [probe.container, probe.videoCodec, probe.audioCodec && probe.audioCodec !== 'none' ? probe.audioCodec : '', probe.width&&probe.height?`${probe.width}×${probe.height}`:'', probe.fps?`${Number(probe.fps).toFixed(2)} fps`:''].filter(Boolean);
    el.diagnostics.textContent = `${bits.join(' · ')} · ${probe.reason||''}`;
    el.compatBtn.classList.toggle('recommended', probe.strategy !== 'native');
    if (probe.duration && !Number.isFinite(el.video.duration)) updateTimeline(0, probe.duration);
  }

  function playerDuration() {
    if (Number.isFinite(el.video.duration) && el.video.duration > 0) return el.video.duration;
    const d = Number(state.currentProbe?.duration); return Number.isFinite(d) && d > 0 ? d : 0;
  }
  function updateTimeline(current = el.video.currentTime || 0, duration = playerDuration()) {
    el.currentTime.textContent = formatTime(current); el.durationTime.textContent = formatTime(duration);
    el.seekBar.value = duration > 0 ? String(Math.round(Math.max(0, Math.min(1, current/duration))*1000)) : '0';
    el.seekBar.disabled = duration <= 0;
  }
  function setMode(mode, label) {
    state.playbackMode = mode; el.playMode.textContent = label; el.playMode.classList.toggle('compat', mode === 'compat');
  }
  function resetVideoSource() {
    el.video.pause(); el.video.removeAttribute('src'); el.video.load(); updateTimeline(0, state.currentProbe?.duration || 0); el.playBtn.textContent='▶';
  }

  function loadVideoSource(url, mode='native', compatLabel='原生') {
    if (!state.current) return;
    const restore = state.restoreTime || state.progress[state.current.id]?.time || 0;
    resetVideoSource(); setMode(mode, compatLabel); el.video.src=url; el.video.load();
    const onMeta=()=>{el.video.removeEventListener('loadedmetadata',onMeta);const duration=playerDuration();if(restore>0&&(!duration||restore<duration-2)){try{el.video.currentTime=restore;}catch{}}updateTimeline(el.video.currentTime,duration);el.video.play().catch(()=>{});};
    el.video.addEventListener('loadedmetadata',onMeta);
  }

  async function startCompatibility(modeOverride = '') {
    if (!state.current) return;
    clearInterval(state.compatPoll); state.compatPoll=null; el.compatBtn.disabled=true; state.restoreTime=el.video.currentTime||state.progress[state.current.id]?.time||0; el.video.pause();
    const mode=modeOverride||state.currentProbe?.compatMode||'transcode';
    showNotice(mode==='remux'?'正在准备兼容封装':'正在准备兼容播放', mode==='remux'?'不重新编码视频，只重新整理为浏览器友好的 MP4。':'仅为当前播放生成临时 H.264/AAC 版本，原文件不会修改。',0);
    try{
      const d=await api('/api/compat/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:state.current.id,mode})});state.compatJob=d.job;
      const poll=async()=>{
        if(!state.current||!state.compatJob)return;
        try{
          const s=await api(`/api/compat/status?id=${encodeURIComponent(state.compatJob.id)}`);state.compatJob=s.job;
          if(s.job.status==='ready'){clearInterval(state.compatPoll);state.compatPoll=null;el.compatBtn.disabled=false;hideNotice();loadVideoSource(s.job.url,'compat',s.job.mode==='remux'?'兼容封装':'兼容转码');return;}
          if(s.job.status==='error'){clearInterval(state.compatPoll);state.compatPoll=null;el.compatBtn.disabled=false;showNotice('兼容播放失败',s.job.error||'FFmpeg 无法生成兼容版本');return;}
          showNotice(s.job.mode==='remux'?'正在准备兼容封装':'正在转为兼容格式',`${s.job.progress.toFixed(1)}% · ${s.job.mode==='remux'?'无损封装':'H.264/AAC 临时转换'}`,s.job.progress);
        }catch(e){clearInterval(state.compatPoll);state.compatPoll=null;el.compatBtn.disabled=false;showNotice('兼容播放失败',e.message);}
      };
      await poll(); if(state.compatJob?.status!=='ready'&&state.compatJob?.status!=='error')state.compatPoll=setInterval(poll,700);
    }catch(e){el.compatBtn.disabled=false;showNotice('兼容播放失败',e.message);}
  }

  async function openViewer(item) {
    clearHoverPreview(true); state.current=item; state.currentProbe=null; state.compatJob=null; state.restoreTime=state.progress[item.id]?.time||0;
    clearInterval(state.compatPoll);state.compatPoll=null; el.viewerTitle.textContent=item.name; el.viewerPath.textContent=item.path; el.manageTags.value=(item.tags||[]).join(', ');el.renameInput.value=item.stem||item.name.replace(/\.[^.]+$/,'');el.moveInput.value=item.folder||'';el.managePanel.classList.add('hidden');renderViewerTags(item);updateViewerFav();el.diagnostics.textContent='正在读取媒体信息…';el.compatBtn.disabled=false;el.compatBtn.classList.remove('recommended');setMode('native','原生');
    el.video.poster=item.thumb||''; resetVideoSource(); showNotice('正在分析媒体','检查容器、编码和浏览器兼容性…'); el.viewer.showModal();
    const unsafe=UNSAFE_NATIVE_EXTS.has(String(item.ext||'').toLowerCase());
    if(!unsafe) loadVideoSource(item.url,'native','原生');
    try{
      const probe=await getProbe(item);if(state.current?.id!==item.id)return;renderProbe(probe);
      if(unsafe||probe.strategy==='compat'){await startCompatibility(probe.compatMode);}
      else{hideNotice();if(probe.strategy==='conditional')showNotice('当前格式可能需要兼容播放',probe.reason||'如果出现黑屏或无法拖动时间轴，请点“兼容播放”。');setTimeout(()=>{if(state.current?.id===item.id&&probe.strategy==='conditional'&&!el.video.error)hideNotice();},2600);}
    }catch(e){if(state.current?.id!==item.id)return;el.diagnostics.textContent='诊断失败：'+e.message;if(unsafe)startCompatibility('transcode');else hideNotice();}
  }

  function persistProgress(force=false){if(!state.current)return;const duration=playerDuration();if(!duration)return;const now=Date.now();if(!force&&now-lastProgressWrite<3000)return;lastProgressWrite=now;state.progress[state.current.id]={time:el.video.currentTime||0,duration,at:now};state.clientIds=[];saveProgress();}
  function closeViewer(){persistProgress(true);clearInterval(state.compatPoll);state.compatPoll=null;resetVideoSource();hideNotice();if(el.viewer.open)el.viewer.close();state.current=null;state.currentProbe=null;state.compatJob=null;state.restoreTime=0;}

  function openSingleImage(item){state.pack={title:item.name,images:[item]};state.packIndex=0;renderReader();el.reader.showModal();}
  async function openPack(folder){const d=await api(`/api/smart/pack?folder=${encodeURIComponent(folder)}`);state.pack=d;state.packIndex=0;renderReader();el.reader.showModal();}
  function renderReader(){if(!state.pack?.images?.length)return;const i=state.pack.images[state.packIndex];el.readerImage.src=i.url;el.readerTitle.textContent=state.pack.title||i.name;el.readerCounter.textContent=`${state.packIndex+1} / ${state.pack.images.length}`;const next=state.pack.images[state.packIndex+1];if(next){const pre=new Image();pre.src=next.url;}}
  function stepReader(d){if(!state.pack?.images?.length)return;state.packIndex=(state.packIndex+d+state.pack.images.length)%state.pack.images.length;renderReader();}

  function openTagDialog(item){state.tagTarget=item;el.tagDialogName.textContent=item.name;el.tagDialogInput.value=(item.tags||[]).join(', ');el.tagDialog.showModal();setTimeout(()=>el.tagDialogInput.focus(),20);}
  async function saveTagQuick(){const item=state.tagTarget;if(!item)return;const tags=el.tagDialogInput.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean);try{await manage({action:'set_tags',paths:[item.id],tags,mode:'replace'});item.tags=tags;updateTagStrip(item);if(state.current?.id===item.id){state.current.tags=tags;renderViewerTags(state.current);el.manageTags.value=tags.join(', ');}el.tagDialog.close();toast('标签已保存');}catch(e){toast(e.message);}}
  async function rescan(){el.rescan.disabled=true;el.rescan.textContent='扫描中…';try{await api('/api/smart/rescan');probeCache.clear();await loadHome();toast('索引已刷新');}catch(e){toast(e.message);}finally{el.rescan.disabled=false;el.rescan.textContent='重新扫描';}}
  async function migrateClient(oldId,newId){if(oldId!==newId){if(state.favorites.delete(oldId)){state.favorites.add(newId);saveFav();}if(state.progress[oldId]){state.progress[newId]=state.progress[oldId];delete state.progress[oldId];saveProgress();}probeCache.delete(oldId);}state.clientIds=[];await api('/api/smart/rescan');}

  el.favorite.onclick=()=>{if(state.current){toggleFavorite(state.current.id);updateViewerFav();}};
  el.manage.onclick=()=>el.managePanel.classList.toggle('hidden');
  el.saveTags.onclick=async()=>{if(!state.current)return;const tags=el.manageTags.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean);try{await manage({action:'set_tags',paths:[state.current.id],tags,mode:'replace'});state.current.tags=tags;const listed=state.items.find(x=>x.id===state.current.id);if(listed){listed.tags=tags;updateTagStrip(listed);}renderViewerTags(state.current);toast('标签已保存');}catch(e){toast(e.message);}};
  el.renameBtn.onclick=async()=>{if(!state.current)return;const old=state.current.id;try{const d=await manage({action:'rename',path:old,stem:el.renameInput.value.trim()}),m=d.moved?.[0];if(m){await migrateClient(old,m.new);closeViewer();toast('已改名');state.route==='folder'?openFolder(state.folder):loadHome();}}catch(e){toast(e.message);}};
  el.moveBtn.onclick=async()=>{if(!state.current)return;const old=state.current.id;try{const d=await manage({action:'move',paths:[old],folder:el.moveInput.value.trim(),create:true}),m=d.moved?.[0];if(m){await migrateClient(old,m.new);closeViewer();toast('已移动');state.route==='folder'?openFolder(state.folder):loadHome();}}catch(e){toast(e.message);}};

  el.playBtn.onclick=()=>{if(!el.video.src)return;if(el.video.paused)el.video.play().catch(()=>{});else el.video.pause();};
  el.video.addEventListener('play',()=>{el.playBtn.textContent='❚❚';hideNotice();});
  el.video.addEventListener('pause',()=>{el.playBtn.textContent='▶';persistProgress(true);});
  el.video.addEventListener('timeupdate',()=>{updateTimeline();persistProgress(false);});
  el.video.addEventListener('durationchange',()=>updateTimeline());
  el.video.addEventListener('loadedmetadata',()=>updateTimeline());
  el.video.addEventListener('error',()=>{if(!state.current)return;const msg=el.video.error?`浏览器播放错误 ${el.video.error.code}`:'浏览器无法播放';showNotice('原生播放失败',`${msg}。可以使用兼容播放。`);el.compatBtn.classList.add('recommended');if(state.currentProbe?.strategy==='compat')startCompatibility(state.currentProbe.compatMode);});
  el.video.addEventListener('loadeddata',()=>{if(state.playbackMode==='native'&&el.video.videoWidth===0){showNotice('视频轨道没有正常显示','文件有时间轴但没有可渲染画面，建议使用兼容播放。');el.compatBtn.classList.add('recommended');}});

  el.seekBar.addEventListener('input',()=>{const d=playerDuration();if(d>0)el.currentTime.textContent=formatTime(d*Number(el.seekBar.value)/1000);});
  el.seekBar.addEventListener('change',()=>{const d=playerDuration();if(!d)return;const target=d*Number(el.seekBar.value)/1000;try{el.video.currentTime=target;}catch{}setTimeout(()=>{if(state.playbackMode==='native'&&Math.abs((el.video.currentTime||0)-target)>Math.max(3,d*.02)){showNotice('当前文件无法稳定拖动','媒体有时长，但浏览器没有建立完整 seek 范围。建议使用兼容播放。');el.compatBtn.classList.add('recommended');}},650);});
  el.volumeBar.oninput=()=>{el.video.volume=Number(el.volumeBar.value);el.video.muted=el.video.volume===0;el.muteBtn.textContent=el.video.muted?'🔇':'🔊';};
  el.muteBtn.onclick=()=>{el.video.muted=!el.video.muted;el.muteBtn.textContent=el.video.muted?'🔇':'🔊';};
  el.speedSelect.onchange=()=>{el.video.playbackRate=Number(el.speedSelect.value)||1;};
  el.compatBtn.onclick=()=>startCompatibility(state.currentProbe?.compatMode||'transcode');
  el.systemPlayerBtn.onclick=async()=>{if(!state.current)return;try{await api('/api/compat/open-system',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:state.current.id})});toast('已交给系统播放器');}catch(e){toast(e.message);}};
  el.fullscreenBtn.onclick=()=>{const target=el.stage;if(document.fullscreenElement)document.exitFullscreen();else target.requestFullscreen?.();};

  el.closeViewer.onclick=closeViewer;el.viewer.addEventListener('cancel',e=>{e.preventDefault();closeViewer();});
  el.closeReader.onclick=()=>el.reader.close();el.readerPrev.onclick=()=>stepReader(-1);el.readerNext.onclick=()=>stepReader(1);el.reader.addEventListener('cancel',e=>{e.preventDefault();el.reader.close();});
  el.closeTagDialog.onclick=el.cancelTagDialog.onclick=()=>el.tagDialog.close();el.saveTagDialog.onclick=saveTagQuick;el.tagDialogInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();saveTagQuick();}});
  el.prevPage.onclick=()=>changePage(-1);el.nextPage.onclick=()=>changePage(1);el.rescan.onclick=rescan;el.brand.onclick=()=>loadHome().catch(e=>toast(e.message));el.clearSearch.onclick=()=>{el.search.value='';loadHome().catch(e=>toast(e.message));};
  el.search.addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>searchNow(el.search.value),240);});
  $$('.main-nav button').forEach(b=>b.onclick=()=>{const r=b.dataset.route;state.clientIds=[];if(r==='home')loadHome();else if(r==='root'){state.folder='';loadList('folder',{offset:0});}else if(r==='favorite'||r==='continue')loadClientSubset(r,{offset:0});else loadList(r,{offset:0});});
  document.addEventListener('keydown',e=>{if(el.reader.open&&!['INPUT','TEXTAREA'].includes(e.target.tagName)){if(e.key==='ArrowLeft')stepReader(-1);if(e.key==='ArrowRight')stepReader(1);}if(el.viewer.open&&!['INPUT','TEXTAREA'].includes(e.target.tagName)){if(e.key==='Escape'){e.preventDefault();closeViewer();}if(e.key===' '){e.preventDefault();el.playBtn.click();}if(e.key==='e'||e.key==='E')el.managePanel.classList.toggle('hidden');}});
  window.addEventListener('beforeunload',()=>{persistProgress(true);clearThumbWork();clearInterval(state.compatPoll);});

  loadHome().catch(e=>{el.meta.textContent='索引加载失败';toast(e.message);});
})();
