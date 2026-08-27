from __future__ import annotations

import json
import threading
import time
import urllib.parse
from http import HTTPStatus

from auto_tag_profile import AutoTagProfile


def install(server_module, auto_tag_support_module) -> None:
    Manager = auto_tag_support_module.AutoTagManager
    if getattr(Manager, "_localhub_v2_patched", False):
        return

    original_init = Manager.__init__
    original_status = Manager.status

    def init_with_profile(self, store):
        original_init(self, store)
        self.profile = AutoTagProfile(store.root)
        self.rematch_paths: set[str] = set()
        self.rematch_lock = threading.RLock()
        self._last_catalog_snapshot: set[str] = set()

    def mark_rematch(self, path: str = "") -> None:
        with self.rematch_lock:
            if path:
                self.rematch_paths.add(path)
            else:
                for row in self.index.all_media(self.encoder.name):
                    if row.get("path"):
                        self.rematch_paths.add(str(row["path"]))

    def discover_new_media(self) -> list[str]:
        current = set(self._catalog_video_ids())
        if not self._last_catalog_snapshot:
            self._last_catalog_snapshot = set(current)
        new_paths = [path for path in sorted(current) if not self.index.has_media(path, self.encoder.name)]
        self._last_catalog_snapshot = set(current)
        return new_paths

    def queue_new_media(self) -> int:
        paths = discover_new_media(self)
        for path in paths:
            self.queue_media(path)
        return len(paths)

    def profile_payload(self) -> dict:
        return {"packs": self.profile.packs(), "profile": self.profile.snapshot()}

    def status_with_profile(self, path: str = "") -> dict:
        payload = original_status(self, path)
        snap = self.profile.snapshot()
        with self.rematch_lock:
            rematch_count = len(self.rematch_paths)
        payload["profile"] = snap
        payload["profileConfigured"] = bool(snap.get("configured"))
        payload["rematchPending"] = rematch_count
        payload["newMediaPending"] = len(discover_new_media(self))
        return payload

    Manager.__init__ = init_with_profile
    Manager.mark_rematch = mark_rematch
    Manager.discover_new_media = discover_new_media
    Manager.queue_new_media = queue_new_media
    Manager.profile_payload = profile_payload
    Manager.status = status_with_profile
    Manager._localhub_v2_patched = True

    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class AutoTagV2Handler(BaseHandler):
            def _v2_json(self, payload, status=HTTPStatus.OK):
                raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._headers(status, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                self.wfile.write(raw)

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                manager = getattr(store, "_auto_tag_manager", None)
                if manager is None:
                    return super().do_GET()
                if parsed.path == "/api/auto-tag/profile":
                    return self._v2_json({"ok": True, **manager.profile_payload()})
                if parsed.path == "/api/auto-tag/new-media":
                    return self._v2_json({"ok": True, "paths": manager.discover_new_media()})
                return super().do_GET()

            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                manager = getattr(store, "_auto_tag_manager", None)
                if manager is None or parsed.path not in {
                    "/api/auto-tag/profile",
                    "/api/auto-tag/rematch",
                    "/api/auto-tag/new-media",
                    "/api/auto-tag/feedback-v2",
                }:
                    return super().do_POST()
                try:
                    data = self._read_json()
                    if parsed.path == "/api/auto-tag/profile":
                        action = str(data.get("action", "update"))
                        if action == "select-pack":
                            profile = manager.profile.select_pack(str(data.get("packId", "")))
                        elif action == "update":
                            profile = manager.profile.update(
                                tags=data.get("tags"),
                                pack_id=data.get("packId"),
                                configured=data.get("configured", True),
                            )
                        else:
                            raise ValueError("未知 Tag 配置操作")
                        manager.index.clear_text_vectors()
                        manager.invalidate_prototypes()
                        manager.mark_rematch()
                        if hasattr(manager, "_siglip_prompt_cache"):
                            manager._siglip_prompt_cache = None
                        return self._v2_json({"ok": True, "profile": profile, "rematchPending": len(manager.rematch_paths)})

                    if parsed.path == "/api/auto-tag/rematch":
                        with manager.rematch_lock:
                            paths = sorted(manager.rematch_paths)
                            manager.rematch_paths.clear()
                        return self._v2_json({"ok": True, "paths": paths, "count": len(paths)})

                    if parsed.path == "/api/auto-tag/new-media":
                        count = manager.queue_new_media()
                        return self._v2_json({"ok": True, "queued": count})

                    path = str(data.get("path", ""))
                    tag = str(data.get("tag", "")).strip()
                    value = int(data.get("value", -1))
                    store.resolve_media(path)
                    manager.index.set_feedback(path, tag, value)
                    manager.invalidate_prototypes()
                    manager.mark_rematch(path)
                    return self._v2_json({"ok": True, "rematchPending": len(manager.rematch_paths)})
                except FileNotFoundError as exc:
                    return self._v2_json({"ok": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)
                except (ValueError, OSError) as exc:
                    return self._v2_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

        return AutoTagV2Handler

    server_module.make_handler = make_handler
