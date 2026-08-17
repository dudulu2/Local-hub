const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const readJSON = (key, fallback) => {
  try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); }
  catch { return fallback; }
};

const state = {
  items: [],
  filtered: [],
  root: '',
  activeFilter: 'all',
  activeFolder: '',
  activeTag: '',
  search: '',
  sort: 'modified-desc',
  compact: false,
  currentIndex: -1,
  viewerList: [],
  viewerAutoplay: true,
  favorites: new Set(readJSON('localhub:favorites', [])),
  progress: readJSON('localhub:progress', {}),
  tagStats: [],
  organizeMode: false,
  selected: new Set(),
  manageDraftTags: [],
  recentFolders: readJSON('localhub:recentFolders', []),
};

const els = {
  grid: $('#mediaGrid'), empty: $('#emptyState'), resultCount: $('#resultCount'), summary: $('#summaryText'),
  pageTitle: $('#pageTitle'), gridTitle: $('#gridTitle'), folders: $('#folderList'), tags: $('#tagList'),
  clearTagFilter: $('#clearTagFilter'), activeFilterBar: $('#activeFilterBar'), search: $('#searchInput'),
  clearSearch: $('#clearSearch'), sort: $('#sortSelect'), density: $('#densityBtn'), rescan: $('#rescanBtn'),
  settings: $('#settingsBtn'), organize: $('#organizeBtn'), viewer: $('#viewer'), video: $('#videoPlayer'),
  image: $('#imageViewer'), close: $('#closeViewer'), prev: $('#prevBtn'), next: $('#nextBtn'),
  viewerTitle: $('#viewerTitle'), viewerPath: $('#viewerPath'), viewerDetails: $('#viewerDetails'),
  viewerTagStrip: $('#viewerTagStrip'), favorite: $('#favoriteBtn'), manage: $('#manageBtn'),
  manageDrawer: $('#manageDrawer'), closeManage: $('#closeManageBtn'), manageTags: $('#manageTags'),
  tagInput: $('#tagInput'), addTag: $('#addTagBtn'), tagSuggestions: $('#tagSuggestions'), saveTags: $('#saveTagsBtn'),
  renameInput: $('#renameInput'), renameExt: $('#renameExt'), rename: $('#renameBtn'),
  moveFolderInput: $('#moveFolderInput'), folderOptions: $('#folderOptions'), recentFolders: $('#recentFolders'), move: $('#moveBtn'),
  continueSection: $('#continueSection'), continueRail: $('#continueRail'), continueCount: $('#continueCount'),
  batchBar: $('#batchBar'), selectedCount: $('#selectedCount'), selectAll: $('#selectAllBtn'),
  batchTag: $('#batchTagBtn'), batchMove: $('#batchMoveBtn'), exitOrganize: $('#exitOrganizeBtn'),
  batchDialog: $('#batchDialog'), batchDialogTitle: $('#batchDialogTitle'), batchDialogHint: $('#batchDialogHint'),
  batchTagForm: $('#batchTagForm'), batchMoveForm: $('#batchMoveForm'), batchTagInput: $('#batchTagInput'),
  batchTagSuggestions: $('#batchTagSuggestions'), applyBatchTag: $('#applyBatchTag'),
  batchMoveInput: $('#batchMoveInput'), applyBatchMove: $('#applyBatchMove'), closeBatchDialog: $('#closeBatchDialog'),
  toast: $('#toast')
};

let previewObserver = null;
let lastProgressWrite = 0;

