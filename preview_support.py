from __future__ import annotations

import json
import urllib.parse
from http import HTTPStatus
from pathlib import Path

import playback_priority
import recommendation_support
import smart_mode
import smart_thumbnail
from io_scheduler import SCHEDULER

HOVER_SLOTS = 6

_PLAYBACK_PRIORITY_SCRIPT = r"""
<script>
(()=>{
  const viewer=document.querySelector('#viewer');
  const video=document.querySelector('#videoPlayer');
  if(!viewer||!video)return;
  let active=false,heartbeat=null;
  const post=(payload,keepalive=false)=>fetch('/api/playback/activity',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload),cache:'no-store',keepalive
  }).catch(()=>{});
  const beat=()=>post({active:true});
  const setActive=value=>{
    if(value){
      if(!active){active=true;post({active:true});}
      if(!heartbeat)heartbeat=setInterval(beat,8000);
    }else{
      active=false;
      if(heartbeat){clearInterval(heartbeat);heartbeat=null;}
      post({active:false,seeking:false},true);
    }
  };
  // Use click rather than pointerdown. Long-press move intentionally suppresses
  // its synthetic click, so a move never leaves the playback-priority latch on.
  document.addEventListener('click',e=>{
    const card=e.target.closest?.('.card[data-id]');
    if(!card||!card.querySelector('.video-thumb'))return;
    if(e.target.closest?.('[data-fav],[data-edit-tags],[data-tag]'))return;
    setActive(true);
  },true);
  video.addEventListener('play',()=>setActive(true));
  video.addEventListener('seeking',()=>{setActive(true);post({active:true,seeking:true});});
  video.addEventListener('seeked',()=>post({active:true,seeking:false}));
  viewer.addEventListener('close',()=>setActive(false));
  addEventListener('pagehide',()=>{if(active)post({active:false,seeking:false},true);});
  addEventListener('beforeunload',()=>{if(active)post({active:false,seeking:false},true);});
})();
</script>
"""

_PORTRAIT_LAYOUT_SCRIPT = r"""
<style>
.viewer.lh-probe-portrait{width:min(720px,94vw)!important;height:min(96vh,1040px)!important}
.viewer.lh-probe-portrait .player-shell{height:calc(100% - 164px)!important}
.viewer.lh-probe-portrait .viewer-stage,
.viewer.lh-probe-landscape .viewer-stage{min-height:0!important;display:flex!important;align-items:center!important;justify-content:center!important;overflow:hidden!important;background:#050506!important}
.viewer.lh-probe-portrait .viewer-stage video,
.viewer.lh-probe-landscape .viewer-stage video{width:var(--lh-fit-w,auto)!important;height:var(--lh-fit-h,auto)!important;max-width:none!important;max-height:none!important;object-fit:contain!important;object-position:center center!important;flex:none!important;background:#050506!important}
.viewer-stage.lh-click-toggle{cursor:pointer}
@media(max-width:760px){.viewer.lh-probe-portrait{width:100vw!important;max-width:100vw!important;height:100vh!important;max-height:100vh!important;border-radius:0!important}.viewer.lh-probe-portrait .player-shell{height:calc(100% - 160px)!important}}
</style>
<script>
(()=>{
  const viewer=document.querySelector('#viewer');
  const stage=document.querySelector('#viewerStage');
  const video=document.querySelector('#videoPlayer');
  const pathNode=document.querySelector('#viewerPath');
  if(!viewer||!stage||!video||!pathNode)return;
  let token=0,displayAspect=0,fitFrame=0;
  const currentPath=()=>String(pathNode.textContent||'').trim();
  const scheduleFit=()=>{
    cancelAnimationFrame(fitFrame);
    fitFrame=requestAnimationFrame(fit);
  };
  const fit=()=>{
    fitFrame=0;
    if(!displayAspect)return;
    const sw=stage.clientWidth,sh=stage.clientHeight;
    if(sw<2||sh<2)return;
    let w=sw,h=w/displayAspect;
    if(h>sh){h=sh;w=h*displayAspect;}
    w=Math.max(1,Math.floor(w));
    h=Math.max(1,Math.floor(h));
    stage.style.setProperty('--lh-fit-w',`${w}px`);
    stage.style.setProperty('--lh-fit-h',`${h}px`);
  };
  const clear=()=>{
    token++;
    displayAspect=0;
    viewer.classList.remove('lh-probe-portrait','lh-probe-landscape');
    stage.classList.remove('lh-probe-stage-portrait');
    stage.style.removeProperty('--lh-probe-aspect');
    stage.style.removeProperty('--lh-fit-w');
    stage.style.removeProperty('--lh-fit-h');
  };
  const apply=(aspect,width,height)=>{
    const w=Number(width)||0,h=Number(height)||0;
    const declared=Number(aspect)||0;
    displayAspect=declared>0?declared:(w>0&&h>0?w/h:0);
    if(!displayAspect)return;
    const portrait=displayAspect<0.93;
    viewer.classList.toggle('lh-probe-portrait',portrait);
    viewer.classList.toggle('lh-probe-landscape',!portrait);
    stage.classList.toggle('lh-probe-stage-portrait',portrait);
    stage.style.setProperty('--lh-probe-aspect',String(displayAspect));
    scheduleFit();
  };
  const refresh=async()=>{
    const path=currentPath();
    const mine=++token;
    if(!path)return;
    try{
      const response=await fetch(`/api/media/probe?path=${encodeURIComponent(path)}`,{cache:'no-store'});
      if(!response.ok)return;
      const data=await response.json();
      if(mine!==token||!viewer.open||currentPath()!==path)return;
      const p=data.probe||{};
      apply(p.displayAspect,p.width,p.height);
    }catch{}
  };

  stage.classList.add('lh-click-toggle');
  stage.addEventListener('click',e=>{
    if(!viewer.open||!video.currentSrc)return;
    if(e.defaultPrevented||e.target.closest?.('button,input,select,a'))return;
    if(video.paused)video.play().catch(()=>{});else video.pause();
  });

  const ro=typeof ResizeObserver==='function'?new ResizeObserver(scheduleFit):null;
  ro?.observe(stage);
  document.addEventListener('fullscreenchange',scheduleFit);
  addEventListener('resize',scheduleFit);
  new MutationObserver(()=>{clear();setTimeout(refresh,0)}).observe(pathNode,{subtree:true,childList:true,characterData:true});
  video.addEventListener('loadedmetadata',()=>{refresh();scheduleFit();});
  video.addEventListener('loadeddata',scheduleFit);
  viewer.addEventListener('close',clear);
  refresh();
})();
</script>
"""

