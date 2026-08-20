from __future__ import annotations

import json
import urllib.parse
from http import HTTPStatus
from pathlib import Path

import compat_v3
import playback_guard
import smart_thumbnail

HOVER_SLOTS = 6


def install(server_module) -> None:
    """Add low-cost preview endpoints and the isolated Test3 playback guard."""
    compat_v3.install()

    original_make_handler = server_module.make_handler
    video_exts = set(server_module.VIDEO_EXTS)
    smart_html = Path(server_module.APP_DIR) / "smart_index.html"

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class PreviewHandler(BaseHandler):
            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)

                if parsed.path in {"/", "/index.html"}:
                    try:
                        html = smart_html.read_text("utf-8")
                    except OSError:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    injected = playback_guard.STYLE + "\n" + playback_guard.SCRIPT
                    if "</body>" in html:
                        html = html.replace("</body>", injected + "\n</body>", 1)
                    else:
                        html += injected
                    raw = html.encode("utf-8")
                    self._headers(
                        HTTPStatus.OK,
                        "text/html; charset=utf-8",
                        len(raw),
                        {"Cache-Control": "no-cache"},
                    )
                    self.wfile.write(raw)
                    return

                if parsed.path == "/api/smart/hover":
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
                            "playbackGuard": "test3-native-first",
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    self._headers(
                        HTTPStatus.OK,
                        "application/json; charset=utf-8",
                        len(raw),
                        {"Cache-Control": "no-store"},
                    )
                    self.wfile.write(raw)
                    return

                return super().do_GET()

        return PreviewHandler

    server_module.make_handler = make_handler