function fmtBytes(bytes){
  if (!Number.isFinite(bytes) || bytes < 0) return '';
  const units = ['B','KB','MB','GB','TB']; let n = bytes, i = 0;
  while(n >= 1024 && i < units.length - 1){ n /= 1024; i++; }
  return `${n >= 10 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
}
function fmtDate(ms){ return new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(ms)); }
function escapeHtml(s=''){ return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function saveFavorites(){ localStorage.setItem('localhub:favorites', JSON.stringify([...state.favorites])); }
function saveProgress(){ localStorage.setItem('localhub:progress', JSON.stringify(state.progress)); }
function saveRecentFolders(){ localStorage.setItem('localhub:recentFolders', JSON.stringify(state.recentFolders.slice(0,8))); }
function toast(msg){ els.toast.textContent = msg; els.toast.classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(()=>els.toast.classList.remove('show'),2200); }
function currentItem(){ return state.viewerList?.[state.currentIndex] || null; }
function isTextInput(el){ return !!el && ['INPUT','TEXTAREA','SELECT'].includes(el.tagName); }

async function apiManage(payload){
  const r = await fetch('/api/manage',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });
  let data = {};
  try { data = await r.json(); } catch {}
  if(!r.ok || data.ok===false) throw new Error(data.error || `操作失败（HTTP ${r.status}）`);
  return data;
}

async function loadMedia(rescan=false, quiet=false){
  if(!quiet) els.summary.textContent = '正在扫描媒体…';
  try{
    const r = await fetch(`/api/media${rescan?'?rescan=1':''}`, {cache:'no-store'});
    if(!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    state.items = data.items || []; state.root = data.root || ''; state.tagStats = data.tags || [];
    els.summary.textContent = `${data.count} 个媒体 · ${data.videos} 个视频 · ${data.images} 张图片 · ${state.tagStats.length} 个标签`;
    renderFolders(); renderTags(); renderFolderOptions(); applyFilters(); renderContinue();
    if(rescan && !quiet) toast(`扫描完成：${data.count} 个媒体`);
    return data;
  }catch(err){
    els.summary.textContent = '扫描失败';
    els.grid.innerHTML = `<div class="empty-state"><h3>无法读取媒体目录</h3><p>${escapeHtml(String(err))}</p></div>`;
    throw err;
  }
}

function allFolders(){
  const set = new Set();
  for(const item of state.items){
    if(!item.folder) continue;
    const parts = item.folder.split('/');
    for(let i=1;i<=parts.length;i++) set.add(parts.slice(0,i).join('/'));
  }
  return [...set].sort((a,b)=>a.localeCompare(b,'zh-CN'));
}

function renderFolders(){
  const counts = new Map();
  for(const item of state.items){
    if(!item.folder) continue;
    const parts = item.folder.split('/');
    for(let i=1;i<=parts.length;i++){
      const folder = parts.slice(0,i).join('/');
      counts.set(folder,(counts.get(folder)||0)+1);
    }
  }
  const folders = [...counts.entries()].sort((a,b)=>a[0].localeCompare(b[0],'zh-CN'));
  els.folders.innerHTML = folders.slice(0,100).map(([folder,count])=>
    `<button class="folder-btn ${state.activeFolder===folder?'active':''}" data-folder="${escapeHtml(folder)}" title="${escapeHtml(folder)}">
      <span>▸ ${escapeHtml(folder)}</span><small>${count}</small>
    </button>`
  ).join('');
  els.folders.querySelectorAll('.folder-btn').forEach(btn=>btn.addEventListener('click',()=>{
    state.activeFolder = state.activeFolder===btn.dataset.folder ? '' : btn.dataset.folder;
    state.activeFilter='all'; syncNav(); renderFolders(); applyFilters();
  }));
}

function renderTags(){
  els.clearTagFilter.classList.toggle('hidden',!state.activeTag);
  if(!state.tagStats.length){
    els.tags.innerHTML = '<div class="privacy-note" style="margin:0;padding:6px 10px">还没有标签</div>';
    return;
  }
  els.tags.innerHTML = state.tagStats.slice(0,40).map(tag=>
    `<button class="tag-btn ${state.activeTag===tag.name?'active':''}" data-tag="${escapeHtml(tag.name)}" title="${escapeHtml(tag.name)}">
      <span class="tag-left"><i class="tag-dot"></i><span class="tag-name">${escapeHtml(tag.name)}</span></span><small>${tag.count}</small>
    </button>`
  ).join('');
  els.tags.querySelectorAll('.tag-btn').forEach(btn=>btn.addEventListener('click',()=>{
    state.activeTag = state.activeTag===btn.dataset.tag ? '' : btn.dataset.tag;
    renderTags(); applyFilters();
  }));
}

function renderFolderOptions(){
  els.folderOptions.innerHTML = allFolders().map(folder=>`<option value="${escapeHtml(folder)}"></option>`).join('');
  renderRecentFolders();
}

function renderRecentFolders(){
  els.recentFolders.innerHTML = state.recentFolders.slice(0,4).map(folder=>
    `<button class="folder-chip" data-folder-shortcut="${escapeHtml(folder)}">${escapeHtml(folder)}</button>`
  ).join('');
  $$('.folder-chip[data-folder-shortcut]').forEach(btn=>btn.onclick=()=>{ els.moveFolderInput.value=btn.dataset.folderShortcut; });
}

function rememberFolder(folder){
  const clean = String(folder||'').replace(/\\/g,'/').replace(/^\/+|\/+$/g,'');
  if(!clean) return;
  state.recentFolders = [clean,...state.recentFolders.filter(x=>x!==clean)].slice(0,8);
  saveRecentFolders(); renderRecentFolders();
}

function syncNav(){ $$('.nav-item').forEach(b=>b.classList.toggle('active', b.dataset.filter===state.activeFilter)); }

function renderActiveFilter(){
  const parts = [];
  if(state.activeTag) parts.push(`标签：${state.activeTag}`);
  if(state.activeFolder) parts.push(`文件夹：${state.activeFolder}`);
  if(state.search.trim()) parts.push(`搜索：${state.search.trim()}`);
  els.activeFilterBar.classList.toggle('hidden',parts.length===0);
  els.activeFilterBar.innerHTML = parts.length ? `<span>${parts.map(escapeHtml).join('　·　')}</span><button id="clearFiltersInline">清除筛选</button>` : '';
  $('#clearFiltersInline')?.addEventListener('click',()=>{
    state.activeTag=''; state.activeFolder=''; state.search=''; els.search.value='';
    renderTags(); renderFolders(); applyFilters();
  });
}

function applyFilters(){
  let arr = state.items.slice();
  if(state.activeFolder) arr = arr.filter(i=>i.folder===state.activeFolder || i.folder.startsWith(state.activeFolder+'/'));
  if(state.activeTag) arr = arr.filter(i=>(i.tags||[]).some(tag=>tag===state.activeTag));
  if(state.activeFilter==='video' || state.activeFilter==='image') arr = arr.filter(i=>i.type===state.activeFilter);
  if(state.activeFilter==='favorite') arr = arr.filter(i=>state.favorites.has(i.id));
  if(state.activeFilter==='continue') arr = arr.filter(i=>i.type==='video' && state.progress[i.id]?.time > 5);
  const q = state.search.trim().toLocaleLowerCase();
  if(q) arr = arr.filter(i=>(`${i.name} ${i.folder} ${(i.tags||[]).join(' ')}`).toLocaleLowerCase().includes(q));
  const [field,dir] = state.sort.split('-');
  arr.sort((a,b)=>{
    let x = field==='name'?a.name.toLocaleLowerCase():a[field], y = field==='name'?b.name.toLocaleLowerCase():b[field];
    if(typeof x==='string') return dir==='asc'?x.localeCompare(y,'zh-CN'):y.localeCompare(x,'zh-CN');
    return dir==='asc'?x-y:y-x;
  });
  state.filtered = arr;
  const labels = {all:'全部媒体',video:'视频',image:'图片',favorite:'收藏',continue:'继续观看'};
  els.pageTitle.textContent = state.activeTag ? `# ${state.activeTag}` : (state.activeFolder || labels[state.activeFilter]);
  els.gridTitle.textContent = state.search ? `“${state.search}” 的结果` : (state.activeFolder?'当前文件夹':'媒体');
  renderActiveFilter(); renderGrid(); updateBatchBar();
}