_MP4_HEALTH_SCRIPT = r"""
<script>
(()=>{
  const viewer=document.querySelector('#viewer');
  const video=document.querySelector('#videoPlayer');
  const pathNode=document.querySelector('#viewerPath');
  const seek=document.querySelector('#seekBar');
  const compat=document.querySelector('#compatBtn');
  const toast=document.querySelector('#toast');
  if(!viewer||!video||!pathNode||!seek||!compat)return;

  let lastTime=0,lastTick=0,peakTime=0,manualUntil=0;
  let backwardHits=[],triggeredPath='',repairing=false,token=0;
  const currentPath=()=>String(pathNode.textContent||'').trim();
  const nativeSource=()=>{
    const src=String(video.currentSrc||video.getAttribute('src')||'');
    return viewer.open&&src.includes('/media/')&&!src.includes('/api/compat/');
  };
  const isMp4Path=path=>/\.(?:mp4|m4v)$/i.test(path||'');
  const showToast=text=>{
    if(!toast)return;
    toast.textContent=text;toast.classList.add('show');
    clearTimeout(showToast.t);showToast.t=setTimeout(()=>toast.classList.remove('show'),2200);
  };
  const reset=()=>{
    token++;lastTime=0;lastTick=0;peakTime=0;manualUntil=0;
    backwardHits=[];repairing=false;triggeredPath='';
  };
  const triggerRepair=async reason=>{
    const path=currentPath();
    if(repairing||!nativeSource()||!isMp4Path(path)||triggeredPath===path)return;
    const mine=++token;
    repairing=true;
    try{
      const r=await fetch(`/api/media/probe?path=${encodeURIComponent(path)}`,{cache:'no-store'});
      if(!r.ok)throw new Error('probe failed');
      const d=await r.json(),p=d.probe||{};
      if(mine!==token||currentPath()!==path||!nativeSource())return;
      // Only auto-repair when FFmpeg can keep the H.264 video stream intact.
      // Other codecs may require a costly full transcode and stay user-driven.
      if(String(p.videoCodec||'').toLowerCase()!=='h264'||p.compatMode!=='remux')return;
      triggeredPath=path;
      showToast(reason==='seek'?'MP4 时间轴无法定位，正在无损修复…':'检测到 MP4 时间轴反复跳回，正在无损修复…');
      compat.click();
    }catch{}
    finally{repairing=false;}
  };

  const markManual=()=>{manualUntil=Date.now()+2600;};
  seek.addEventListener('pointerdown',markManual,true);
  seek.addEventListener('input',markManual,true);
  seek.addEventListener('keydown',markManual,true);
  seek.addEventListener('change',()=>{
    const d=Number.isFinite(video.duration)&&video.duration>0?video.duration:0;
    if(!d||!nativeSource()||!isMp4Path(currentPath()))return;
    markManual();
    const target=d*Math.max(0,Math.min(1000,Number(seek.value)||0))/1000;
    setTimeout(()=>{
      if(!nativeSource()||currentPath()===triggeredPath)return;
      const tolerance=Math.max(2.5,d*.012);
      if(Math.abs((video.currentTime||0)-target)>tolerance)void triggerRepair('seek');
    },950);
  },true);

  video.addEventListener('timeupdate',()=>{
    if(!nativeSource()||!isMp4Path(currentPath())){
      lastTime=video.currentTime||0;lastTick=performance.now();return;
    }
    const now=performance.now(),cur=Math.max(0,video.currentTime||0);
    peakTime=Math.max(peakTime,cur);
    if(Date.now()>manualUntil&&lastTick&&now-lastTick<3200&&lastTime>2.5&&cur+1.35<lastTime){
      const stamp=Date.now();
      backwardHits=backwardHits.filter(t=>stamp-t<9000);
      backwardHits.push(stamp);
      if(backwardHits.length>=2)void triggerRepair('loop');
    }
    lastTime=cur;lastTick=now;
  });

  video.addEventListener('loadedmetadata',()=>{
    lastTime=video.currentTime||0;peakTime=lastTime;lastTick=performance.now();backwardHits=[];
  });
  new MutationObserver(()=>reset()).observe(pathNode,{subtree:true,childList:true,characterData:true});
  viewer.addEventListener('close',reset);
})();
</script>
"""


