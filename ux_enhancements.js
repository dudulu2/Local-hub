(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const ratingCache = new Map();
  const metaCache = new Map();
  let renameBusy = false;
  let autoCompatBusy = false;
  let blackFrameTimer = null;

  const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const api = async (url, opt = {}) => {
    const r = await fetch(url, {cache:'no-store', ...opt});
    let data = {};
    try { data = await r.json(); } catch {}
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  };
  const manage = payload => api('/api/manage', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const currentPath = () => ($('#viewerPath')?.textContent || '').trim();
  const toast = msg => {
    const el = $('#toast'); if (!el) return;
    el.textContent = msg; el.classList.add('show');
    clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove('show'), 1800);
  };

  function ratingMarkup(path, value = 0) {
    const v = Math.max(0, Math.min(5, Number(value) || 0));
    return `<span class="rating-inline" data-rating-path="${esc(path)}" data-rating-value="${v}" title="个人评分">
      <button class="rating-summary" type="button" aria-label="评分">${v ? `★ ${v}` : '☆'}</button>
      <span class="rating-stars">${[1,2,3,4,5].map(n => `<button type="button" data-rate="${n}" aria-label="${n} 分">${n <= v ? '★' : '☆'}</button>`).join('')}</span>
    </span>`;
  }

  async function loadMeta(path) {
    if (!path) return {rating:0,tags:[]};
    if (metaCache.has(path)) return metaCache.get(path);
    try {
      const d = await api(`/api/rating?path=${encodeURIComponent(path)}`);
      const row = {rating:Number(d.rating)||0,tags:Array.isArray(d.tags)?d.tags:[]};
      metaCache.set(path,row); ratingCache.set(path,row.rating); return row;
    } catch { return {rating:0,tags:[]}; }
  }

  function ensureRemoveHandles(strip) {
    strip.querySelectorAll('.tag-chip,.viewer-tag-chip').forEach(chip => {
      if (chip.querySelector('.tag-remove-inline')) return;
      const x = document.createElement('span'); x.className = 'tag-remove-inline'; x.textContent = '×'; x.title = '删除这个标签';
      chip.appendChild(x);
    });
  }

  function ensureRating(strip, path) {
    if (!path || strip.querySelector('.rating-inline')) return;
    const holder = document.createElement('span'); holder.innerHTML = ratingMarkup(path, ratingCache.get(path) || 0);
    strip.appendChild(holder.firstElementChild);
    loadMeta(path).then(meta => updateRatingUI(path, meta.rating));
  }

  function decorateStrip(strip) {
    if (!(strip instanceof HTMLElement)) return;
    const path = strip.dataset.tagStrip || (strip.id === 'viewerTagStrip' ? currentPath() : '');
    if (!path) return;
    ensureRemoveHandles(strip);
    ensureRating(strip,path);
  }

  function decorateAll() {
    document.querySelectorAll('[data-tag-strip],#viewerTagStrip').forEach(decorateStrip);
  }

  function updateRatingUI(path, value) {
    ratingCache.set(path, value); const cached = metaCache.get(path); if (cached) cached.rating = value;
    document.querySelectorAll('.rating-inline').forEach(w => {
      if (w.dataset.ratingPath !== path) return;
      w.dataset.ratingValue = String(value);
      const summary = w.querySelector('.rating-summary'); if (summary) summary.textContent = value ? `★ ${value}` : '☆';
      w.querySelectorAll('[data-rate]').forEach(b => b.textContent = Number(b.dataset.rate) <= value ? '★' : '☆');
    });
  }

  async function setRating(path, value) {
    try {
      const d = await api('/api/rating',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,rating:value})});
      updateRatingUI(path, Number(d.rating)||0); toast(value ? `已评分 ${value}` : '已清除评分');
    } catch (e) { toast(e.message); }
  }

  function beginInlineTag(strip, path) {
    if (!strip || !path || strip.querySelector('.inline-tag-editor')) return;
    const add = strip.querySelector('.tag-edit,.viewer-tag-add');
    const input = document.createElement('input');
    input.className='inline-tag-editor'; input.placeholder='添加标签'; input.maxLength=32; input.autocomplete='off';
    add?.classList.add('editing');
    if (add) strip.insertBefore(input,add); else strip.appendChild(input);
    const finish = () => { input.remove(); add?.classList.remove('editing'); };
    input.addEventListener('keydown', async e => {
      if (e.key === 'Escape') { e.preventDefault(); finish(); return; }
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const tags = input.value.split(/[,，]/).map(v=>v.trim()).filter(Boolean);
      if (!tags.length) { finish(); return; }
      input.disabled=true;
      try {
        await manage({action:'set_tags',paths:[path],tags,mode:'add'});
        const meta = await loadMetaFresh(path);
        syncTagStrips(path,meta.tags); toast('标签已添加'); finish();
      } catch (err) { input.disabled=false; toast(err.message); }
    });
    input.addEventListener('blur',()=>setTimeout(()=>{if(document.activeElement!==input)finish();},100));
    requestAnimationFrame(()=>input.focus());
  }

  async function loadMetaFresh(path) {
    metaCache.delete(path);
    return loadMeta(path);
  }

  function tagButton(tag, viewer=false) {
    const cls = viewer ? 'viewer-tag-chip' : 'tag-chip';
    const attr = viewer ? 'data-viewer-tag' : 'data-tag';
    return `<button class="${cls}" ${attr}="${esc(tag)}" type="button">#${esc(tag)}<span class="tag-remove-inline" title="删除这个标签">×</span></button>`;
  }

  function syncTagStrips(path,tags) {
    document.querySelectorAll('[data-tag-strip]').forEach(strip => {
      if (strip.dataset.tagStrip !== path) return;
      const rating = strip.querySelector('.rating-inline'); const add = strip.querySelector('.tag-edit');
      strip.querySelectorAll('.tag-chip,.no-tags,.inline-tag-editor').forEach(n=>n.remove());
      if (tags.length) {
        const box=document.createElement('span');box.innerHTML=tags.slice(0,6).map(t=>tagButton(t,false)).join('');
        [...box.children].forEach(n=>strip.insertBefore(n,rating||add||null));
      } else {
        const empty=document.createElement('span');empty.className='no-tags';empty.textContent='暂无标签';strip.insertBefore(empty,rating||add||null);
      }
    });
    const viewer=$('#viewerTagStrip');
    if (viewer && currentPath()===path) {
      const rating=viewer.querySelector('.rating-inline'); const add=viewer.querySelector('.viewer-tag-add');
      viewer.querySelectorAll('.viewer-tag-chip,.viewer-no-tags,.inline-tag-editor').forEach(n=>n.remove());
      if(tags.length){const box=document.createElement('span');box.innerHTML=tags.map(t=>tagButton(t,true)).join('');[...box.children].forEach(n=>viewer.insertBefore(n,rating||add||null));}
      else{const empty=document.createElement('span');empty.className='viewer-no-tags';empty.textContent='暂无标签';viewer.insertBefore(empty,rating||add||null);}
    }
    const cached=metaCache.get(path);if(cached)cached.tags=[...tags];
    decorateAll();
  }

  async function removeTag(path,tag) {
    try {
      await manage({action:'set_tags',paths:[path],tags:[tag],mode:'remove'});
      const meta=await loadMetaFresh(path);syncTagStrips(path,meta.tags);toast('标签已删除');
    } catch(e){toast(e.message);}
  }

  function migrateLocalKey(oldId,newId,currentTime,duration) {
    try {
      const fav=JSON.parse(localStorage.getItem('localhub:favorites')||'[]');
      const next=fav.map(x=>x===oldId?newId:x);localStorage.setItem('localhub:favorites',JSON.stringify([...new Set(next)]));
      const progress=JSON.parse(localStorage.getItem('localhub:progress')||'{}');
      const existing=progress[oldId]||{};delete progress[oldId];
      progress[newId]={...existing,time:Number(currentTime)||existing.time||0,duration:Number(duration)||existing.duration||0,at:Date.now()};
      localStorage.setItem('localhub:progress',JSON.stringify(progress));
    } catch {}
    const meta=metaCache.get(oldId);if(meta){metaCache.delete(oldId);metaCache.set(newId,meta);}if(ratingCache.has(oldId)){const v=ratingCache.get(oldId);ratingCache.delete(oldId);ratingCache.set(newId,v);}
  }

  async function reopenRenamed(newId,wasPaused,currentTime=0) {
    try { await api('/api/smart/rescan'); } catch {}
    const input=$('#searchInput'); if(!input){location.reload();return;}
    input.value=newId.split('/').pop()||newId; input.dispatchEvent(new Event('input',{bubbles:true}));
    const deadline=Date.now()+5000;
    const timer=setInterval(()=>{
      const card=[...document.querySelectorAll('.card[data-id]')].find(n=>n.dataset.id===newId);
      if(card){
        clearInterval(timer);
        const video=$('#videoPlayer');
        if(video&&currentTime>0){
          const restore=()=>{try{if(!Number.isFinite(video.duration)||currentTime<video.duration-1)video.currentTime=currentTime;}catch{}if(wasPaused)setTimeout(()=>video.pause(),80);};
          video.addEventListener('loadedmetadata',restore,{once:true});
        }
        card.click();
        if(wasPaused&&!currentTime)setTimeout(()=>$('#videoPlayer')?.pause(),700);
      } else if(Date.now()>deadline){clearInterval(timer);location.reload();}
    },120);
  }

  function beginTitleRename() {
    if(renameBusy)return; const title=$('#viewerTitle'),path=currentPath(),video=$('#videoPlayer');
    if(!title||!path||!video)return;
    const name=title.textContent.trim(),dot=name.lastIndexOf('.'),stem=dot>0?name.slice(0,dot):name,ext=dot>0?name.slice(dot):'';
    const row=title.parentElement; if(row?.querySelector('.inline-rename'))return;
    const input=document.createElement('input');input.className='inline-rename';input.value=stem;input.maxLength=180;
    const suffix=document.createElement('span');suffix.className='inline-rename-ext';suffix.textContent=ext;
    title.classList.add('renaming');title.after(input,suffix);input.select();
    const cancel=()=>{input.remove();suffix.remove();title.classList.remove('renaming');};
    input.addEventListener('keydown',async e=>{
      if(e.key==='Escape'){e.preventDefault();cancel();return;}
      if(e.key!=='Enter')return;e.preventDefault();const nextStem=input.value.trim();if(!nextStem||nextStem===stem){cancel();return;}
      renameBusy=true;input.disabled=true;const time=video.currentTime||0,duration=Number.isFinite(video.duration)?video.duration:0,wasPaused=video.paused;
      video.pause();video.removeAttribute('src');video.load();
      try{
        const d=await manage({action:'rename',path,stem:nextStem});const moved=d.moved?.[0];if(!moved)throw new Error('改名失败');
        migrateLocalKey(path,moved.new,time,duration);cancel();toast('已改名');await reopenRenamed(moved.new,wasPaused,time);
      }catch(err){toast(err.message);input.disabled=false;}
      finally{renameBusy=false;}
    });
  }

  function requestAutoCompat(reason='') {
    const viewer=$('#viewer'),video=$('#videoPlayer'),btn=$('#compatBtn'),mode=$('#playMode');
    if(!viewer?.open||!video||!btn||btn.disabled||autoCompatBusy)return;
    if(mode?.classList.contains('compat')||/兼容/.test(mode?.textContent||''))return;
    autoCompatBusy=true;
    $('#playerNotice')?.classList.add('hidden');
    toast(reason ? `自动切换兼容播放：${reason}` : '正在自动切换兼容播放');
    btn.click();setTimeout(()=>{autoCompatBusy=false;},1800);
  }

  function watchPlayerNotice() {
    const notice=$('#playerNotice'),title=$('#playerNoticeTitle');if(!notice||!title)return;
    const inspect=()=>{
      if(notice.classList.contains('hidden'))return;const t=title.textContent||'';
      if(/无法稳定拖动|视频轨道没有正常显示|原生播放失败/.test(t)){notice.classList.add('hidden');requestAutoCompat(t);return;}
      if(/当前格式可能需要兼容播放|正在分析媒体/.test(t)){notice.classList.add('hidden');return;}
    };
    new MutationObserver(inspect).observe(notice,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});inspect();
  }

  function installBlackFrameWatch() {
    const video=$('#videoPlayer');if(!video)return;
    video.addEventListener('play',()=>{
      clearTimeout(blackFrameTimer);const start=video.currentTime||0;
      blackFrameTimer=setTimeout(()=>{
        if(!$('#viewer')?.open||video.paused)return;
        if((video.currentTime||0)>start+1.2 && (!video.videoWidth||!video.videoHeight)) requestAutoCompat('检测到黑屏');
      },2300);
    });
    video.addEventListener('error',()=>requestAutoCompat('浏览器解码失败'));
    video.addEventListener('loadeddata',()=>{if(!video.videoWidth||!video.videoHeight)setTimeout(()=>{if(video.currentTime>0&&!video.videoWidth)requestAutoCompat('视频轨未输出');},1500);});
  }

  function installProcessingStatus() {
    const notice=$('#playerNotice'),title=$('#playerNoticeTitle'),progress=$('#compatProgress'),row=$('.viewer-title-row');
    if(!notice||!title||!row)return;
    let status=$('#processingStatus');
    if(!status){
      status=document.createElement('div');status.id='processingStatus';status.className='processing-status hidden';
      status.innerHTML='<span class="processing-status-dot"></span><span class="processing-status-label"></span>';
      row.insertAdjacentElement('afterend',status);
    }
    const label=status.querySelector('.processing-status-label');
    const sync=()=>{
      if(notice.classList.contains('hidden')){status.classList.add('hidden');status.classList.remove('error');return;}
      const t=(title.textContent||'').trim();let kind='';
      if(/兼容封装/.test(t))kind='无损封装';
      else if(/准备兼容播放|转为兼容格式|兼容转码/.test(t))kind='兼容转码';
      else if(/兼容播放失败/.test(t))kind='处理失败';
      else {status.classList.add('hidden');return;}
      let pct='';const width=progress?.querySelector('i')?.style?.width||'';
      if(/^\d+(?:\.\d+)?%$/.test(width)&&parseFloat(width)>0)pct=` ${Math.round(parseFloat(width))}%`;
      if(label)label.textContent=kind==='处理失败'?'视频处理失败':`视频处理中 · ${kind}${pct}`;
      status.classList.toggle('error',kind==='处理失败');status.classList.remove('hidden');
    };
    new MutationObserver(sync).observe(notice,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});
    if(progress)new MutationObserver(sync).observe(progress,{subtree:true,attributes:true,attributeFilter:['style','class']});
    sync();
  }

  function installPortraitFit() {
    const video=$('#videoPlayer'),stage=$('#viewerStage'),viewer=$('#viewer');
    if(!video||!stage)return;
    const clear=()=>stage.classList.remove('lh-video-portrait','lh-video-landscape');
    const fit=()=>{
      const w=Number(video.videoWidth)||0,h=Number(video.videoHeight)||0;
      if(!w||!h)return;
      const portrait=h>w*1.08;
      stage.classList.toggle('lh-video-portrait',portrait);
      stage.classList.toggle('lh-video-landscape',!portrait);
    };
    video.addEventListener('loadedmetadata',fit);video.addEventListener('loadeddata',fit);video.addEventListener('resize',fit);video.addEventListener('emptied',clear);
    viewer?.addEventListener('close',clear);fit();
  }

  document.addEventListener('click',e=>{
    const remove=e.target.closest('.tag-remove-inline');
    if(remove){e.preventDefault();e.stopImmediatePropagation();const chip=remove.closest('.tag-chip,.viewer-tag-chip');const strip=chip?.closest('[data-tag-strip],#viewerTagStrip');const path=strip?.dataset.tagStrip||currentPath();const tag=(chip?.dataset.tag||chip?.dataset.viewerTag||'').trim();if(path&&tag)removeTag(path,tag);return;}

    const add=e.target.closest('.tag-edit,#viewerTagAdd,.viewer-tag-add');
    if(add){e.preventDefault();e.stopImmediatePropagation();const strip=add.closest('[data-tag-strip],#viewerTagStrip');const path=strip?.dataset.tagStrip||currentPath();beginInlineTag(strip,path);return;}

    const rate=e.target.closest('[data-rate]');
    if(rate){e.preventDefault();e.stopImmediatePropagation();const widget=rate.closest('.rating-inline');const path=widget?.dataset.ratingPath;if(path)setRating(path,Number(rate.dataset.rate)||0);return;}
    const summary=e.target.closest('.rating-summary');
    if(summary){e.preventDefault();e.stopImmediatePropagation();summary.closest('.rating-inline')?.classList.toggle('expanded');return;}
  },true);

  document.addEventListener('dblclick',e=>{
    if(e.target.closest('#viewerTitle')){e.preventDefault();e.stopImmediatePropagation();beginTitleRename();}
  },true);

  new MutationObserver(()=>decorateAll()).observe(document.body,{subtree:true,childList:true});
  watchPlayerNotice();installBlackFrameWatch();installProcessingStatus();installPortraitFit();decorateAll();
})();
