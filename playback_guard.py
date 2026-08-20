from __future__ import annotations

STYLE = r"""
<style id="lh-playback-guard-style">
#viewer.viewer[open]{display:grid!important;grid-template-rows:minmax(0,1fr) 164px!important;overflow:hidden!important}
#viewer .player-shell{height:100%!important;min-height:0!important;display:grid!important;grid-template-rows:minmax(0,1fr) 54px!important}
#viewer .viewer-stage{min-height:0!important;height:auto!important;overflow:hidden!important;display:grid!important;place-items:center!important;background:#050506!important}
#viewer .viewer-stage video{display:block!important;width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important;object-fit:contain!important;object-position:center center!important;margin:0!important;transform:none!important;background:#050506!important}
#viewer .player-controls{height:54px!important;min-height:54px!important;max-height:54px!important}
#viewer .viewer-info{height:164px!important;min-height:0!important;overflow:hidden!important}
@media(max-width:1050px){
  #viewer.viewer[open]{grid-template-rows:minmax(0,1fr) 160px!important}
  #viewer .viewer-info{height:160px!important}
}
</style>
"""

SCRIPT = r"""
<script id="lh-playback-guard-script">
(()=>{
'use strict';
const AUTO_BLOCK='__LOCALHUB_AUTO_COMPAT_DISABLED__';
const SEEK_GUARD_MS=1500;
const video=document.querySelector('#videoPlayer');
const seek=document.querySelector('#seekBar');
const compatBtn=document.querySelector('#compatBtn');
const notice=document.querySelector('#playerNotice');
const noticeTitle=document.querySelector('#playerNoticeTitle');
const noticeText=document.querySelector('#playerNoticeText');
const compatProgress=document.querySelector('#compatProgress');
const diagnostics=document.querySelector('#mediaDiagnostics');
const pathNode=document.querySelector('#viewerPath');
const playMode=document.querySelector('#playMode');
if(!video||!compatBtn||!notice||!noticeTitle||!noticeText)return;

let manualCompatUntil=0;
let seekGuardUntil=0;
let nativeRetryToken=0;
const nativeFetch=window.fetch.bind(window);

function beginSeekGuard(){seekGuardUntil=Date.now()+SEEK_GUARD_MS;}
function extendSeekGuard(){seekGuardUntil=Math.max(seekGuardUntil,Date.now()+SEEK_GUARD_MS);}
function inSeekGuard(){return Date.now()<seekGuardUntil;}
function hideNotice(){notice.classList.add('hidden');}
function clearProgress(){compatProgress?.classList.add('hidden');}
function showManualCompatHint(title='原生播放失败',text='浏览器无法稳定直接播放此文件。可手动点击“兼容播放”生成兼容副本。'){
  noticeTitle.textContent=title;
  noticeText.textContent=text;
  clearProgress();
  notice.classList.remove('hidden');
  compatBtn.disabled=false;
  compatBtn.classList.add('recommended');
}
function showCompatFailure(){
  noticeTitle.textContent='兼容副本播放失败';
  noticeText.textContent='兼容副本没有正常播放。已停止自动重试，不会再次转换。';
  clearProgress();
  notice.classList.remove('hidden');
  compatBtn.disabled=false;
}
function encodedCurrentPath(){
  const raw=(pathNode?.textContent||'').trim();
  return raw ? raw.split('/').map(encodeURIComponent).join('/') : '';
}
function tryNativeCurrent(){
  const token=++nativeRetryToken;
  setTimeout(()=>{
    if(token!==nativeRetryToken)return;
    const path=encodedCurrentPath();
    if(!path)return;
    const src=video.getAttribute('src')||'';
    if(src && !src.includes('/api/compat/file'))return;
    video.src='/media/'+path;
    video.load();
    video.play().catch(()=>{});
  },0);
}
function markManualCompat(){manualCompatUntil=Date.now()+2500;}
compatBtn.addEventListener('pointerdown',markManualCompat,true);
compatBtn.addEventListener('click',markManualCompat,true);
compatBtn.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')markManualCompat();},true);

window.fetch=(input,init={})=>{
  const url=typeof input==='string'?input:(input&&input.url)||'';
  if(url.includes('/api/compat/start')){
    if(Date.now()>manualCompatUntil){
      tryNativeCurrent();
      const err=new Error(AUTO_BLOCK);
      err.name='LocalHubAutoCompatBlocked';
      return Promise.reject(err);
    }
    manualCompatUntil=0;
  }
  return nativeFetch(input,init);
};

if(seek){
  seek.addEventListener('pointerdown',beginSeekGuard,true);
  seek.addEventListener('input',extendSeekGuard,true);
  seek.addEventListener('change',extendSeekGuard,true);
}
video.addEventListener('seeking',extendSeekGuard,true);
video.addEventListener('seeked',extendSeekGuard,true);

// Capture media errors before the stable 2.2.3 target listener. This prevents
// a transient seek error or a compat-copy error from recursively starting a new conversion.
document.addEventListener('error',e=>{
  if(e.target!==video)return;
  const isCompat=(video.currentSrc||video.src||'').includes('/api/compat/file')||/兼容/.test(playMode?.textContent||'');
  if(inSeekGuard()){
    e.preventDefault();
    e.stopImmediatePropagation();
    hideNotice();
    compatBtn.classList.remove('recommended');
    setTimeout(()=>{
      if(video.error&&video.readyState===0&&!isCompat)showManualCompatHint('拖动后播放未恢复','刚才的拖动没有恢复播放。可再次尝试播放，或手动使用“兼容播放”。');
    },SEEK_GUARD_MS+80);
    return;
  }
  e.preventDefault();
  e.stopImmediatePropagation();
  if(isCompat)showCompatFailure();
  else showManualCompatHint();
},true);

// Suppress notices generated by the old automatic compatibility path. The old
// code is kept intact underneath, but its automatic /api/compat/start request is blocked above.
new MutationObserver(()=>{
  const title=(noticeTitle.textContent||'').trim();
  const text=(noticeText.textContent||'').trim();
  if(text.includes(AUTO_BLOCK)){
    hideNotice();
    compatBtn.disabled=false;
    compatBtn.classList.add('recommended');
    if(diagnostics)diagnostics.textContent=(diagnostics.textContent||'').replace(/\s*·\s*$/,'')+' · 原生优先，兼容播放仅手动触发';
    return;
  }
  if(title==='当前文件无法稳定拖动'&&inSeekGuard()){
    hideNotice();
    compatBtn.classList.remove('recommended');
  }
}).observe(notice,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});
})();
</script>
"""