function mediaCard(item, index){
  const p = state.progress[item.id];
  const pct = p?.duration ? Math.max(0,Math.min(100,p.time/p.duration*100)) : 0;
  const media = item.type==='image'
    ? `<img loading="lazy" src="${item.url}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'thumb-placeholder',textContent:'▣'}))">`
    : `<video class="lazy-preview" muted playsinline preload="none" data-src="${item.url}#t=0.15"></video>`;
  const tags = (item.tags||[]).slice(0,2).map(tag=>`<button class="card-tag" data-card-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`).join('');
  const selected = state.selected.has(item.id);
  return `<article class="media-card ${state.organizeMode?'organize-card':''} ${selected?'selected':''}" data-index="${index}" data-id="${escapeHtml(item.id)}">
    <div class="thumb-wrap">${media}
      ${item.type==='video'?'<div class="play-overlay"></div>':''}
      ${state.organizeMode
        ? `<button class="select-mark ${selected?'on':''}" data-select="${escapeHtml(item.id)}" aria-label="选择">${selected?'✓':''}</button>`
        : `<span class="badge type-badge">${item.type==='video'?'视频':'图片'}</span>`}
      <span class="badge">${item.ext.toUpperCase()}</span>
      ${!state.organizeMode?`<button class="manage-mark" data-manage="${escapeHtml(item.id)}" aria-label="整理">⋯</button><button class="favorite-mark ${state.favorites.has(item.id)?'on':''}" data-favorite="${escapeHtml(item.id)}" aria-label="收藏">★</button>`:''}
      ${pct>0?`<div class="progress-line"><span style="width:${pct}%"></span></div>`:''}
    </div>
    <div class="card-title" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
    <div class="card-meta"><span>${fmtBytes(item.size)}</span><span class="folder">${escapeHtml(item.folder||'根目录')}</span></div>
    ${tags?`<div class="card-tags">${tags}</div>`:''}
  </article>`;
}

