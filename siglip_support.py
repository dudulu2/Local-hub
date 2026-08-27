from __future__ import annotations

import hashlib
import json
import statistics
import threading
import urllib.parse
from http import HTTPStatus
from pathlib import Path

from auto_tag_prompts import DEFAULT_TAG_PROMPTS, prompts_from_tags
from io_scheduler import SCHEDULER
from siglip_encoder import ENCODER_NAME, SiglipModelBundle, SiglipOnnxEncoder
from visual_encoder import DEFAULT_ENCODER, cosine, mean_vector


def _prompt_hash(prompts: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(prompts).encode("utf-8")).hexdigest()


def _install_manager_patch(auto_tag_support_module) -> None:
    Manager = auto_tag_support_module.AutoTagManager
    if getattr(Manager, "_localhub_siglip_patched", False):
        return

    original_init = Manager.__init__
    original_suggestions = Manager.suggestions
    original_queue_media = Manager.queue_media
    original_start_library = Manager.start_library

    def init_with_siglip(self, store):
        original_init(self, store)
        self.siglip_bundle = SiglipModelBundle(store.root)
        self.siglip_encoder = SiglipOnnxEncoder(self.siglip_bundle)
        self._siglip_enabled = False
        self._siglip_prompt_cache = None
        self._siglip_prompt_lock = threading.RLock()
        self._siglip_warmup_running = False

    def current_prompts(self):
        profile = getattr(self, "profile", None)
        if profile is None:
            return DEFAULT_TAG_PROMPTS
        try:
            snapshot = profile.snapshot()
            prompts = prompts_from_tags(snapshot.get("tags", []))
            return prompts or DEFAULT_TAG_PROMPTS
        except Exception:
            return DEFAULT_TAG_PROMPTS

    def enable_siglip(self) -> bool:
        if self._siglip_enabled and self.encoder.name == ENCODER_NAME:
            return True
        if not self.siglip_bundle.available() or not self.siglip_encoder.ready():
            return False
        self._siglip_enabled = True
        self.encoder = self.siglip_encoder
        self.invalidate_prototypes()
        self._siglip_prompt_cache = None
        return True

    def disable_siglip(self) -> None:
        self._siglip_enabled = False
        self._siglip_warmup_running = False
        self._siglip_prompt_cache = None
        self.siglip_encoder.unload_all()
        self.encoder = DEFAULT_ENCODER
        self.invalidate_prototypes()

    def refresh_encoder(self):
        if not self._siglip_enabled:
            return self.encoder
        if self.encoder.name != ENCODER_NAME:
            if not self.siglip_encoder.ready():
                disable_siglip(self)
                return self.encoder
            self.encoder = self.siglip_encoder
            self.invalidate_prototypes()
            self._siglip_prompt_cache = None
        return self.encoder

    def cached_prompt_vectors(self):
        prompts_map = current_prompts(self)
        result = {}
        missing: list[tuple[str, tuple[str, ...], str]] = []
        for tag, prompts in prompts_map.items():
            fingerprint = _prompt_hash(prompts)
            cached = self.index.text_vector(tag, ENCODER_NAME, fingerprint)
            if cached:
                result[tag] = cached
            else:
                missing.append((tag, prompts, fingerprint))
        return result, missing

    def build_prompt_vectors(self):
        if not self._siglip_enabled:
            return {}
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
                encoded = self.siglip_encoder.encode_texts(flat_prompts, batch_size=4)
                if len(encoded) != len(flat_prompts):
                    return result
                cursor = 0
                for (tag, _, fingerprint), count in zip(missing, group_sizes):
                    group = encoded[cursor : cursor + count]
                    cursor += count
                    vector = mean_vector(group)
                    if vector:
                        self.index.save_text_vector(tag, ENCODER_NAME, fingerprint, vector)
                        result[tag] = vector
            except InterruptedError:
                return result
            finally:
                self.siglip_encoder.unload_text()
            self._siglip_prompt_cache = result
            return result

    def warmup_worker(self):
        try:
            if self._siglip_enabled and SCHEDULER.wait_background_idle(self.stop, grace=4.0):
                build_prompt_vectors(self)
        except InterruptedError:
            pass
        except Exception as exc:
            with self.lock:
                self.last_error = f"SigLIP Prompt: {exc}"
        finally:
            with self._siglip_prompt_lock:
                self._siglip_warmup_running = False

    def start_prompt_warmup(self):
        if not self._siglip_enabled or SCHEDULER.busy() or not self.siglip_encoder.ready():
            return
        _, missing = cached_prompt_vectors(self)
        if not missing:
            return
        with self._siglip_prompt_lock:
            if self._siglip_warmup_running:
                return
            self._siglip_warmup_running = True
        threading.Thread(target=lambda: warmup_worker(self), name="LocalHubSiglipPrompts", daemon=True).start()

    def semantic_suggestions(self, path: str, limit: int = 6) -> dict:
        if not self._siglip_enabled:
            return original_suggestions(self, path, limit)
        refresh_encoder(self)
        if self.encoder.name != ENCODER_NAME:
            return original_suggestions(self, path, limit)
        vector = self.index.media_vector(path, ENCODER_NAME)
        if not vector:
            return {"ready": False, "items": [], "reason": "not-indexed"}
        frame_vectors = [row[2] for row in self.index.frame_vectors(path) if row[2]] or [vector]
        existing = {tag.casefold() for tag in self.store.tags_for(path)}
        feedback = {key.casefold(): value for key, value in self.index.feedback_for(path).items()}
        text_vectors = build_prompt_vectors(self)
        prompt_target = len(current_prompts(self))
        if len(text_vectors) < prompt_target and not SCHEDULER.busy():
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
            # Explicit positive evidence makes the learned prototype matter more;
            # explicit negative evidence is filtered above.
            if feedback.get(key) == 1 and prototype_score is not None:
                combined = combined * 0.65 + prototype_score * 0.35
            items.append({
                "tag": tag,
                "score": round(combined, 4),
                "semanticScore": round(semantic, 4),
                "prototypeScore": round(prototype_score, 4) if prototype_score is not None else None,
                "frames": len(frame_scores),
                "source": "siglip-zero-shot+prototype" if prototype_score is not None else "siglip-zero-shot",
            })
        items.sort(key=lambda row: row["score"], reverse=True)
        return {
            "ready": True,
            "items": items[: max(1, min(10, int(limit)))],
            "reason": "prompts-warming" if len(text_vectors) < prompt_target else "",
            "calibrated": False,
            "promptVectors": len(text_vectors),
            "promptTarget": prompt_target,
        }

    def status_with_siglip(self, path: str = ""):
        encoder_name = self.encoder.name
        semantic_active = bool(self._siglip_enabled and encoder_name == ENCODER_NAME)
        index_name = ENCODER_NAME if semantic_active else encoder_name
        index_stats = self.index.stats(index_name)
        model_status = self.siglip_bundle.status()
        model_status["enabled"] = semantic_active
        payload = original_status(self, path)
        payload.update({
            "encoder": encoder_name,
            "semanticModel": semantic_active,
            "aiEnabled": semantic_active,
            "indexed": index_stats["media"],
            "indexedFrames": index_stats["frames"],
            "model": model_status,
            "suggestionMode": "siglip-zero-shot" if semantic_active else "visual-prototype",
        })
        if path:
            payload["pathIndexed"] = self.index.has_media(path, ENCODER_NAME) if semantic_active else self.index.has_media(path, encoder_name)
        if semantic_active:
            cached, missing = cached_prompt_vectors(self)
            payload["promptVectors"] = len(cached)
            payload["promptTarget"] = len(current_prompts(self))
            payload["promptWarmup"] = self._siglip_warmup_running
            payload["promptMissing"] = len(missing)
        return payload

    def queue_with_siglip(self, path: str):
        enable_siglip(self)
        return original_queue_media(self, path)

    def start_library_with_siglip(self):
        enable_siglip(self)
        return original_start_library(self)

    Manager.__init__ = init_with_siglip
    Manager._enable_siglip = enable_siglip
    Manager._disable_siglip = disable_siglip
    Manager._refresh_siglip_encoder = refresh_encoder
    Manager._siglip_prompt_vectors = build_prompt_vectors
    Manager._start_siglip_prompt_warmup = start_prompt_warmup
    Manager._current_tag_prompts = current_prompts
    Manager.suggestions = semantic_suggestions
    Manager.status = status_with_siglip
    Manager.queue_media = queue_with_siglip
    Manager.start_library = start_library_with_siglip
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
        enhanced_html = base_html.replace("</head>",'  <link rel="stylesheet" href="/auto_tag_ui.css">\n  <link rel="stylesheet" href="/playback_stability.css">\n</head>',1).replace("</body>",'  <script src="/auto_tag_ui.js"></script>\n  <script src="/playback_stability.js"></script>\n</body>',1).encode("utf-8")
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
                    self.wfile.write(enhanced_html); return
                if parsed.path != "/api/auto-tag/model": return super().do_GET()
                manager = getattr(store, "_auto_tag_manager", None)
                if manager is None: return self._siglip_json({"ok":False,"error":"Auto Tag 尚未初始化"},HTTPStatus.SERVICE_UNAVAILABLE)
                payload = manager.siglip_bundle.status(); payload["enabled"] = bool(getattr(manager,"_siglip_enabled",False))
                return self._siglip_json({"ok":True,**payload})
            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/api/auto-tag/model": return super().do_POST()
                manager = getattr(store, "_auto_tag_manager", None)
                if manager is None: return self._siglip_json({"ok":False,"error":"Auto Tag 尚未初始化"},HTTPStatus.SERVICE_UNAVAILABLE)
                try:
                    data=self._read_json(); action=str(data.get("action","install"))
                    if action=="install": manager.siglip_bundle.start_install()
                    elif action=="enable": manager._enable_siglip()
                    elif action=="unload": manager._disable_siglip()
                    elif action=="refresh": manager._refresh_siglip_encoder()
                    else: raise ValueError("未知 SigLIP 模型操作")
                    payload=manager.siglip_bundle.status(); payload["enabled"]=bool(getattr(manager,"_siglip_enabled",False))
                    return self._siglip_json({"ok":True,**payload})
                except ValueError as exc:
                    return self._siglip_json({"ok":False,"error":str(exc)},HTTPStatus.BAD_REQUEST)
        return SiglipHandler
    server_module.make_handler = make_handler
