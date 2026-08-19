from __future__ import annotations

STYLE = r"""
<style id="lh-recovery-style">
.viewer-stage{contain:layout paint}
.viewer-stage video{display:block;object-fit:contain!important;object-position:center center!important;max-width:100%!important;max-height:100%!important}
.viewer-stage.lh-video-portrait video{width:auto!important;height:100%!important;max-width:100%!important;max-height:100%!important}
.viewer-stage.lh-video-landscape video{width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important}
.player-notice.lh-passive-notice{display:none!important}
.mode-pill.lh-mode-busy{border:0!important;background:transparent!important;padding:2px 0!important;color:#8b8b92!important;font-size:9px!important}
.mode-pill.lh-mode-error{color:#c98383!important}
.mode-pill.lh-mode-busy::before{content:'';display:inline-block;width:5px;height:5px;margin-right:5px;border-radius:50%;background:currentColor;vertical-align:1px;animation:lh-status-pulse 1.1s ease-in-out infinite}
@keyframes lh-status-pulse{0%,100%{opacity:.28}50%{opacity:1}}
.lh-recommend-strip{height:122px;flex:0 0 122px;border-top:1px solid #242428;background:#0d0d0f;padding:8px 14px 10px;overflow:hidden}
.lh-recommend-head{height:20px;display:flex;align-items:center;justify-content:space-between;color:#8d8d94;font-size:10px}
.lh-recommend-head strong{color:#d8d8dc;font-size:11px}.lh-recommend-head span{color:#55555d;font-size:9px}
.lh-recommend-row{height:82px;display:flex;gap:9px;overflow-x:auto;overflow-y:hidden;padding:3px 0 2px;scrollbar-width:thin}
.lh-rec-card{width:132px;min-width:132px;border:0;background:transparent;color:inherit;text-align:left;padding:0;cursor:pointer;display:grid;grid-template-columns:72px 1fr;grid-template-rows:41px 18px;column-gap:7px;align-items:start}
.lh-rec-thumb{grid-row:1/3;width:72px;height:59px;border:1px solid #29292e;border-radius:6px;overflow:hidden;background:#171719;position:relative}
.lh-rec-thumb img{width:100%;height:100%;display:block;object-fit:cover;opacity:0;transition:opacity .15s}.lh-rec-thumb img.loaded{opacity:1}
.lh-rec-thumb::after{content:'▶';position:absolute;inset:0;display:grid;place-items:center;color:#aaa;font-size:13px;background:linear-gradient(transparent,rgba(0,0,0,.22));pointer-events:none}
.lh-rec-card:hover .lh-rec-thumb{border-color:#55555c}.lh-rec-card:hover .lh-rec-title{color:#fff}
.lh-rec-title{font-size:10px;line-height:1.28;color:#c4c4c9;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-all}
.lh-rec-meta{font-size:8.5px;color:#66666d;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-top:2px}
#viewer.lh-rec-visible .player-shell{height:calc(100% - 286px)!important}
@media(max-height:720px){.lh-recommend-strip{display:none!important}#viewer.lh-rec-visible .player-shell{height:calc(100% - 164px)!important}}
@media(max-width:700px){.lh-recommend-strip{height:112px;flex-basis:112px;padding-left:10px;padding-right:10px}.lh-rec-card{width:122px;min-width:122px;grid-template-columns:66px 1fr}.lh-rec-thumb{width:66px;height:54px}#viewer.lh-rec-visible .player-shell{height:calc(100% - 276px)!important}}
</style>
"""

