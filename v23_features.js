(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const bytes = (n = 0) => { const u=['B','KB','MB','GB','TB']; let x=Number(n)||0,i=0; while(x>=1024&&i<u.length-1){x/=1024;i++;} return `${x>=10||i===0?x.toFixed(0):x.toFixed(1)} ${u[i]}`; };

  const ARROW_LEFT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.82843 10.9999H20V12.9999H7.82843L13.1924 18.3638L11.7782 19.778L4 11.9999L11.7782 4.22168L13.1924 5.63589L7.82843 10.9999Z"/></svg>';
  const REFRESH = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.46257 4.43262C7.21556 2.91688 9.5007 2 12 2C17.5228 2 22 6.47715 22 12C22 14.1361 21.3302 16.1158 20.1892 17.7406L17 12H20C20 7.58172 16.4183 4 12 4C9.84982 4 7.89777 4.84827 6.46023 6.22842L5.46257 4.43262ZM18.5374 19.5674C16.7844 21.0831 14.4993 22 12 22C6.47715 22 2 17.5228 2 12C2 9.86386 2.66979 7.88416 3.8108 6.25944L7 12H4C4 16.4183 7.58172 20 12 20C14.1502 20 16.1022 19.1517 17.5398 17.7716L18.5374 19.5674Z"/></svg>';

  let currentFolder = '';
  let suppressClickUntil = 0;
  let drag = null;
  let recommendationToken = 0;
  let recObserver = null;
  const recObjectUrls = new Set();

  async function api(url, opt = {}) {
    const r = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await r.json(); } catch {}
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  function toast(message) {
    const node = $('#toast');
    if (!node) return;
    node.textContent = message;
    node.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => node.classList.remove('show'), 1800);
  }

  function installBranding() {
    const appName = 'LocalHub';
    let meta = document.querySelector('meta[name="application-name"]');
    if (!meta) { meta = document.createElement('meta'); meta.name = 'application-name'; document.head.appendChild(meta); }
    meta.content = appName;
    if (!document.querySelector('link[data-localhub-favicon]')) {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#ff9800"/><rect x="8" y="8" width="48" height="48" rx="11" fill="#111113"/><path d="M27 20v24l20-12z" fill="#ff9800"/></svg>`;
      const icon = document.createElement('link');
      icon.rel = 'icon'; icon.type = 'image/svg+xml'; icon.dataset.localhubFavicon = '1'; icon.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
      document.head.appendChild(icon);
    }
    const updateTitle = () => {
      const viewer = $('#viewer');
      const viewerTitle = ($('#viewerTitle')?.textContent || '').trim();
      const pageTitle = ($('#pageTitle')?.textContent || '').trim();
      if (viewer?.open && viewerTitle) document.title = `${viewerTitle} · LocalHub`;
      else if (pageTitle && pageTitle !== '首页') document.title = `${pageTitle} · LocalHub`;
      else document.title = 'LocalHub · 本地媒体库';
    };
    const observer = new MutationObserver(updateTitle);
    const page = $('#pageTitle'), viewerTitle = $('#viewerTitle'), viewer = $('#viewer');
    if (page) observer.observe(page,{subtree:true,childList:true,characterData:true});
    if (viewerTitle) observer.observe(viewerTitle,{subtree:true,childList:true,characterData:true});
    if (viewer) observer.observe(viewer,{attributes:true,attributeFilter:['open']});
    updateTitle();
  }

  function installHeadingControls() {
    const headingLeft = document.querySelector('.heading > div:first-child');
    const title = $('#pageTitle');
    if (!headingLeft || !title) return;
    headingLeft.classList.add('v23-heading-left');
    if (!$('#folderBackBtn')) {
      const back = document.createElement('button');
      back.id = 'folderBackBtn'; back.className = 'v23-icon-btn v23-back hidden'; back.type = 'button';
      back.innerHTML = ARROW_LEFT; back.title = '返回上级文件夹'; back.setAttribute('aria-label','返回上级文件夹');
      headingLeft.insertBefore(back,title);
      back.addEventListener('click', () => {
        const folder = resolveCurrentFolder();
        if (!folder) {
          $('#brandBtn')?.click();
          setTimeout(updateBackButton, 60);
          return;
        }
        const parts = folder.replace(/\\/g,'/').split('/').filter(Boolean); parts.pop();
        navigateFolder(parts.join('/'));
      });
    }
    const rescan = $('#rescanBtn');
    if (rescan) {
      rescan.classList.add('v23-icon-btn','v23-rescan');
      rescan.title = '重新扫描媒体库'; rescan.setAttribute('aria-label','重新扫描媒体库');
      const repaint = () => {
        if (rescan.disabled) { rescan.innerHTML = REFRESH; rescan.classList.add('busy'); }
        else { rescan.innerHTML = REFRESH; rescan.classList.remove('busy'); }
      };
      new MutationObserver(repaint).observe(rescan,{childList:true,characterData:true,attributes:true,attributeFilter:['disabled']});
      repaint();
    }
    updateBackButton();
  }

  function resolveCurrentFolder() {
    const title = ($('#pageTitle')?.textContent || '').trim();
    const activeFolder = $('.folder-nav button.active');
    const mainActive = $('.main-nav button.active');
    const rootPages = new Set(['首页','全部视频','新视频','图包 / 图册','Tag / 分类','标签分类','收藏','继续观看','AI 分析','设置','根目录']);
    // A root-level page wins over stale folder-nav selection. AI/Tag/etc. may
    // be opened while a folder remains highlighted in the sidebar, but their
    // Back action must still return Home rather than climb that old folder.
    if (mainActive || rootPages.has(title) || title.startsWith('搜索：')) currentFolder = '';
    else if (activeFolder?.dataset.folder != null) currentFolder = activeFolder.dataset.folder;
    else if (title) currentFolder = title;
    return currentFolder;
  }

  function updateBackButton() {
    const back = $('#folderBackBtn'); if (!back) return;
    const title = ($('#pageTitle')?.textContent || '').trim();
    const folder = resolveCurrentFolder();
    const show = !!title && title !== '首页';
    back.classList.toggle('hidden', !show);
    back.title = folder ? '返回上级文件夹' : '返回首页';
    back.setAttribute('aria-label', back.title);
  }

  function navigateFolder(folder) {
    currentFolder = folder || '';
    if (!folder) {
      $('#brandBtn')?.click();
      setTimeout(updateBackButton,60);
      return true;
    }
    const buttons = $$('.folder-nav button');
    const direct = buttons.find(node => node.dataset.folder === folder);
    if (direct) { direct.click(); setTimeout(updateBackButton,60); return true; }
    // renderFolders binds each button to () => openFolder(button.dataset.folder).
    // Reuse that existing closure as a safe navigation proxy for a folder that
    // is deeper than the sidebar display limit, then restore the button data.
    const proxy = buttons.find(node => typeof node.onclick === 'function');
    if (proxy) {
      const old = proxy.dataset.folder;
      proxy.dataset.folder = folder;
      try { proxy.onclick(); }
      finally { proxy.dataset.folder = old; }
      setTimeout(updateBackButton,60);
      return true;
    }
    toast('暂时无法返回这个目录');
    return false;
  }

  function destinationFromPoint(x,y) {
    const node = document.elementFromPoint(x,y)?.closest?.('.folder-nav button,.main-nav button[data-route="root"]');
    if (!node) return null;
    if (node.matches('.main-nav button[data-route="root"]')) return {node,folder:''};
    return {node,folder:node.dataset.folder ?? null};
  }

  function sourceFolder(path) {
    const parts = String(path||'').replace(/\\/g,'/').split('/'); parts.pop(); return parts.join('/');
  }

  function migrateLocalState(oldId,newId) {
    if (!oldId || !newId || oldId === newId) return;
    try {
      const fav = JSON.parse(localStorage.getItem('localhub:favorites') || '[]');
      localStorage.setItem('localhub:favorites',JSON.stringify([...new Set(fav.map(id=>id===oldId?newId:id))]));
      const progress = JSON.parse(localStorage.getItem('localhub:progress') || '{}');
      if (progress[oldId]) { progress[newId]=progress[oldId]; delete progress[oldId]; localStorage.setItem('localhub:progress',JSON.stringify(progress)); }
    } catch {}
  }

  function clearDragVisuals() {
    drag?.card?.classList.remove('v23-dragging');
    drag?.ghost?.remove();
    $$('.v23-drop-hover').forEach(n=>n.classList.remove('v23-drop-hover'));
    document.body.classList.remove('v23-is-dragging');
  }

  async function finishMove(path,folder) {
    if (sourceFolder(path) === folder) { toast('已经在这个分类里'); return; }
    try {
      const data = await api('/api/manage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'move',paths:[path],folder,create:false})});
      const moved = data.moved?.[0]; if (!moved) throw new Error('移动失败');
      migrateLocalState(path,moved.new);
      toast(`已移动到 ${folder || '根目录'}`);
      await api('/api/smart/rescan');
      const title = ($('#pageTitle')?.textContent || '').trim();
      if (title === '首页') $('#brandBtn')?.click();
      else if (currentFolder || title === '根目录') navigateFolder(currentFolder);
      else $('.main-nav button.active')?.click();
    } catch (e) { toast(e.message || '移动失败'); }
  }

  function armDrag(card,e) {
    if (!card?.querySelector('.video-thumb') || e.button > 0 || e.target.closest('button,input,select,a')) return;
    const path = card.dataset.id; if (!path) return;
    const startX=e.clientX,startY=e.clientY,pointerId=e.pointerId;
    const delay = e.pointerType === 'touch' ? 360 : 220;
    const state = {card,path,startX,startY,pointerId,active:false,target:null,ghost:null,timer:null};
    state.timer=setTimeout(()=>{
      if (drag !== state) return;
      state.active=true; suppressClickUntil=Date.now()+700;
      document.body.classList.add('v23-is-dragging'); card.classList.add('v23-dragging');
      card.dispatchEvent(new Event('mouseleave'));
      const ghost=document.createElement('div'); ghost.className='v23-drag-ghost'; ghost.textContent=card.querySelector('.card-title')?.textContent||'视频'; document.body.appendChild(ghost); state.ghost=ghost;
      try { card.setPointerCapture(pointerId); } catch {}
      moveDragGhost(state,e.clientX,e.clientY);
    },delay);
    drag=state;
  }

  function moveDragGhost(state,x,y) {
    if (state.ghost) { state.ghost.style.transform=`translate3d(${x+14}px,${y+14}px,0)`; }
    $$('.v23-drop-hover').forEach(n=>n.classList.remove('v23-drop-hover'));
    const target=destinationFromPoint(x,y); state.target=target;
    target?.node?.classList.add('v23-drop-hover');
  }

  document.addEventListener('pointerdown',e=>{
    const card=e.target.closest?.('.card[data-id]'); if(card) armDrag(card,e);
  },true);
  document.addEventListener('pointermove',e=>{
    if(!drag||e.pointerId!==drag.pointerId)return;
    if(!drag.active){if(Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)>8){clearTimeout(drag.timer);drag=null;}return;}
    e.preventDefault();moveDragGhost(drag,e.clientX,e.clientY);
  },true);
  document.addEventListener('pointerup',e=>{
    if(!drag||e.pointerId!==drag.pointerId)return;
    clearTimeout(drag.timer);const done=drag;drag=null;
    if(!done.active)return;
    e.preventDefault();e.stopImmediatePropagation();suppressClickUntil=Date.now()+700;
    clearDragVisuals();
    if(done.target?.folder!=null)finishMove(done.path,done.target.folder);
  },true);
  document.addEventListener('pointercancel',()=>{if(drag)clearTimeout(drag.timer);clearDragVisuals();drag=null;},true);
  document.addEventListener('click',e=>{if(Date.now()<suppressClickUntil){e.preventDefault();e.stopImmediatePropagation();}},true);

  function installRecommendationUI() {
    const viewer = $('#viewer'), info = $('.viewer-info');
    if (!viewer || !info || $('#recommendations')) return;
    viewer.classList.add('v23-viewer');
    const section=document.createElement('section'); section.id='recommendations'; section.className='v23-recommendations';
    section.innerHTML='<div class="v23-rec-head"><h3>推荐视频</h3><span>本地推荐 · 不读取视频内容</span></div><div id="recommendGrid" class="v23-rec-grid"><div class="v23-rec-loading">正在挑选一些不重复的内容…</div></div>';
    info.insertAdjacentElement('afterend',section);
  }

  function historyRows() {
    try {
      const progress=JSON.parse(localStorage.getItem('localhub:progress')||'{}');
      return Object.entries(progress).map(([id,row])=>({id,at:Number(row?.at)||0})).filter(x=>x.at).sort((a,b)=>b.at-a.at).slice(0,240);
    } catch { return []; }
  }
  function exposureRows() {
    try {
      const rows=JSON.parse(localStorage.getItem('localhub:recommend-exposure')||'{}');
      return Object.entries(rows).map(([id,row])=>({id,at:Number(row?.at)||0,count:Number(row?.count)||0})).filter(x=>x.at).sort((a,b)=>b.at-a.at).slice(0,360);
    } catch { return []; }
  }
  function noteExposure(items) {
    try {
      const rows=JSON.parse(localStorage.getItem('localhub:recommend-exposure')||'{}'),now=Date.now();
      for(const item of items){const old=rows[item.id]||{};rows[item.id]={at:now,count:(Number(old.count)||0)+1};}
      const compact=Object.entries(rows).sort((a,b)=>(Number(b[1]?.at)||0)-(Number(a[1]?.at)||0)).slice(0,500);
      localStorage.setItem('localhub:recommend-exposure',JSON.stringify(Object.fromEntries(compact)));
    } catch {}
  }

  function clearRecThumbs() {
    recObserver?.disconnect(); recObserver=null;
    for(const url of recObjectUrls)URL.revokeObjectURL(url); recObjectUrls.clear();
  }
  function observeRecThumbs() {
    clearRecThumbs();
    recObserver=new IntersectionObserver(entries=>{
      for(const entry of entries){if(!entry.isIntersecting)continue;recObserver.unobserve(entry.target);loadRecThumb(entry.target);}
    },{root:$('#viewer'),rootMargin:'260px 0px'});
    $$('#recommendGrid img[data-rec-thumb]').forEach(img=>recObserver.observe(img));
  }
  async function loadRecThumb(img) {
    if(!img?.isConnected)return;
    try{const r=await fetch(img.dataset.recThumb,{cache:'no-store'});if(!r.ok)return;const blob=await r.blob();if(!img.isConnected)return;const url=URL.createObjectURL(blob);recObjectUrls.add(url);img.src=url;await img.decode().catch(()=>{});img.classList.add('loaded');img.closest('.v23-rec-thumb')?.classList.add('ready');}catch{}
  }

  function recCard(item) {
    const tags=(item.tags||[]).slice(0,2).map(t=>`<span>#${esc(t)}</span>`).join('');
    const rating=Number(item.rating)||0;
    return `<article class="v23-rec-card" data-rec-id="${esc(item.id)}"><div class="v23-rec-thumb"><div class="v23-rec-placeholder"></div><img data-rec-thumb="${esc(item.thumb)}" alt="" decoding="async"><span class="v23-rec-ext">${esc(String(item.ext||'').toUpperCase())}</span></div><div class="v23-rec-title" title="${esc(item.name)}">${esc(item.name)}</div><div class="v23-rec-meta"><span>${bytes(item.size)}</span>${rating?`<span>★ ${rating}</span>`:''}</div>${tags?`<div class="v23-rec-tags">${tags}</div>`:''}</article>`;
  }

  function snapshotView() {
    return {folder:$('.folder-nav button.active')?.dataset.folder??null,route:$('.main-nav button.active')?.dataset.route||'',query:($('#searchInput')?.value||'').trim()};
  }
  async function restoreBackground(view) {
    if(view.folder!=null){navigateFolder(view.folder);return;}
    if(view.query){const input=$('#searchInput');if(input){input.value=view.query;input.dispatchEvent(new Event('input',{bubbles:true}));}return;}
    if(view.route)$(`.main-nav button[data-route="${CSS.escape(view.route)}"]`)?.click();
  }
  async function openRecommended(item) {
    const view=snapshotView();
    $('#closeViewer')?.click();
    await sleep(50);
    const input=$('#searchInput'); if(!input)return;
    input.value=item.id; input.dispatchEvent(new Event('input',{bubbles:true}));
    const deadline=Date.now()+4200;
    while(Date.now()<deadline){const card=$$('.card[data-id]').find(n=>n.dataset.id===item.id);if(card){card.click();await sleep(180);restoreBackground(view);return;}await sleep(90);}
    toast('暂时无法打开推荐视频');
  }

  async function loadRecommendations(path) {
    const grid=$('#recommendGrid'); if(!grid||!path)return;
    const token=++recommendationToken; clearRecThumbs();
    grid.innerHTML='<div class="v23-rec-loading">正在挑选一些不重复的内容…</div>';
    try{
      const data=await api('/api/recommend',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,limit:10,history:historyRows(),exposure:exposureRows()})});
      if(token!==recommendationToken||!$('#viewer')?.open)return;
      const items=data.items||[];
      if(!items.length){grid.innerHTML='<div class="v23-rec-loading">媒体库里暂时没有合适的推荐。</div>';return;}
      grid.innerHTML=items.map(recCard).join('');noteExposure(items);observeRecThumbs();
      grid.querySelectorAll('.v23-rec-card').forEach(card=>{card.addEventListener('click',()=>{const item=items.find(x=>x.id===card.dataset.recId);if(item)openRecommended(item);});});
    }catch(e){if(token===recommendationToken)grid.innerHTML='<div class="v23-rec-loading">推荐暂时不可用，不影响当前播放。</div>';}
  }

  function watchViewerRecommendations() {
    const viewer=$('#viewer'),path=$('#viewerPath'); if(!viewer||!path)return;
    let last='';
    const inspect=()=>{
      if(!viewer.open){last='';clearRecThumbs();return;}
      const current=(path.textContent||'').trim();if(!current||current===last)return;last=current;
      setTimeout(()=>{if(viewer.open&&(path.textContent||'').trim()===current)loadRecommendations(current);},90);
    };
    new MutationObserver(inspect).observe(viewer,{attributes:true,attributeFilter:['open']});
    new MutationObserver(inspect).observe(path,{subtree:true,childList:true,characterData:true});
  }

  document.addEventListener('click',e=>{
    const folder=e.target.closest?.('[data-folder]'); if(folder?.dataset.folder!=null){currentFolder=folder.dataset.folder;setTimeout(updateBackButton,80);return;}
    const root=e.target.closest?.('.main-nav button[data-route="root"]'); if(root){currentFolder='';setTimeout(updateBackButton,80);return;}
    if(e.target.closest?.('.main-nav button:not([data-route="root"])')){currentFolder='';setTimeout(updateBackButton,80);}
  },true);

  installBranding(); installHeadingControls(); installRecommendationUI(); watchViewerRecommendations();
  const headingObserver=new MutationObserver(()=>updateBackButton());
  if($('#pageTitle'))headingObserver.observe($('#pageTitle'),{subtree:true,childList:true,characterData:true});
})();

