from __future__ import annotations

import urllib.parse
from pathlib import Path

import preview_support


def install(server_module) -> None:
    original_make_handler = server_module.make_handler
    smart_html = Path(server_module.APP_DIR) / "smart_index.html"

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class RepairPageHandler(BaseHandler):
            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path in {"/", "/index.html"}:
                    try:
                        html = smart_html.read_text("utf-8")
                    except OSError:
                        self.send_error(404)
                        return
                    injected = (
                        '<script src="/recommendation_ui.js"></script>\n'
                        + preview_support._PLAYBACK_PRIORITY_SCRIPT
                        + preview_support._PORTRAIT_LAYOUT_SCRIPT
                        + '<script src="/mse_ui.js"></script>\n'
                        + '<script src="/repair_ui.js"></script>\n'
                    )
                    if "</body>" in html:
                        html = html.replace("</body>", injected + "\n</body>", 1)
                    else:
                        html += injected
                    raw = html.encode("utf-8")
                    self._headers(200, "text/html; charset=utf-8", len(raw), {"Cache-Control": "no-cache"})
                    self.wfile.write(raw)
                    return
                return super().do_GET()

        return RepairPageHandler

    server_module.make_handler = make_handler
