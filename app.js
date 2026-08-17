const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const state = {
  items: [],
  filtered: [],
  root: '',
  activeFilter: 'all',
  activeFolder: '',
  search: '',
  sort: 'modified-desc',
  compact: false,
  currentIndex: -1,
  viewerList: [],
  favorites: new Set(JSON.parse(localStorage.getItem('localhub:favorites') || '[]')),
  progress: JSON.parse(localStorage.getItem('localhub:progress') || '{}'),
};

const els = {
  grid: $('#mediaGrid'), empty: $('#emptyState'), resultCount: $('#resultCount'), summary: $('#summaryText'),
  pageTitle: $('#pageTitle'), gridTitle: $('#gridTitle'), folders: $('#folderList'), search: $('#searchInput'),
  clearSearch: $('#clearSearch'), sort: $('#sortSelect'), density: $('#densityBtn'), rescan: $('#rescanBtn'),
  settings: $('#settingsBtn'), viewer: $('#viewer'), video: $('#videoPlayer'), image: $('#imageViewer'),
  close: $('#closeViewer'), prev: $('#prevBtn'), next: $('#nextBtn'), viewerTitle: $('#viewerTitle'),
  viewerPath: $('#viewerPath'), viewerDetails: $('#viewerDetails'), favorite: $('#favoriteBtn'),
  continueSection: $('#continueSection'), continueRail: $('#continueRail'), continueCount: $('#continueCount'), toast: $('#toast')
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
function toast(msg){ els.toast.textContent = msg; els.toast.classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(()=>els.toast.classList.remove('show'),1700); }

async function loadMedia(rescan=false){
  els.summary.textContent = '正在扫描媒体…';
  try{
    const r = await fetch(`/api/media${rescan?'?rescan=1':''}`, {cache:'no-store'});
    if(!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    state.items = data.items || []; state.root = data.root || '';
    els.summary.textContent = `${data.count} 个媒体 · ${data.videos} 个视频 · ${data.images} 张图片`;
    renderFolders(); applyFilters(); renderContinue();
    if(rescan) toast(`扫描完成：${data.count} 个媒体`);
  }catch(err){
    els.summary.textContent = '扫描失败';
    els.grid.innerHTML = `<div class="empty-state"><h3>无法读取媒体目录</h3><p>${escapeHtml(String(err))}</p></div>`;
  }
}

function renderFolders(){
  const counts = new Map();
  for(const item of state.items){
    const folder = item.folder || '';
    if(folder) counts.set(folder, (counts.get(folder)||0)+1);
  }
  const folders = [...counts.entries()].sort((a,b)=>a[0].localeCompare(b[0],'zh-CN'));
  els.folders.innerHTML = folders.slice(0,80).map(([folder,count])=>
    `<button class="folder-btn ${state.activeFolder===folder?'active':''}" data-folder="${escapeHtml(folder)}" title="${escapeHtml(folder)}">▸ ${escapeHtml(folder)} <small>(${count})</small></button>`
  ).join('');
  $$('.folder-btn').forEach(btn=>btn.addEventListener('click',()=>{
    state.activeFolder = state.activeFolder===btn.dataset.folder ? '' : btn.dataset.folder;
    state.activeFilter='all'; syncNav(); renderFolders(); applyFilters();
  }));
}

function syncNav(){ $$('.nav-item').forEach(b=>b.classList.toggle('active', b.dataset.filter===state.activeFilter)); }

function applyFilters(){
  let arr = state.items.slice();
  if(state.activeFolder) arr = arr.filter(i=>i.folder===state.activeFolder || i.folder.startsWith(state.activeFolder+'/'));
  if(state.activeFilter==='video' || state.activeFilter==='image') arr = arr.filter(i=>i.type===state.activeFilter);
  if(state.activeFilter==='favorite') arr = arr.filter(i=>state.favorites.has(i.id));
  if(state.activeFilter==='continue') arr = arr.filter(i=>i.type==='video' && state.progress[i.id]?.time > 5);
  const q = state.search.trim().toLocaleLowerCase();
  if(q) arr = arr.filter(i=>(i.name+' '+i.folder).toLocaleLowerCase().includes(q));
  const [field,dir] = state.sort.split('-');
  arr.sort((a,b)=>{
    let x = field==='name'?a.name.toLocaleLowerCase():a[field], y = field==='name'?b.name.toLocaleLowerCase():b[field];
    if(typeof x==='string') return dir==='asc'?x.localeCompare(y,'zh-CN'):y.localeCompare(x,'zh-CN');
    return dir==='asc'?x-y:y-x;
  });
  state.filtered = arr;
  const labels = {all:'全部媒体',video:'视频',image:'图片',favorite:'收藏',continue:'继续观看'};
  els.pageTitle.textContent = state.activeFolder || labels[state.activeFilter];
  els.gridTitle.textContent = state.search ? `“${state.search}” 的结果` : (state.activeFolder?'当前文件夹':'媒体');
  renderGrid();
}

function mediaCard(item, index){
  const p = state.progress[item.id];
  const pct = p?.duration ? Math.max(0,Math.min(100,p.time/p.duration*100)) : 0;
  const media = item.type==='image'
    ? `<img loading="lazy" src="${item.url}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'thumb-placeholder',textContent:'▣'}))">`
    : `<video class="lazy-preview" muted playsinline preload="none" data-src="${item.url}#t=0.15"></video>`;
  return `<article class="media-card" data-index="${index}" data-id="${escapeHtml(item.id)}">
    <div class="thumb-wrap">${media}
      ${item.type==='video'?'<div class="play-overlay"></div>':''}
      <span class="badge type-badge">${item.type==='video'?'视频':'图片'}</span>
      <span class="badge">${item.ext.toUpperCase()}</span>
      <button class="favorite-mark ${state.favorites.has(item.id)?'on':''}" data-favorite="${escapeHtml(item.id)}" aria-label="收藏">★</button>
      ${pct>0?`<div class="progress-line"><span style="width:${pct}%"></span></div>`:''}
    </div>
    <div class="card-title" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
    <div class="card-meta"><span>${fmtBytes(item.size)}</span><span class="folder">${escapeHtml(item.folder||'根目录')}</span></div>
  </article>`;
}

function activateLazyPreviews(container){
  if(previewObserver) previewObserver.disconnect();
  previewObserver = new IntersectionObserver(entries=>{
    for(const entry of entries){
      if(!entry.isIntersecting) continue;
      const video = entry.target;
      if(!video.src && video.dataset.src){
        video.src = video.dataset.src;
        video.load();
      }
      previewObserver.unobserve(video);
    }
  },{rootMargin:'220px 0px'});
  container.querySelectorAll('.lazy-preview').forEach(v=>previewObserver.observe(v));
}

function bindCards(container, source){
  container.querySelectorAll('.media-card').forEach(card=>{
    card.addEventListener('click',e=>{
      if(e.target.closest('[data-favorite]')) return;
      const idx = Number(card.dataset.index); openViewer(source[idx], source);
    });
  });
  container.querySelectorAll('[data-favorite]').forEach(btn=>btn.addEventListener('click',e=>{
    e.stopPropagation(); toggleFavorite(btn.dataset.favorite); applyFilters(); renderContinue();
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
  els.continueSection.classList.toggle('hidden', arr.length===0 || state.activeFilter==='continue');
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
function currentItem(){ return state.viewerList?.[state.currentIndex] || null; }

function openViewer(item, source=state.filtered){
  state.viewerList = source; state.currentIndex = source.findIndex(i=>i.id===item.id); showCurrent();
  if(!els.viewer.open) els.viewer.showModal();
  document.body.classList.add('modal-open');
}
function showCurrent(){
  const item = currentItem(); if(!item) return;
  els.video.pause(); els.video.removeAttribute('src'); els.video.load();
  els.image.removeAttribute('src'); els.video.classList.add('hidden'); els.image.classList.add('hidden');
  els.viewerTitle.textContent = item.name; els.viewerPath.textContent = item.path;
  els.viewerDetails.innerHTML = `<span>${item.type==='video'?'视频':'图片'}</span><span>${item.ext.toUpperCase()}</span><span>${fmtBytes(item.size)}</span><span>${fmtDate(item.modified)}</span>`;
  if(item.type==='video'){
    els.video.src = item.url; els.video.classList.remove('hidden');
    const stored = state.progress[item.id];
    els.video.addEventListener('loadedmetadata', function restore(){
      els.video.removeEventListener('loadedmetadata',restore);
      if(stored?.time > 3 && stored.time < els.video.duration-3) els.video.currentTime = stored.time;
      els.video.play().catch(()=>{});
    });
  }else{ els.image.src=item.url; els.image.alt=item.name; els.image.classList.remove('hidden'); }
  updateViewerFavorite();
}
function stepViewer(delta){
  const list = state.viewerList || []; if(!list.length)return;
  persistProgress(true); state.currentIndex=(state.currentIndex+delta+list.length)%list.length; showCurrent();
}
function persistProgress(force=false){
  const item=currentItem();
  if(!item || item.type!=='video' || !Number.isFinite(els.video.duration)) return;
  const now = Date.now();
  if(!force && now-lastProgressWrite < 3000) return;
  lastProgressWrite = now;
  state.progress[item.id]={time:els.video.currentTime,duration:els.video.duration,updated:now};
  saveProgress();
}
function closeViewer(){ persistProgress(true); els.video.pause(); els.viewer.close(); document.body.classList.remove('modal-open'); applyFilters(); renderContinue(); }

$$('.nav-item').forEach(btn=>btn.addEventListener('click',()=>{state.activeFilter=btn.dataset.filter;state.activeFolder='';syncNav();renderFolders();applyFilters();}));
els.search.addEventListener('input',()=>{state.search=els.search.value;applyFilters();});
els.clearSearch.addEventListener('click',()=>{els.search.value='';state.search='';applyFilters();els.search.focus();});
els.sort.addEventListener('change',()=>{state.sort=els.sort.value;applyFilters();});
els.density.addEventListener('click',()=>{state.compact=!state.compact;els.density.textContent=state.compact?'宽松':'紧凑';renderGrid();});
els.settings.addEventListener('click',()=>els.density.click());
els.rescan.addEventListener('click',()=>loadMedia(true));
els.close.addEventListener('click',closeViewer); els.prev.addEventListener('click',()=>stepViewer(-1)); els.next.addEventListener('click',()=>stepViewer(1));
els.favorite.addEventListener('click',()=>{const i=currentItem();if(i)toggleFavorite(i.id);});
els.viewer.addEventListener('cancel',e=>{e.preventDefault();closeViewer();});
els.viewer.addEventListener('click',e=>{if(e.target===els.viewer)closeViewer();});
els.video.addEventListener('timeupdate',()=>persistProgress(false));
els.video.addEventListener('ended',()=>{persistProgress(true);setTimeout(()=>stepViewer(1),300);});
window.addEventListener('beforeunload',()=>persistProgress(true));
document.addEventListener('keydown',e=>{
  if(!els.viewer.open){ if(e.key==='/' && document.activeElement!==els.search){e.preventDefault();els.search.focus();} return; }
  if(e.key==='ArrowLeft')stepViewer(-1); if(e.key==='ArrowRight')stepViewer(1); if(e.key==='Escape'){e.preventDefault();closeViewer();}
});

loadMedia();