function ensurePreviewObserver(){
  if(previewObserver) return;
  previewObserver = new IntersectionObserver(entries=>{
    for(const entry of entries){
      if(!entry.isIntersecting) continue;
      const video = entry.target;
      if(!video.src && video.dataset.src){ video.src=video.dataset.src; video.load(); }
      previewObserver.unobserve(video);
    }
  },{rootMargin:'220px 0px'});
}
function activateLazyPreviews(container){
  ensurePreviewObserver();
  container.querySelectorAll('.lazy-preview').forEach(v=>previewObserver.observe(v));
}

function bindCards(container, source){
  container.querySelectorAll('.media-card').forEach(card=>{
    card.addEventListener('click',e=>{
      if(e.target.closest('[data-favorite],[data-manage],[data-select],[data-card-tag]')) return;
      const idx = Number(card.dataset.index);
      if(state.organizeMode){ toggleSelected(source[idx].id); return; }
      openViewer(source[idx],source,{manage:false,autoplay:true});
    });
  });
  container.querySelectorAll('[data-favorite]').forEach(btn=>btn.addEventListener('click',e=>{
    e.stopPropagation(); toggleFavorite(btn.dataset.favorite); applyFilters(); renderContinue();
  }));
  container.querySelectorAll('[data-manage]').forEach(btn=>btn.addEventListener('click',e=>{
    e.stopPropagation(); const item=source.find(i=>i.id===btn.dataset.manage); if(item) openViewer(item,source,{manage:true,autoplay:false});
  }));
  container.querySelectorAll('[data-select]').forEach(btn=>btn.addEventListener('click',e=>{
    e.stopPropagation(); toggleSelected(btn.dataset.select);
  }));
  container.querySelectorAll('[data-card-tag]').forEach(btn=>btn.addEventListener('click',e=>{
    e.stopPropagation(); state.activeTag=btn.dataset.cardTag; renderTags(); applyFilters(); window.scrollTo({top:0,behavior:'smooth'});
  }));
  activateLazyPreviews(container);
}

function renderGrid(){
  els.grid.classList.toggle('compact-grid', state.compact);
  els.grid.innerHTML = state.filtered.map((item,i)=>mediaCard(item,i)).join('');
  els.resultCount.textContent = `${state.filtered.length} 项`;
  els.empty.classList.toggle('hidden', state.filtered.length!==0);
  bindCards(els.grid,state.filtered);
}

function continueItems(){
  return state.items.filter(i=>i.type==='video' && state.progress[i.id]?.time>5 && state.progress[i.id]?.duration && state.progress[i.id].time < state.progress[i.id].duration-4)
    .sort((a,b)=>(state.progress[b.id]?.updated||0)-(state.progress[a.id]?.updated||0)).slice(0,12);
}
function renderContinue(){
  const arr = continueItems();
  els.continueSection.classList.toggle('hidden', state.organizeMode || arr.length===0 || state.activeFilter==='continue');
  els.continueCount.textContent = `${arr.length} 个`;
  els.continueRail.innerHTML = arr.map((i,n)=>mediaCard(i,n)).join('');
  bindCards(els.continueRail,arr);
}

