from __future__ import annotations

import json
import urllib.parse
from http import HTTPStatus

from io_scheduler import SCHEDULER


def install(server_module) -> None:
    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class IOHandler(BaseHandler):
            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/api/io/status":
                    return super().do_GET()
                payload = {"ok": True, **SCHEDULER.snapshot()}
                raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                self.wfile.write(raw)

            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/api/io/activity":
                    return super().do_POST()
                try:
                    data = self._read_json()
                    playing = data.get("playing") if isinstance(data.get("playing"), bool) else None
                    seeking = data.get("seeking") if isinstance(data.get("seeking"), bool) else None
                    SCHEDULER.note(playing=playing, seeking=seeking)
                    raw = json.dumps({"ok": True, **SCHEDULER.snapshot()}, separators=(",", ":")).encode("utf-8")
                    self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                    self.wfile.write(raw)
                except ValueError as exc:
                    self._error_json(HTTPStatus.BAD_REQUEST, str(exc))

        return IOHandler

    server_module.make_handler = make_handler
