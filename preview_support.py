from __future__ import annotations

import json
import urllib.parse
from http import HTTPStatus
from pathlib import Path

import playback_priority
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
  document.addEventListener('pointerdown',e=>{
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


def install(server_module) -> None:
    """Add low-cost preview endpoints and playback-first scheduling."""
    playback_priority.install()
    original_make_handler = server_module.make_handler
    video_exts = set(server_module.VIDEO_EXTS)
    smart_html = Path(server_module.APP_DIR) / "smart_index.html"

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
                    if "</body>" in html:
                        html = html.replace("</body>", _PLAYBACK_PRIORITY_SCRIPT + "\n</body>", 1)
                    else:
                        html += _PLAYBACK_PRIORITY_SCRIPT
                    raw = html.encode("utf-8")
                    self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(raw), {"Cache-Control": "no-cache"})
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
