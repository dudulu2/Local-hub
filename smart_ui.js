(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const readJSON = (k, f) => { try { return JSON.parse(localStorage.getItem(k) || JSON.stringify(f)); } catch { return f; } };
  const state = {
    route: 'home', folder: '', query: '', offset: 0, hasMore: false, items: [], folders: [], stats: {},
    favorites: new Set(readJSON('localhub:favorites', [])), progress: readJSON('localhub:progress', {}),
    current: null, pack: null, packIndex: 0, tagTarget: null, requestToken: 0,
  };
  const els = {
    grid: $('#grid'), title: $('#pageTitle'), meta: $('#pageMeta'), hint: $('#viewHint'), empty: $('#empty'), more: $('#loadMore'),
    folderNav: $('#folderNav'), search: $('#searchInput'), clearSearch: $('#clearSearch'), rescan: $('#rescanBtn'), brand: $('#brandBtn'),
    viewer: $('#viewer'), closeViewer: $('#closeViewer'), video: $('#videoPlayer'), viewerTitle: $('#viewerTitle'), viewerPath: $('#viewerPath'),
    viewerTags: $('#viewerTags'), favorite: $('#favoriteBtn'), manage: $('#manageBtn'), managePanel: $('#managePanel'),
    manageTags: $('#manageTags'), saveTags: $('#saveTags'), renameInput: $('#renameInput'), renameBtn: $('#renameBtn'), moveInput: $('#moveInput'), moveBtn: $('#moveBtn'),
    reader: $('#reader'), closeReader: $('#closeReader'), readerImage: $('#readerImage'), readerTitle: $('#readerTitle'), readerCounter: $('#readerCounter'),
    readerPrev: $('#readerPrev'), readerNext: $('#readerNext'), tagDialog: $('#tagDialog'), closeTagDialog: $('#closeTagDialog'), cancelTagDialog: $('#cancelTagDialog'),
    tagDialogName: $('#tagDialogName'), tagDialogInput: $('#tagDialogInput'), saveTagDialog: $('#saveTagDialog'), toast: $('#toast')
  };

  let thumbObserver = null;
  let thumbQueue = [];
  let thumbActive = 0;
  let thumbGeneration = 0;
  const thumbControllers = new Set();
  const objectUrls = new Set();
  let searchTimer = null;
  let lastProgressWrite = 0;

  function toast(msg){ els.toast.textContent=msg; els.toast.classList.add('show'); clearTimeout(toast.t); toast.t=setTimeout(()=>els.toast.classList.remove('show'),2200); }
  function esc(s=''){ return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function bytes(n=0){ const u=['B','KB','MB','GB','TB'];let i=0,x=Number(n)||0;while(x>=1024&&i<u.length-1){x/=1024;i++;}return `${x>=10||i===0?x.toFixed(0):x.toFixed(1)} ${u[i]}`; }
  function saveFav(){ localStorage.setItem('localhub:favorites',JSON.stringify([...state.favorites])); }
  function saveProgress(){ localStorage.setItem('localhub:progress',JSON.stringify(state.progress)); }

  async function api(url, options){ const r=await fetch(url,{cache:'no-store',...options}); let data={}; try{data=await r.json();}catch{} if(!r.ok)throw new Error(data.error||`HTTP ${r.status}`); return data; }
  async function manage(payload){ return api('/api/manage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); }

  function resetThumbnails(){
    thumbGeneration++; thumbQueue=[];
    for(const c of thumbControllers)c.abort(); thumbControllers.clear(); thumbActive=0;
    for(const url of objectUrls)URL.revokeObjectURL(url); objectUrls.clear();
    if(thumbObserver){thumbObserver.disconnect(); thumbObserver=null;}
  }
  function ensureThumbObserver(){
    if(thumbObserver)return;
    thumbObserver=new IntersectionObserver(entries=>{
      const gen=thumbGeneration;
      for(const e of entries){if(!e.isIntersecting)continue;thumbObserver.unobserve(e.target);thumbQueue.push({img:e.target,gen});}
      pumpThumbs();
    },{rootMargin:'320px 0px',threshold:.01});
  }
  async function pumpThumbs(){
    while(thumbActive<2&&thumbQueue.length){
      const job=thumbQueue.shift(); if(!job||job.gen!==thumbGeneration||!job.img.isConnected)continue;
      thumbActive++; const controller=new AbortController(); thumbControllers.add(controller);
      try{
        const r=await fetch(job.img.dataset.thumb,{cache:'no-store',signal:controller.signal});
        if(!r.ok)throw new Error(); const blob=await r.blob();
        if(job.gen!==thumbGeneration||!job.img.isConnected)continue;
        const url=URL.createObjectURL(blob); objectUrls.add(url); job.img.src=url; job.img.classList.add('loaded');
      }catch(e){ if(e.name!=='AbortError')job.img.closest('.thumb')?.classList.add('thumb-failed'); }
      finally{ thumbControllers.delete(controller); thumbActive=Math.max(0,thumbActive-1); pumpThumbs(); }
    }
  }
  function observeThumbs(){ensureThumbObserver();els.grid.querySelectorAll('img[data-thumb]').forEach(img=>thumbObserver.observe(img));}

  function progressPct(item){const p=state.progress[item.id];return p?.duration?Math.max(0,Math.min(100,p.time/p.duration*100)):0;}
  function tagStrip(item){
    if(!['video','image'].includes(item.kind))return '';
    const tags=(item.tags||[]).slice(0,3).map(t=>`<button class="tag-chip" data-tag="${esc(t)}">#${esc(t)}</button>`).join('');
    return `<div class="tag-strip">${tags||'<span class="no-tags">暂无标签</span>'}<button class="tag-edit" data-edit-tags="${esc(item.id)}">＋</button></div>`;
  }
  function mediaCard(item){
    const pct=progressPct(item); const fav=state.favorites.has(item.id);
    const img=`<div class="thumb-placeholder">准备预览</div><img data-thumb="${esc(item.thumb)}" alt="" decoding="async">`;
    return `<article class="card clickable" data-id="${esc(item.id)}">
      <div class="thumb ${item.kind==='video'?'video-thumb':''}">${img}<span class="badge">${item.kind==='video'?'视频':'图片'}</span><span class="badge ext">${esc((item.ext||'').toUpperCase())}</span>
      <button class="favorite-star ${fav?'on':''}" data-fav="${esc(item.id)}">★</button>${pct?`<div class="progress"><i style="width:${pct}%"></i></div>`:''}</div>
      <div class="card-title" title="${esc(item.name)}">${esc(item.name)}</div>${tagStrip(item)}
      <div class="card-meta"><span>${bytes(item.size)}</span><span>${esc(item.folder||'根目录')}</span></div>
    </article>`;
  }
  function folderCard(item){return `<article class="card folder-card clickable" data-folder="${esc(item.path)}"><div class="thumb"><div class="folder-glyph">▰</div><span class="badge">文件夹</span></div><div class="card-title">${esc(item.name)}</div><div class="card-meta"><span>${item.videos} 视频</span><span>${item.images} 图片</span></div></article>`;}
  function packCard(item){return `<article class="card pack-card clickable" data-pack="${esc(item.folder)}"><div class="thumb"><div class="thumb-placeholder">图册封面</div><img data-thumb="${esc(item.coverThumb||item.cover)}" alt="" decoding="async"><span class="pack-count">${item.count} 张</span></div><div class="card-title">${esc(item.name)}</div><div class="card-meta"><span>图包 / 图册</span><span>${esc(item.folder||'根目录')}</span></div></article>`;}
  function render(append=false){
    if(!append)resetThumbnails();
    const html=state.items.map(item=>item.kind==='folder'?folderCard(item):item.kind==='pack'?packCard(item):mediaCard(item)).join('');
    if(append)els.grid.insertAdjacentHTML('beforeend',html);else els.grid.innerHTML=html;
    els.empty.classList.toggle('hidden',state.items.length>0); els.more.classList.toggle('hidden',!state.hasMore);
    bindCards(); observeThumbs();
  }
  function bindCards(){
    els.grid.querySelectorAll('.card:not([data-bound])').forEach(card=>{
      card.dataset.bound='1'; card.addEventListener('click',e=>{
        if(e.target.closest('[data-fav],[data-edit-tags],[data-tag]'))return;
        if(card.dataset.folder!==undefined)return openFolder(card.dataset.folder);
        if(card.dataset.pack!==undefined)return openPack(card.dataset.pack);
        const item=state.items.find(x=>x.id===card.dataset.id);if(item){if(item.kind==='video')openViewer(item);else openSingleImage(item);}
      });
    });
    els.grid.querySelectorAll('[data-fav]:not([data-bound])').forEach(btn=>{btn.dataset.bound='1';btn.onclick=e=>{e.stopPropagation();toggleFavorite(btn.dataset.fav);btn.classList.toggle('on',state.favorites.has(btn.dataset.fav));};});
    els.grid.querySelectorAll('[data-edit-tags]:not([data-bound])').forEach(btn=>{btn.dataset.bound='1';btn.onclick=e=>{e.stopPropagation();const item=state.items.find(x=>x.id===btn.dataset.editTags);if(item)openTagDialog(item);};});
    els.grid.querySelectorAll('[data-tag]:not([data-bound])').forEach(btn=>{btn.dataset.bound='1';btn.onclick=e=>{e.stopPropagation();els.search.value=btn.dataset.tag;searchNow(btn.dataset.tag);};});
  }

  function navActive(route){$$('.main-nav button').forEach(b=>b.classList.toggle('active',b.dataset.route===route));$$('.folder-nav button').forEach(b=>b.classList.toggle('active',route==='folder'&&b.dataset.folder===state.folder));}
  function renderFolders(){
    els.folderNav.innerHTML=state.folders.map(f=>{const depth=Math.min(2,(f.path.match(/\//g)||[]).length);return `<button class="depth-${depth}" data-folder="${esc(f.path)}"><span>▸ ${esc(f.name)}</span><small>${f.videos||f.images}</small></button>`;}).join('')||'<div class="side-loading">没有文件夹</div>';
    els.folderNav.querySelectorAll('button').forEach(b=>b.onclick=()=>openFolder(b.dataset.folder));
  }

  async function loadHome(){
    const token=++state.requestToken; state.route='home';state.folder='';state.offset=0;navActive('home');els.title.textContent='首页';els.meta.textContent='只保留 13–15 个视频。根目录优先，不足时从不同文件夹抽取。';els.hint.textContent='轻量首页';
    const data=await api('/api/smart/home');if(token!==state.requestToken)return;state.items=data.items||[];state.folders=data.folders||[];state.stats=data.stats||{};state.hasMore=false;renderFolders();render();
    els.meta.textContent=`${state.stats.videos||0} 个视频 · ${state.stats.images||0} 张图片 · 首页仅展示 ${state.items.length} 个视频`;
  }
  async function loadList(view, opts={}){
    const token=++state.requestToken;const append=!!opts.append;const offset=append?state.items.length:0;state.route=view;if(!append)state.offset=0;
    let url=`/api/smart/list?view=${encodeURIComponent(view)}&offset=${offset}&limit=30`;
    if(view==='folder')url+=`&folder=${encodeURIComponent(state.folder)}`;if(view==='search')url+=`&q=${encodeURIComponent(state.query)}`;
    const data=await api(url);if(token!==state.requestToken)return;
    if(append)state.items.push(...(data.items||[]));else state.items=data.items||[];state.hasMore=!!data.hasMore;state.offset=state.items.length;
    els.title.textContent=data.title||'媒体';els.meta.textContent=`${data.total||0} 项 · 当前只加载 ${state.items.length} 项`;els.hint.textContent=state.hasMore?'按页加载，避免一次渲染整个媒体库':'已到末尾';navActive(view);render(append);
  }
  function openFolder(folder){state.folder=folder;state.query='';els.search.value='';loadList('folder');}
  function searchNow(q){const text=String(q||'').trim();if(!text){loadHome();return;}state.query=text;state.folder='';loadList('search');}
  async function loadClientSubset(kind){
    state.route=kind;state.folder='';state.query='';navActive(kind);const ids=kind==='favorite'?[...state.favorites]:Object.entries(state.progress).filter(([,p])=>p?.time>5).map(([id])=>id);
    els.title.textContent=kind==='favorite'?'收藏':'继续观看';els.meta.textContent=ids.length?`共 ${ids.length} 项`:'这里还没有内容';els.hint.textContent='本机记录';state.hasMore=false;
    if(!ids.length){state.items=[];render();return;}
    const data=await api(`/api/smart/by-ids?ids=${encodeURIComponent(ids.slice(0,120).join('\n'))}`);state.items=data.items||[];render();
  }

  function toggleFavorite(id){if(state.favorites.has(id))state.favorites.delete(id);else state.favorites.add(id);saveFav();if(state.current?.id===id)updateViewerFav();}
  function updateViewerFav(){const on=state.current&&state.favorites.has(state.current.id);els.favorite.textContent=on?'★ 已收藏':'☆ 收藏';}
  function openViewer(item){
    state.current=item;els.video.src=item.url;els.viewerTitle.textContent=item.name;els.viewerPath.textContent=item.path;els.viewerTags.innerHTML=(item.tags||[]).map(t=>`<span>#${esc(t)}</span>`).join('');els.manageTags.value=(item.tags||[]).join(', ');els.renameInput.value=item.stem||item.name.replace(/\.[^.]+$/,'');els.moveInput.value=item.folder||'';els.managePanel.classList.add('hidden');updateViewerFav();els.viewer.showModal();
    const p=state.progress[item.id];els.video.addEventListener('loadedmetadata',function restore(){els.video.removeEventListener('loadedmetadata',restore);if(p?.time&&p.time<els.video.duration-3)els.video.currentTime=p.time;els.video.play().catch(()=>{});});
  }
  function closeViewer(){persistProgress(true);els.video.pause();els.video.removeAttribute('src');els.video.load();els.viewer.close();state.current=null;}
  function persistProgress(force=false){if(!state.current||!Number.isFinite(els.video.duration)||els.video.duration<=0)return;const now=Date.now();if(!force&&now-lastProgressWrite<3000)return;lastProgressWrite=now;state.progress[state.current.id]={time:els.video.currentTime,duration:els.video.duration,at:now};saveProgress();}
  function openSingleImage(item){state.pack={title:item.name,images:[item]};state.packIndex=0;renderReader();els.reader.showModal();}
  async function openPack(folder){const data=await api(`/api/smart/pack?folder=${encodeURIComponent(folder)}`);state.pack=data;state.packIndex=0;renderReader();els.reader.showModal();}
  function renderReader(){if(!state.pack?.images?.length)return;const item=state.pack.images[state.packIndex];els.readerImage.src=item.url;els.readerTitle.textContent=state.pack.title||item.name;els.readerCounter.textContent=`${state.packIndex+1} / ${state.pack.images.length}`;const next=state.pack.images[state.packIndex+1];if(next){const preload=new Image();preload.src=next.url;}}
  function stepReader(delta){if(!state.pack?.images?.length)return;state.packIndex=(state.packIndex+delta+state.pack.images.length)%state.pack.images.length;renderReader();}

  function openTagDialog(item){state.tagTarget=item;els.tagDialogName.textContent=item.name;els.tagDialogInput.value=(item.tags||[]).join(', ');els.tagDialog.showModal();setTimeout(()=>els.tagDialogInput.focus(),30);}
  async function saveTagDialog(){const item=state.tagTarget;if(!item)return;const tags=els.tagDialogInput.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean);try{await manage({action:'set_tags',paths:[item.id],tags,mode:'replace'});item.tags=tags;els.tagDialog.close();render();toast('标签已保存');}catch(e){toast(e.message);}}
  async function refreshCatalog(){els.rescan.disabled=true;els.rescan.textContent='扫描中…';try{await api('/api/smart/rescan');await loadHome();toast('索引已刷新');}catch(e){toast(e.message);}finally{els.rescan.disabled=false;els.rescan.textContent='重新扫描';}}
  async function reindexAfterManage(oldId,newId){if(oldId!==newId){if(state.favorites.delete(oldId)){state.favorites.add(newId);saveFav();}if(state.progress[oldId]){state.progress[newId]=state.progress[oldId];delete state.progress[oldId];saveProgress();}}await api('/api/smart/rescan');}

  els.favorite.onclick=()=>{if(state.current)toggleFavorite(state.current.id);};
  els.manage.onclick=()=>els.managePanel.classList.toggle('hidden');
  els.saveTags.onclick=async()=>{if(!state.current)return;const tags=els.manageTags.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean);try{await manage({action:'set_tags',paths:[state.current.id],tags,mode:'replace'});state.current.tags=tags;els.viewerTags.innerHTML=tags.map(t=>`<span>#${esc(t)}</span>`).join('');toast('标签已保存');}catch(e){toast(e.message);}};
  els.renameBtn.onclick=async()=>{if(!state.current)return;const old=state.current.id;try{const d=await manage({action:'rename',path:old,stem:els.renameInput.value.trim()});const moved=d.moved?.[0];if(moved){await reindexAfterManage(old,moved.new);toast('已改名');closeViewer();state.route==='folder'?openFolder(state.folder):loadHome();}}catch(e){toast(e.message);}};
  els.moveBtn.onclick=async()=>{if(!state.current)return;const old=state.current.id;try{const d=await manage({action:'move',paths:[old],folder:els.moveInput.value.trim(),create:true});const moved=d.moved?.[0];if(moved){await reindexAfterManage(old,moved.new);toast('已移动');closeViewer();state.route==='folder'?openFolder(state.folder):loadHome();}}catch(e){toast(e.message);}};
  els.video.addEventListener('timeupdate',()=>persistProgress(false));els.video.addEventListener('pause',()=>persistProgress(true));
  els.closeViewer.onclick=closeViewer;els.viewer.addEventListener('cancel',e=>{e.preventDefault();closeViewer();});
  els.closeReader.onclick=()=>els.reader.close();els.readerPrev.onclick=()=>stepReader(-1);els.readerNext.onclick=()=>stepReader(1);els.reader.addEventListener('cancel',e=>{e.preventDefault();els.reader.close();});
  els.closeTagDialog.onclick=els.cancelTagDialog.onclick=()=>els.tagDialog.close();els.saveTagDialog.onclick=saveTagDialog;els.tagDialogInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();saveTagDialog();}});
  els.more.onclick=()=>loadList(state.route,{append:true});els.rescan.onclick=refreshCatalog;els.brand.onclick=loadHome;els.clearSearch.onclick=()=>{els.search.value='';loadHome();};
  els.search.addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>searchNow(els.search.value),260);});
  $$('.main-nav button').forEach(b=>b.onclick=()=>{const r=b.dataset.route;if(r==='home')loadHome();else if(r==='root'){state.folder='';loadList('folder');}else if(r==='favorite'||r==='continue')loadClientSubset(r);else loadList(r);});
  document.addEventListener('keydown',e=>{if(els.reader.open&&!['INPUT','TEXTAREA'].includes(e.target.tagName)){if(e.key==='ArrowLeft')stepReader(-1);if(e.key==='ArrowRight')stepReader(1);}if(els.viewer.open&&!['INPUT','TEXTAREA'].includes(e.target.tagName)&&e.key==='Escape'){e.preventDefault();closeViewer();}});
  window.addEventListener('beforeunload',()=>{persistProgress(true);resetThumbnails();});

  loadHome().catch(e=>{els.meta.textContent='索引加载失败';toast(e.message);});
})();