function toggleFavorite(id){
  if(state.favorites.has(id)){state.favorites.delete(id);toast('已取消收藏');}else{state.favorites.add(id);toast('已加入收藏');}
  saveFavorites(); updateViewerFavorite();
}
function updateViewerFavorite(){
  const item = currentItem(); if(!item) return;
  const on = state.favorites.has(item.id); els.favorite.classList.toggle('on',on); els.favorite.textContent = on?'★ 已收藏':'☆ 收藏';
}
function renderViewerTags(item){
  els.viewerTagStrip.innerHTML=(item.tags||[]).map(tag=>`<span class="viewer-tag"># ${escapeHtml(tag)}</span>`).join('');
}

function openViewer(item, source=state.filtered, options={}){
  state.viewerList=source; state.currentIndex=Math.max(0,source.findIndex(i=>i.id===item.id)); state.viewerAutoplay=options.autoplay!==false;
  if(!els.viewer.open) els.viewer.showModal();
  document.body.classList.add('modal-open');
  setManageOpen(!!options.manage,false);
  showCurrent({autoplay:state.viewerAutoplay});
}
function showCurrent(options={}){
  const item=currentItem(); if(!item)return;
  els.video.pause(); els.video.removeAttribute('src'); els.video.load();
  els.image.removeAttribute('src'); els.video.classList.add('hidden'); els.image.classList.add('hidden');
  els.viewerTitle.textContent=item.name; els.viewerPath.textContent=item.path;
  els.viewerDetails.innerHTML=`<span>${item.type==='video'?'视频':'图片'}</span><span>${item.ext.toUpperCase()}</span><span>${fmtBytes(item.size)}</span><span>${fmtDate(item.modified)}</span>`;
  renderViewerTags(item);
  if(item.type==='video'){
    els.video.src=item.url; els.video.classList.remove('hidden');
    const stored=state.progress[item.id];
    const resumeTime=Number.isFinite(options.resumeTime)?options.resumeTime:stored?.time;
    els.video.addEventListener('loadedmetadata',function restore(){
      els.video.removeEventListener('loadedmetadata',restore);
      if(resumeTime>3 && resumeTime<els.video.duration-3) els.video.currentTime=resumeTime;
      if(options.autoplay!==false) els.video.play().catch(()=>{});
    });
  }else{els.image.src=item.url;els.image.alt=item.name;els.image.classList.remove('hidden');}
  updateViewerFavorite(); renderManagePanel();
}
function stepViewer(delta){
  const list=state.viewerList||[];if(!list.length)return;
  persistProgress(true);state.currentIndex=(state.currentIndex+delta+list.length)%list.length;showCurrent({autoplay:true});
}
function persistProgress(force=false){
  const item=currentItem();
  if(!item || item.type!=='video' || !Number.isFinite(els.video.duration))return;
  const now=Date.now();if(!force && now-lastProgressWrite<3000)return;lastProgressWrite=now;
  state.progress[item.id]={time:els.video.currentTime,duration:els.video.duration,updated:now};saveProgress();
}
function closeViewer(){
  persistProgress(true);els.video.pause();setManageOpen(false,false);els.viewer.close();document.body.classList.remove('modal-open');applyFilters();renderContinue();
}

