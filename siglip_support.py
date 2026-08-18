from __future__ import annotations

import hashlib
import json
import statistics
import threading
import urllib.parse
from http import HTTPStatus
from pathlib import Path

from auto_tag_prompts import DEFAULT_TAG_PROMPTS
from io_scheduler import SCHEDULER
from siglip_encoder import ENCODER_NAME, SiglipModelBundle, SiglipOnnxEncoder
from visual_encoder import cosine, mean_vector


def _prompt_hash(prompts: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(prompts).encode("utf-8")).hexdigest()


def _install_manager_patch(auto_tag_support_module) -> None:
    Manager = auto_tag_support_module.AutoTagManager
    if getattr(Manager, "_localhub_siglip_patched", False):
        return

    original_init = Manager.__init__
    original_suggestions = Manager.suggestions
    original_queue_media = Manager.queue_media

    def init_with_siglip(self, store):
        original_init(self, store)
        self.siglip_bundle = SiglipModelBundle(store.root)
        self.siglip_encoder = SiglipOnnxEncoder(self.siglip_bundle)
        self._siglip_prompt_cache = None
        self._siglip_prompt_lock = threading.RLock()
        self._siglip_warmup_running = False
        if self.siglip_encoder.ready():
            self.encoder = self.siglip_encoder
            start_prompt_warmup(self)

    def refresh_encoder(self):
        if self.siglip_encoder.ready() and self.encoder.name != ENCODER_NAME:
            self.encoder = self.siglip_encoder
            self.invalidate_prototypes()
            self._siglip_prompt_cache = None
            start_prompt_warmup(self)
        return self.encoder

    def cached_prompt_vectors(self):
        result = {}
        missing: list[tuple[str, tuple[str, ...], str]] = []
        for tag, prompts in DEFAULT_TAG_PROMPTS.items():
            fingerprint = _prompt_hash(prompts)
            cached = self.index.text_vector(tag, ENCODER_NAME, fingerprint)
            if cached:
                result[tag] = cached
            else:
                missing.append((tag, prompts, fingerprint))
        return result, missing

    def build_prompt_vectors(self):
        refresh_encoder(self)
        if self.encoder.name != ENCODER_NAME:
            return {}
        with self._siglip_prompt_lock:
            if self._siglip_prompt_cache is not None:
                return self._siglip_prompt_cache
            result, missing = cached_prompt_vectors(self)
            if not missing:
                self._siglip_prompt_cache = result
                return result
            if SCHEDULER.busy():
                return result

            flat_prompts: list[str] = []
            group_sizes: list[int] = []
            for _, prompts, _ in missing:
                flat_prompts.extend(prompts)
                group_sizes.append(len(prompts))
            try:
                encoded = self.siglip_encoder.encode_texts(flat_prompts, batch_size=16)
                cursor = 0
                for (tag, _, fingerprint), count in zip(missing, group_sizes):
                    group = encoded[cursor : cursor + count]
                    cursor += count
                    vector = mean_vector(group)
                    if vector:
                        self.index.save_text_vector(tag, ENCODER_NAME, fingerprint, vector)
                        result[tag] = vector
            finally:
                self.siglip_encoder.unload_text()
            self._siglip_prompt_cache = result
            return result

    def warmup_worker(self):
        try:
            if not SCHEDULER.wait_background_idle(self.stop, grace=4.0):
                return
            build_prompt_vectors(self)
        except Exception as exc:
            with self.lock:
                self.last_error = f"SigLIP Prompt: {exc}"
        finally:
            with self._siglip_prompt_lock:
                self._siglip_warmup_running = False

    def start_prompt_warmup(self):
        if not self.siglip_encoder.ready():
            return
        _, missing = cached_prompt_vectors(self)
        if not missing:
            if self._siglip_prompt_cache is None:
                self._siglip_prompt_cache = {
                    tag: self.index.text_vector(tag, ENCODER_NAME, _prompt_hash(prompts))
                    for tag, prompts in DEFAULT_TAG_PROMPTS.items()
                }
            return
        with self._siglip_prompt_lock:
            if self._siglip_warmup_running:
                return
            self._siglip_warmup_running = True
        threading.Thread(target=lambda: warmup_worker(self), name="LocalHubSiglipPrompts", daemon=True).start()

    def semantic_suggestions(self, path: str, limit: int = 6) -> dict:
        refresh_encoder(self)
        if self.encoder.name != ENCODER_NAME:
            return original_suggestions(self, path, limit)
        vector = self.index.media_vector(path, ENCODER_NAME)
        if not vector:
            return {"ready": False, "items": [], "reason": "not-indexed"}

        frame_vectors = [row[2] for row in self.index.frame_vectors(path) if row[2]]
        if not frame_vectors:
            frame_vectors = [vector]
        existing = {tag.casefold() for tag in self.store.tags_for(path)}
        feedback = {key.casefold(): value for key, value in self.index.feedback_for(path).items()}
        text_vectors = build_prompt_vectors(self)
        if len(text_vectors) < len(DEFAULT_TAG_PROMPTS):
            start_prompt_warmup(self)
        prototypes = self._prototypes()
        items = []

        for tag, text_vector in text_vectors.items():
            key = tag.casefold()
            if key in existing or feedback.get(key) == -1:
                continue
            frame_scores = [cosine(frame, text_vector) for frame in frame_vectors]
            ordered = sorted(frame_scores)
            mean_score = statistics.fmean(frame_scores)
            upper = ordered[max(0, int((len(ordered) - 1) * 0.75))]
            peak = ordered[-1]
            semantic = mean_score * 0.55 + upper * 0.30 + peak * 0.15
            prototype_row = prototypes.get(key)
            prototype_score = cosine(vector, prototype_row["prototype"]) if prototype_row else None
            combined = semantic if prototype_score is None else semantic * 0.72 + prototype_score * 0.28
            items.append(
                {
                    "tag": tag,
                    "score": round(combined, 4),
                    "semanticScore": round(semantic, 4),
                    "prototypeScore": round(prototype_score, 4) if prototype_score is not None else None,
                    "frameMin": round(ordered[0], 4),
                    "frameMax": round(peak, 4),
                    "frames": len(frame_scores),
                    "source": "siglip-zero-shot+prototype" if prototype_score is not None else "siglip-zero-shot",
                }
            )

        semantic_keys = {tag.casefold() for tag in text_vectors}
        for key, row in prototypes.items():
            if key in existing or feedback.get(key) == -1 or key in semantic_keys:
                continue
            score = cosine(vector, row["prototype"])
            threshold = float(row["threshold"])
            if score < threshold:
                continue
            items.append(
                {
                    "tag": row["tag"],
                    "score": round(score, 4),
                    "semanticScore": None,
                    "prototypeScore": round(score, 4),
                    "frames": len(frame_vectors),
                    "positives": int(row["positives"]),
                    "source": "visual-prototype",
                }
            )

        items.sort(key=lambda row: row["score"], reverse=True)
        reason = "prompts-warming" if len(text_vectors) < len(DEFAULT_TAG_PROMPTS) else ""
        return {
            "ready": True,
            "items": items[: max(1, min(10, int(limit)))],
            "reason": reason,
            "calibrated": False,
            "promptVectors": len(text_vectors),
            "promptTarget": len(DEFAULT_TAG_PROMPTS),
        }

    def status_with_siglip(self, path: str = ""):
        refresh_encoder(self)
        encoder_name = self.encoder.name
        index_stats = self.index.stats(encoder_name)
        io_state = SCHEDULER.snapshot()
        with self.lock:
            prototype_cache = self._prototype_cache[1] if self._prototype_cache else {}
            payload = {
                "ok": True,
                "encoder": encoder_name,
                "semanticModel": encoder_name == ENCODER_NAME,
                "libraryRunning": self.library_running,
                "queued": self.urgent.qsize() + len(self.library),
                "current": self.current,
                "completed": self.completed,
                "failed": self.failed,
                "lastError": self.last_error,
                "lastElapsedMs": round(self.last_elapsed_ms, 1),
                "indexed": index_stats["media"],
                "indexedFrames": index_stats["frames"],
                "learnedTags": len(prototype_cache),
                "learnedTagsCached": bool(self._prototype_cache),
                "minPositives": auto_tag_support_module.MIN_TAG_POSITIVES,
                "io": io_state,
            }
        if path:
            payload["pathIndexed"] = self.index.has_media(path, encoder_name)
        payload["model"] = self.siglip_bundle.status()
        payload["suggestionMode"] = "siglip-zero-shot" if payload["semanticModel"] else "visual-prototype"
        if payload["semanticModel"]:
            cached, missing = cached_prompt_vectors(self)
            payload["promptVectors"] = len(cached)
            payload["promptTarget"] = len(DEFAULT_TAG_PROMPTS)
            payload["promptWarmup"] = self._siglip_warmup_running or bool(missing)
        return payload

    def queue_with_siglip(self, path: str):
        refresh_encoder(self)
        return original_queue_media(self, path)

    Manager.__init__ = init_with_siglip
    Manager._refresh_siglip_encoder = refresh_encoder
    Manager._siglip_prompt_vectors = build_prompt_vectors
    Manager._start_siglip_prompt_warmup = start_prompt_warmup
    Manager.suggestions = semantic_suggestions
    Manager.status = status_with_siglip
    Manager.queue_media = queue_with_siglip
    Manager._localhub_siglip_patched = True