def install(server_module) -> None:
    """Add low-cost preview endpoints, playback priority, exact-fit layout, recommendations, and native MP4 health checks."""
    recommendation_support.install(server_module, smart_mode)
    playback_priority.install()
    original_make_handler = server_module.make_handler
    video_exts = set(server_module.VIDEO_EXTS)
    smart_html = Path(server_module.APP_DIR) / "smart_index.html"
    recommendation_js = Path(server_module.APP_DIR) / "recommendation_ui.js"

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class PreviewHandler(BaseHandler):
            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/api/playback/activity":
                    try:
                        payload = self._read_json()
                    except ValueError as exc:
                        return self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    active_raw = payload.get("active")
                    seeking_raw = payload.get("seeking")
                    active = active_raw if isinstance(active_raw, bool) else None
                    seeking = seeking_raw if isinstance(seeking_raw, bool) else None
                    SCHEDULER.note(active=active, seeking=seeking)
                    return self._send_json({"ok": True, "priority": SCHEDULER.snapshot()})
                return super().do_POST()

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)

                if parsed.path in {"/", "/index.html"}:
                    try:
                        html = smart_html.read_text("utf-8")
                    except OSError:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    injected = (
                        '<script src="/recommendation_ui.js"></script>\n'
                        + _PLAYBACK_PRIORITY_SCRIPT
                        + _PORTRAIT_LAYOUT_SCRIPT
                        + _MP4_HEALTH_SCRIPT
                    )
                    if "</body>" in html:
                        html = html.replace("</body>", injected + "\n</body>", 1)
                    else:
                        html += injected
                    raw = html.encode("utf-8")
                    self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(raw), {"Cache-Control": "no-cache"})
                    self.wfile.write(raw)
                    return

                if parsed.path == "/recommendation_ui.js":
                    try:
                        raw = recommendation_js.read_bytes()
                    except OSError:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._headers(HTTPStatus.OK, "application/javascript; charset=utf-8", len(raw), {"Cache-Control": "no-cache"})
                    self.wfile.write(raw)
                    return

                if parsed.path == "/api/smart/hover":
                    if SCHEDULER.busy():
                        self.send_response(HTTPStatus.NO_CONTENT)
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("X-LocalHub-Preview", "paused-for-playback")
                        self.end_headers()
                        return
                    relative = query.get("path", [""])[0]
                    try:
                        slot = int(query.get("slot", ["0"])[0] or 0)
                    except ValueError:
                        slot = 0
                    slot = max(0, min(HOVER_SLOTS - 1, slot))
                    try:
                        media = store.resolve_media(relative)
                    except (ValueError, FileNotFoundError):
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    if media.suffix.lower() not in video_exts:
                        self.send_error(HTTPStatus.BAD_REQUEST)
                        return
                    data = smart_thumbnail.get_hover_frame(media, slot=slot, size=360)
                    if not data:
                        self.send_response(HTTPStatus.NO_CONTENT)
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        return
                    self._headers(
                        HTTPStatus.OK,
                        "image/jpeg",
                        len(data),
                        {"Cache-Control": "no-store", "X-LocalHub-Preview": f"hover-{slot}"},
                    )
                    self.wfile.write(data)
                    return

                if parsed.path == "/api/smart/preview-status":
                    raw = json.dumps(
                        {
                            "ok": True,
                            "ffmpeg": smart_thumbnail.ffmpeg_available(),
                            "hoverWorkers": 1,
                            "hoverSlots": HOVER_SLOTS,
                            "priority": SCHEDULER.snapshot(),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                    self.wfile.write(raw)
                    return

                return super().do_GET()

        return PreviewHandler

    server_module.make_handler = make_handler