function setManageOpen(open, focus=true){
  els.viewer.classList.toggle('manage-open',open);els.manage.classList.toggle('on',open);
  if(open){renderManagePanel();if(focus)setTimeout(()=>els.tagInput.focus(),120);}
}
function renderManagePanel(){
  const item=currentItem();if(!item)return;
  state.manageDraftTags=[...(item.tags||[])];
  renderManageDraftTags();
  els.renameInput.value=item.stem || item.name.replace(/\.[^.]+$/,'');
  els.renameExt.textContent='.'+item.ext;
  els.moveFolderInput.value=item.folder||'';
  renderTagSuggestions();
}
function renderManageDraftTags(){
  els.manageTags.innerHTML=state.manageDraftTags.length
    ? state.manageDraftTags.map((tag,i)=>`<span class="editable-tag">${escapeHtml(tag)}<button data-remove-tag="${i}" aria-label="删除标签">×</button></span>`).join('')
    : '<span class="manage-hint" style="margin:0">暂无标签</span>';
  els.manageTags.querySelectorAll('[data-remove-tag]').forEach(btn=>btn.onclick=()=>{state.manageDraftTags.splice(Number(btn.dataset.removeTag),1);renderManageDraftTags();renderTagSuggestions();});
}
function renderTagSuggestions(){
  const current=new Set(state.manageDraftTags.map(t=>t.toLocaleLowerCase()));
  const suggestions=state.tagStats.map(x=>x.name).filter(t=>!current.has(t.toLocaleLowerCase())).slice(0,12);
  els.tagSuggestions.innerHTML=suggestions.map(tag=>`<button class="suggestion-chip" data-suggest-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`).join('');
  els.tagSuggestions.querySelectorAll('[data-suggest-tag]').forEach(btn=>btn.onclick=()=>addManageTag(btn.dataset.suggestTag));
  els.batchTagSuggestions.innerHTML=state.tagStats.slice(0,12).map(tag=>`<button class="suggestion-chip" data-batch-suggest="${escapeHtml(tag.name)}">${escapeHtml(tag.name)}</button>`).join('');
  els.batchTagSuggestions.querySelectorAll('[data-batch-suggest]').forEach(btn=>btn.onclick=()=>{
    const current=splitTags(els.batchTagInput.value);if(!current.some(t=>t.toLocaleLowerCase()===btn.dataset.batchSuggest.toLocaleLowerCase()))current.push(btn.dataset.batchSuggest);
    els.batchTagInput.value=current.join(', ');
  });
}
function addManageTag(raw){
  const tag=String(raw||'').trim();if(!tag)return;
  if(tag.length>32){toast('单个标签最多 32 个字符');return;}
  if(!state.manageDraftTags.some(t=>t.toLocaleLowerCase()===tag.toLocaleLowerCase()))state.manageDraftTags.push(tag);
  els.tagInput.value='';renderManageDraftTags();renderTagSuggestions();
}
function splitTags(raw){
  return String(raw||'').split(/[,，]/).map(x=>x.trim()).filter(Boolean).slice(0,40);
}

async function saveCurrentTags(){
  const item=currentItem();if(!item)return;
  try{
    els.saveTags.disabled=true;
    await apiManage({action:'set_tags',paths:[item.id],tags:state.manageDraftTags,mode:'replace'});
    item.tags=[...state.manageDraftTags];
    const master=state.items.find(i=>i.id===item.id);if(master)master.tags=[...state.manageDraftTags];
    await loadMedia(false,true);
    const refreshed=state.items.find(i=>i.id===item.id);
    if(refreshed){
      const idx=state.viewerList.findIndex(i=>i.id===item.id);if(idx>=0)state.viewerList[idx]=refreshed;
      renderViewerTags(refreshed);state.manageDraftTags=[...(refreshed.tags||[])];renderManageDraftTags();renderTagSuggestions();
    }
    toast('标签已保存');
  }catch(err){toast(err.message);}finally{els.saveTags.disabled=false;}
}

function migrateClientKeys(moved){
  let favChanged=false,progressChanged=false;
  for(const entry of moved||[]){
    if(state.favorites.has(entry.old)){state.favorites.delete(entry.old);state.favorites.add(entry.new);favChanged=true;}
    if(state.progress[entry.old]){state.progress[entry.new]=state.progress[entry.old];delete state.progress[entry.old];progressChanged=true;}
    if(state.selected.has(entry.old)){state.selected.delete(entry.old);state.selected.add(entry.new);}
  }
  if(favChanged)saveFavorites();if(progressChanged)saveProgress();
}