def install(server_module, auto_tag_support_module) -> None:
    _install_manager_patch(auto_tag_support_module)
    import interactive_preview_support
    interactive_preview_support.install(server_module)

    app_dir = Path(server_module.APP_DIR)
    server_module.STATIC_FILES["/auto_tag_ui.js"] = app_dir / "auto_tag_ui.js"
    server_module.STATIC_FILES["/auto_tag_ui.css"] = app_dir / "auto_tag_ui.css"
    server_module.STATIC_FILES["/playback_stability.js"] = app_dir / "playback_stability.js"
    server_module.STATIC_FILES["/playback_stability.css"] = app_dir / "playback_stability.css"

    try:
        base_html = (app_dir / "smart_index.html").read_text("utf-8")
        enhanced_html = base_html.replace(
            "</head>",
            '  <link rel="stylesheet" href="/auto_tag_ui.css">\n  <link rel="stylesheet" href="/playback_stability.css">\n</head>',
            1,
        ).replace(
            "</body>",
            '  <script src="/auto_tag_ui.js"></script>\n  <script src="/playback_stability.js"></script>\n</body>',
            1,
        ).encode("utf-8")
    except OSError:
        enhanced_html = b""

    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class SiglipHandler(BaseHandler):
            def _siglip_json(self, payload, status=HTTPStatus.OK):
                raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._headers(status, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                self.wfile.write(raw)

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path in {"/", "/index.html"} and enhanced_html:
                    self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(enhanced_html), {"Cache-Control": "no-cache"})
                    self.wfile.write(enhanced_html)
                    return
                if parsed.path != "/api/auto-tag/model":
                    return super().do_GET()
                manager = getattr(store, "_auto_tag_manager", None)
                if manager is None:
                    return self._siglip_json({"ok": False, "error": "Auto Tag 尚未初始化"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return self._siglip_json({"ok": True, **manager.siglip_bundle.status()})

            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/api/auto-tag/model":
                    return super().do_POST()
                manager = getattr(store, "_auto_tag_manager", None)
                if manager is None:
                    return self._siglip_json({"ok": False, "error": "Auto Tag 尚未初始化"}, HTTPStatus.SERVICE_UNAVAILABLE)
                try:
                    data = self._read_json()
                    action = str(data.get("action", "install"))
                    if action == "install":
                        manager.siglip_bundle.start_install()
                    elif action == "unload":
                        manager.siglip_encoder.unload_all()
                    elif action == "refresh":
                        manager._refresh_siglip_encoder()
                    else:
                        raise ValueError("未知 SigLIP 模型操作")
                    return self._siglip_json({"ok": True, **manager.siglip_bundle.status()})
                except ValueError as exc:
                    return self._siglip_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

        return SiglipHandler

    server_module.make_handler = make_handler