// LH_RECOMMEND_NAVIGATION_FIX_V2
(() => {
  'use strict';

  const viewer = document.querySelector('#viewer');
  const pathNode = document.querySelector('#viewerPath');
  const search = document.querySelector('#searchInput');
  const closeButton = document.querySelector('#closeViewer');
  const toastNode = document.querySelector('#toast');
  if (!viewer || !pathNode || !search || !closeButton) return;

  const history = [];
  let internalNavigation = false;
  let navigatingBack = false;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function toast(message) {
    if (!toastNode || !message) return;
    toastNode.textContent = message;
    toastNode.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => toastNode.classList.remove('show'), 2100);
  }

  async function api(url) {
    const response = await fetch(url, {cache:'no-store'});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function snapshotView() {
    return {
      folder: document.querySelector('.folder-nav button.active')?.dataset.folder ?? null,
      route: document.querySelector('.main-nav button.active')?.dataset.route || '',
      query: (search.value || '').trim(),
    };
  }

  function restoreBackground(view) {
    if (!view) return;
    if (view.folder != null) {
      const direct = [...document.querySelectorAll('.folder-nav button')].find(node => node.dataset.folder === view.folder);
      direct?.click();
      return;
    }
    if (view.query) {
      search.value = view.query;
      search.dispatchEvent(new Event('input', {bubbles:true}));
      return;
    }
    if (view.route) document.querySelector(`.main-nav button[data-route="${CSS.escape(view.route)}"]`)?.click();
  }

  async function itemById(id) {
    if (!id) return null;
    const data = await api(`/api/smart/by-ids?ids=${encodeURIComponent(id)}`);
    return (data.items || []).find(item => item.id === id) || (data.items || [])[0] || null;
  }

  function updateBackButton() {
    let button = document.querySelector('#viewerHistoryBack');
    if (!button) {
      button = document.createElement('button');
      button.id = 'viewerHistoryBack';
      button.type = 'button';
      button.className = 'lh-viewer-history-back';
      button.setAttribute('aria-label', '返回上一个视频');
      button.title = '返回上一个视频';
      button.textContent = '←';
      viewer.appendChild(button);
      button.addEventListener('click', async event => {
        event.preventDefault();
        event.stopPropagation();
        const previous = history.pop();
        updateBackButton();
        if (!previous) return;
        try {
          const item = await itemById(previous);
          if (!item) throw new Error('上一个视频已不存在');
          navigatingBack = true;
          await openExactItem(item, {recordHistory:false});
        } catch (error) {
          toast(error.message || '无法返回上一个视频');
        } finally {
          navigatingBack = false;
          updateBackButton();
        }
      });
    }
    button.classList.toggle('hidden', history.length === 0);
  }

  if (!document.querySelector('#lhViewerNavigationStyle')) {
    const style = document.createElement('style');
    style.id = 'lhViewerNavigationStyle';
    style.textContent = `
      .lh-viewer-history-back{position:absolute;left:12px;top:12px;z-index:40;width:40px;height:40px;border:1px solid #35353a;border-radius:50%;background:rgba(0,0,0,.72);color:#fff;font-size:24px;line-height:1;display:grid;place-items:center;cursor:pointer;box-shadow:0 5px 18px rgba(0,0,0,.28)}
      .lh-viewer-history-back:hover{background:#202024;border-color:#55555c}
      .lh-viewer-history-back.hidden{display:none!important}
    `;
    document.head.appendChild(style);
  }
  updateBackButton();

  async function waitForExactCard(id, timeout = 4600) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const card = [...document.querySelectorAll('.card[data-id]')].find(node => node.dataset.id === id);
      if (card) return card;
      await sleep(80);
    }
    return null;
  }

  async function openExactItem(item, {recordHistory=true} = {}) {
    const targetId = String(item?.id || '');
    if (!targetId) throw new Error('推荐视频路径无效');
    const currentId = (pathNode.textContent || '').trim();
    if (recordHistory && currentId && currentId !== targetId && !navigatingBack) {
      if (history[history.length - 1] !== currentId) history.push(currentId);
      if (history.length > 40) history.splice(0, history.length - 40);
      updateBackButton();
    }

    const background = snapshotView();
    internalNavigation = true;
    closeButton.click();
    await sleep(55);

    const queries = [item.name, item.stem, String(item.name || '').replace(/\.[^.]+$/, '')]
      .map(value => String(value || '').trim())
      .filter((value, index, rows) => value && rows.indexOf(value) === index);

    let card = null;
    for (const query of queries) {
      search.value = query;
      search.dispatchEvent(new Event('input', {bubbles:true}));
      card = await waitForExactCard(targetId, 2600);
      if (card) break;
    }

    if (!card) {
      internalNavigation = false;
      restoreBackground(background);
      throw new Error('推荐视频存在，但当前列表没有定位到它');
    }

    card.click();
    const deadline = Date.now() + 2600;
    while (Date.now() < deadline) {
      if (viewer.open && (pathNode.textContent || '').trim() === targetId) break;
      await sleep(60);
    }
    viewer.scrollTop = 0;
    setTimeout(() => restoreBackground(background), 120);
    internalNavigation = false;
    updateBackButton();
  }

  document.addEventListener('click', async event => {
    const card = event.target.closest?.('.v23-rec-card[data-rec-id]');
    if (!card) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      const item = await itemById(card.dataset.recId || '');
      if (!item) throw new Error('推荐视频已不存在');
      await openExactItem(item, {recordHistory:true});
    } catch (error) {
      internalNavigation = false;
      toast(error.message || '暂时无法打开推荐视频');
    }
  }, true);

  viewer.addEventListener('close', () => {
    if (internalNavigation) return;
    history.length = 0;
    updateBackButton();
  });
})();