async function mutateCurrentPath(payload, successLabel){
  const item=currentItem();if(!item)return;
  const wasPlaying=item.type==='video' && !els.video.paused;
  const resumeTime=item.type==='video' ? els.video.currentTime : 0;
  persistProgress(true);
  if(item.type==='video'){els.video.pause();els.video.removeAttribute('src');els.video.load();}
  try{
    const data=await apiManage(payload);
    migrateClientKeys(data.moved||[]);
    const moved=(data.moved||[]).find(x=>x.old===item.id);
    const newId=moved?.new || item.id;
    await loadMedia(true,true);
    const refreshed=state.items.find(i=>i.id===newId);
    if(!refreshed)throw new Error('操作成功，但重新扫描后未找到文件');
    state.viewerList=state.filtered.length?state.filtered:state.items;
    state.currentIndex=state.viewerList.findIndex(i=>i.id===newId);
    if(state.currentIndex<0){state.viewerList=state.items;state.currentIndex=state.items.findIndex(i=>i.id===newId);}
    showCurrent({autoplay:wasPlaying,resumeTime});
    setManageOpen(true,false);
    toast(successLabel);
    return refreshed;
  }catch(err){
    await loadMedia(true,true).catch(()=>{});
    const fallback=state.items.find(i=>i.id===item.id);
    if(fallback){state.viewerList=state.items;state.currentIndex=state.items.findIndex(i=>i.id===item.id);showCurrent({autoplay:wasPlaying,resumeTime});setManageOpen(true,false);}
    toast(err.message);
    return null;
  }
}

async function renameCurrent(){
  const item=currentItem();if(!item)return;
  const stem=els.renameInput.value.trim();
  if(!stem || stem===item.stem){toast(stem===item.stem?'名称没有变化':'名称不能为空');return;}
  els.rename.disabled=true;
  try{await mutateCurrentPath({action:'rename',path:item.id,stem},'已改名');}finally{els.rename.disabled=false;}
}
async function moveCurrent(){
  const item=currentItem();if(!item)return;
  const folder=els.moveFolderInput.value.trim().replace(/\\/g,'/').replace(/^\/+|\/+$/g,'');
  if(folder===item.folder){toast('已经在这个文件夹');return;}
  els.move.disabled=true;
  try{
    const result=await mutateCurrentPath({action:'move',paths:[item.id],folder,create:true},folder?`已移动到 ${folder}`:'已移动到根目录');
    if(result)rememberFolder(folder);
  }finally{els.move.disabled=false;}
}

function setOrganizeMode(on){
  state.organizeMode=on;els.organize.classList.toggle('active',on);els.organize.textContent=on?'整理中':'整理';
  if(!on)state.selected.clear();
  renderGrid();renderContinue();updateBatchBar();
}
function toggleSelected(id){state.selected.has(id)?state.selected.delete(id):state.selected.add(id);renderGrid();updateBatchBar();}
function updateBatchBar(){
  els.batchBar.classList.toggle('hidden',!state.organizeMode);
  els.selectedCount.textContent=state.selected.size;
  els.batchTag.disabled=state.selected.size===0;els.batchMove.disabled=state.selected.size===0;
}
function openBatchDialog(mode){
  if(!state.selected.size){toast('先选择要整理的媒体');return;}
  els.batchTagForm.classList.toggle('hidden',mode!=='tag');els.batchMoveForm.classList.toggle('hidden',mode!=='move');
  els.batchDialogTitle.textContent=mode==='tag'?'批量添加标签':'批量移动';
  els.batchDialogHint.textContent=`将作用于 ${state.selected.size} 个媒体`;
  if(mode==='tag'){els.batchTagInput.value='';renderTagSuggestions();}
  else els.batchMoveInput.value='';
  els.batchDialog.showModal();
  setTimeout(()=>mode==='tag'?els.batchTagInput.focus():els.batchMoveInput.focus(),80);
}
async function applyBatchTags(){
  const tags=splitTags(els.batchTagInput.value);if(!tags.length){toast('请输入至少一个标签');return;}
  els.applyBatchTag.disabled=true;
  try{
    await apiManage({action:'set_tags',paths:[...state.selected],tags,mode:'add'});
    await loadMedia(false,true);els.batchDialog.close();toast(`已为 ${state.selected.size} 项添加标签`);setOrganizeMode(false);
  }catch(err){toast(err.message);}finally{els.applyBatchTag.disabled=false;}
}
async function applyBatchMove(){
  const folder=els.batchMoveInput.value.trim().replace(/\\/g,'/').replace(/^\/+|\/+$/g,'');
  els.applyBatchMove.disabled=true;
  try{
    const data=await apiManage({action:'move',paths:[...state.selected],folder,create:true});
    migrateClientKeys(data.moved||[]);rememberFolder(folder);await loadMedia(true,true);els.batchDialog.close();
    toast(`已移动 ${data.moved?.length||0} 个媒体`);setOrganizeMode(false);
  }catch(err){toast(err.message);}finally{els.applyBatchMove.disabled=false;}
}