SCRIPT = r"""
<script id="lh-recovery-script">
(()=>{
'use strict';
const viewer=document.querySelector('#viewer'),video=document.querySelector('#videoPlayer'),stage=document.querySelector('#viewerStage');
const pathNode=document.querySelector('#viewerPath'),notice=document.querySelector('#playerNotice'),noticeTitle=document.querySelector('#playerNoticeTitle');
const noticeText=document.querySelector('#playerNoticeText'),progress=document.querySelector('#compatProgress'),mode=document.querySelector('#playMode');
const info=document.querySelector('.viewer-info'),search=document.querySelector('#searchInput');
if(!viewer||!video||!stage||!pathNode||!info)return;
const esc=(s='')=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const read=(k,f)=>{try{return JSON.parse(localStorage.getItem(k)||JSON.stringify(f));}catch{return f;}};
const write=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v));}catch{}};
function fit(){const w=video.videoWidth||0,h=video.videoHeight||0;if(!w||!h)return;const portrait=h>w*1.08;stage.classList.toggle('lh-video-portrait',portrait);stage.classList.toggle('lh-video-landscape',!portrait);}
video.addEventListener('loadedmetadata',()=>{fit();requestAnimationFrame(fit)});video.addEventListener('loadeddata',fit);video.addEventListener('resize',fit);
function passiveLabel(title,text){if(/兼容封装|无损封装/.test(title))return'正在无损封装';if(/准备兼容播放/.test(title))return'正在准备兼容播放';if(/正在转为兼容格式|兼容转码/.test(title))return'正在兼容转码';if(/正在分析媒体|正在分析/.test(title))return'分析媒体';if(/兼容播放失败/.test(title))return'兼容失败';if(/兼容/.test(text)&&/准备|转码|封装/.test(text))return'兼容处理中';return'';}
function mirror(){if(!notice||notice.classList.contains('hidden')||!mode)return;const title=(noticeTitle?.textContent||'').trim(),text=(noticeText?.textContent||'').trim(),label=passiveLabel(title,text);if(!label){notice.classList.remove('lh-passive-notice');return;}let pct='';const width=progress?.querySelector('i')?.style.width||'';if(/^\d+(?:\.\d+)?%$/.test(width)&&width!=='0%')pct=` ${Math.round(parseFloat(width))}%`;mode.textContent=label+pct;mode.classList.add('lh-mode-busy');mode.classList.toggle('lh-mode-error',label==='兼容失败');notice.classList.add('lh-passive-notice');}
if(notice)new MutationObserver(mirror).observe(notice,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class','style']});
if(progress)new MutationObserver(mirror).observe(progress,{subtree:true,attributes:true,attributeFilter:['style','class']});
if(mode)new MutationObserver(()=>{if(/^(原生|兼容封装|兼容转码)$/.test((mode.textContent||'').trim())){mode.classList.remove('lh-mode-busy','lh-mode-error');notice?.classList.remove('lh-passive-notice');}}).observe(mode,{subtree:true,childList:true,characterData:true});
const panel=document.createElement('section');panel.id='lhRecommendations';panel.className='lh-recommend-strip hidden';panel.innerHTML='<div class="lh-recommend-head"><strong>猜你想看</strong><span>本地推荐 · 不联网</span></div><div class="lh-recommend-row"></div>';info.insertAdjacentElement('afterend',panel);const row=panel.querySelector('.lh-recommend-row');
let token=0,controller=null,timer=0,current=[];
function hide(){token++;clearTimeout(timer);controller?.abort();controller=null;current=[];row.innerHTML='';panel.classList.add('hidden');viewer.classList.remove('lh-rec-visible');}
function history(){const raw=read('localhub:progress',{});return Object.fromEntries(Object.entries(raw||{}).sort((a,b)=>(b[1]?.at||0)-(a[1]?.at||0)).slice(0,160));}
function exposure(){const raw=read('localhub:recExposure',{}),now=Date.now();return Object.fromEntries(Object.entries(raw||{}).filter(([,v])=>v&&now-(Number(v.at)||0)<45*86400000).slice(-240));}
function render(items){if(!items.length){hide();return;}current=items;row.innerHTML=items.map((item,i)=>`<button class="lh-rec-card" type="button" data-i="${i}" title="${esc(item.name)}"><span class="lh-rec-thumb"><img loading="lazy" decoding="async" src="${esc(item.thumb||'')}" alt=""></span><span class="lh-rec-title">${esc(item.name)}</span><span class="lh-rec-meta">${esc(item.folder||'根目录')} · ${esc(String(item.ext||'').toUpperCase())}</span></button>`).join('');panel.classList.remove('hidden');viewer.classList.add('lh-rec-visible');row.querySelectorAll('img').forEach(img=>{img.addEventListener('load',()=>img.classList.add('loaded'),{once:true});img.addEventListener('error',()=>img.removeAttribute('src'),{once:true});});const ex=exposure(),now=Date.now();for(const item of items){const old=ex[item.id]||{};ex[item.id]={at:now,count:Math.min(99,(Number(old.count)||0)+1)}}write('localhub:recExposure',ex);}
async function load(path){const mine=++token;controller?.abort();controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),1800);try{const r=await fetch('/api/recommend',{method:'POST',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({path,limit:8,history:history(),exposure:exposure(),favorites:read('localhub:favorites',[])})});if(!r.ok)return;const data=await r.json();if(mine!==token||!viewer.open||(pathNode.textContent||'').trim()!==path)return;render((Array.isArray(data.items)?data.items:[]).filter(x=>x&&x.kind==='video'&&x.id!==path).slice(0,8));}catch(e){if(e?.name!=='AbortError'&&mine===token)hide();}finally{clearTimeout(timeout);if(mine===token)controller=null;}}
function schedule(){clearTimeout(timer);const path=(pathNode.textContent||'').trim();stage.classList.remove('lh-video-portrait','lh-video-landscape');if(!viewer.open||!path){hide();return;}panel.classList.add('hidden');viewer.classList.remove('lh-rec-visible');timer=setTimeout(()=>load(path),120);}
row.addEventListener('click',e=>{const card=e.target.closest('.lh-rec-card');if(!card)return;const item=current[Number(card.dataset.i)||0];if(!item||!search)return;document.querySelector('#closeViewer')?.click();search.value=item.name||item.id;search.dispatchEvent(new Event('input',{bubbles:true}));const deadline=Date.now()+3500,poll=setInterval(()=>{const target=[...document.querySelectorAll('.card[data-id]')].find(n=>n.dataset.id===item.id);if(target){clearInterval(poll);target.click();}else if(Date.now()>deadline)clearInterval(poll);},120);});
new MutationObserver(schedule).observe(pathNode,{subtree:true,childList:true,characterData:true});viewer.addEventListener('close',()=>{stage.classList.remove('lh-video-portrait','lh-video-landscape');notice?.classList.remove('lh-passive-notice');mode?.classList.remove('lh-mode-busy','lh-mode-error');hide();});viewer.addEventListener('cancel',hide);schedule();
})();
</script>
"""
