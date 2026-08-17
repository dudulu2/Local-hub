from __future__ import annotations

import json
import urllib.parse
from http import HTTPStatus


def install(server_module, smart_mode_module) -> None:
    """Add 0-5 personal ratings without changing the media files themselves."""
    Store = server_module.MediaStore

    def rating_for(self, rel: str) -> int:
        with self.lock:
            entry = self._metadata.get("items", {}).get(rel, {})
            try:
                value = int(entry.get("rating", 0) or 0)
            except (TypeError, ValueError):
                value = 0
            return max(0, min(5, value))

    def set_rating(self, rel: str, rating: int) -> int:
        self.resolve_media(rel)
        try:
            value = int(rating)
        except (TypeError, ValueError) as exc:
            raise ValueError("评分必须是 0 到 5") from exc
        if value < 0 or value > 5:
            raise ValueError("评分必须是 0 到 5")
        with self.lock:
            items = self._metadata.setdefault("items", {})
            entry = dict(items.get(rel, {}))
            if value:
                entry["rating"] = value
                items[rel] = entry
            else:
                entry.pop("rating", None)
                if entry:
                    items[rel] = entry
                else:
                    items.pop(rel, None)
            self._save_metadata()
        return value

    Store.rating_for = rating_for
    Store.set_rating = set_rating

    original_scan = Store.scan
    def scan_with_rating(self):
        rows = original_scan(self)
        with self.lock:
            metadata = dict(self._metadata.get("items", {}))
        for row in rows:
            try:
                value = int(metadata.get(row["id"], {}).get("rating", 0) or 0)
            except (TypeError, ValueError):
                value = 0
            row["rating"] = max(0, min(5, value))
        return rows
    Store.scan = scan_with_rating

    original_public = smart_mode_module._media_public
    def media_public_with_rating(item: dict) -> dict:
        row = original_public(item)
        try:
            row["rating"] = max(0, min(5, int(item.get("rating", 0) or 0)))
        except (TypeError, ValueError):
            row["rating"] = 0
        return row
    smart_mode_module._media_public = media_public_with_rating

    original_make_handler = server_module.make_handler
    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class RatingHandler(BaseHandler):
            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/api/rating":
                    query = urllib.parse.parse_qs(parsed.query)
                    rel = query.get("path", [""])[0]
                    try:
                        store.resolve_media(rel)
                        payload = {"ok": True, "path": rel, "rating": store.rating_for(rel), "tags": store.tags_for(rel)}
                    except (ValueError, FileNotFoundError) as exc:
                        raw = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
                        self._headers(HTTPStatus.NOT_FOUND, "application/json; charset=utf-8", len(raw), {"Cache-Control":"no-store"})
                        self.wfile.write(raw)
                        return
                    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control":"no-store"})
                    self.wfile.write(raw)
                    return
                return super().do_GET()

            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/api/rating":
                    return super().do_POST()
                try:
                    data = self._read_json()
                    rel = str(data.get("path", ""))
                    value = store.set_rating(rel, data.get("rating", 0))
                    raw = json.dumps({"ok": True, "path": rel, "rating": value}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control":"no-store"})
                    self.wfile.write(raw)
                except FileNotFoundError as exc:
                    self._error_json(HTTPStatus.NOT_FOUND, str(exc))
                except (ValueError, OSError) as exc:
                    self._error_json(HTTPStatus.BAD_REQUEST, str(exc))

        return RatingHandler

    server_module.make_handler = make_handler