$$('.nav-item').forEach(btn=>btn.addEventListener('click',()=>{state.activeFilter=btn.dataset.filter;state.activeFolder='';syncNav();renderFolders();applyFilters();}));
els.clearTagFilter.addEventListener('click',()=>{state.activeTag='';renderTags();applyFilters();});
els.search.addEventListener('input',()=>{state.search=els.search.value;applyFilters();});
els.clearSearch.addEventListener('click',()=>{els.search.value='';state.search='';applyFilters();els.search.focus();});
els.sort.addEventListener('change',()=>{state.sort=els.sort.value;applyFilters();});
els.density.addEventListener('click',()=>{state.compact=!state.compact;els.density.textContent=state.compact?'宽松':'紧凑';renderGrid();});
els.settings.addEventListener('click',()=>els.density.click());
els.rescan.addEventListener('click',()=>loadMedia(true));
els.organize.addEventListener('click',()=>setOrganizeMode(!state.organizeMode));

els.close.addEventListener('click',closeViewer);els.prev.addEventListener('click',()=>stepViewer(-1));els.next.addEventListener('click',()=>stepViewer(1));
els.favorite.addEventListener('click',()=>{const i=currentItem();if(i)toggleFavorite(i.id);});
els.manage.addEventListener('click',()=>setManageOpen(!els.viewer.classList.contains('manage-open')));
els.closeManage.addEventListener('click',()=>setManageOpen(false,false));
els.viewer.addEventListener('cancel',e=>{e.preventDefault();closeViewer();});
els.viewer.addEventListener('click',e=>{if(e.target===els.viewer)closeViewer();});
els.video.addEventListener('timeupdate',()=>persistProgress(false));
els.video.addEventListener('ended',()=>{persistProgress(true);setTimeout(()=>stepViewer(1),300);});
window.addEventListener('beforeunload',()=>persistProgress(true));

els.addTag.addEventListener('click',()=>addManageTag(els.tagInput.value));
els.tagInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();addManageTag(els.tagInput.value);}});
els.saveTags.addEventListener('click',saveCurrentTags);
els.rename.addEventListener('click',renameCurrent);
els.renameInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();renameCurrent();}});
els.move.addEventListener('click',moveCurrent);
els.moveFolderInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();moveCurrent();}});

els.selectAll.addEventListener('click',()=>{state.filtered.forEach(i=>state.selected.add(i.id));renderGrid();updateBatchBar();});
els.exitOrganize.addEventListener('click',()=>setOrganizeMode(false));
els.batchTag.addEventListener('click',()=>openBatchDialog('tag'));
els.batchMove.addEventListener('click',()=>openBatchDialog('move'));
els.closeBatchDialog.addEventListener('click',()=>els.batchDialog.close());
els.applyBatchTag.addEventListener('click',applyBatchTags);
els.applyBatchMove.addEventListener('click',applyBatchMove);

document.addEventListener('keydown',e=>{
  if(els.batchDialog.open)return;
  if(!els.viewer.open){
    if(e.key==='/' && document.activeElement!==els.search){e.preventDefault();els.search.focus();}
    return;
  }
  if(isTextInput(document.activeElement))return;
  if(e.key.toLocaleLowerCase()==='e'){e.preventDefault();setManageOpen(!els.viewer.classList.contains('manage-open'));}
  if(e.key==='ArrowLeft'){e.preventDefault();stepViewer(-1);}
  if(e.key==='ArrowRight'){e.preventDefault();stepViewer(1);}
  if(e.key==='Escape'){e.preventDefault();closeViewer();}
});

loadMedia();
