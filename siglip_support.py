from __future__ import annotations

import hashlib
import json
import statistics
import urllib.parse
from http import HTTPStatus

from auto_tag_prompts import DEFAULT_TAG_PROMPTS
from siglip_encoder import ENCODER_NAME, SiglipModelBundle, SiglipOnnxEncoder
from visual_encoder import cosine


def _prompt_hash(prompts: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(prompts).encode("utf-8")).hexdigest()


def _install_manager_patch(auto_tag_support_module) -> None:
    Manager = auto_tag_support_module.AutoTagManager
    if getattr(Manager, "_localhub_siglip_patched", False):
        return

    original_init = Manager.__init__
    original_status = Manager.status
    original_suggestions = Manager.suggestions
    original_queue_media = Manager.queue_media

    def init_with_siglip(self, store):
        original_init(self, store)
        self.siglip_bundle = SiglipModelBundle(store.root)
        self.siglip_encoder = SiglipOnnxEncoder(self.siglip_bundle)
        self._siglip_prompt_cache = None
        if self.siglip_encoder.ready():
            self.encoder = self.siglip_encoder

    def refresh_encoder(self):
        if self.siglip_encoder.ready() and self.encoder.name != ENCODER_NAME:
            try:
                self.encoder.unload_all()
            except Exception:
                pass
            self.encoder = self.siglip_encoder
            self.invalidate_prototypes()
            self._siglip_prompt_cache = None
        return self.encoder

    def prompt_vectors(self):
        refresh_encoder(self)
        if self.encoder.name != ENCODER_NAME:
            return {}
        if self._siglip_prompt_cache is not None:
            return self._siglip_prompt_cache

        result = {}
        missing: list[tuple[str, tuple[str, ...], str]] = []
        for tag, prompts in DEFAULT_TAG_PROMPTS.items():
            fingerprint = _prompt_hash(prompts)
            cached = self.index.text_vector(tag, ENCODER_NAME, fingerprint)
            if cached:
                result[tag] = cached
            else:
                missing.append((tag, prompts, fingerprint))

        try:
            for tag, prompts, fingerprint in missing:
                vector = self.siglip_encoder.encode_prompt_group(prompts)
                if vector:
                    self.index.save_text_vector(tag, ENCODER_NAME, fingerprint, vector)
                    result[tag] = vector
        finally:
            # The text tower is ~111 MB on disk and is only needed when prompts
            # change. Release its session immediately after vectors are cached.
            self.siglip_encoder.unload_text()

        self._siglip_prompt_cache = result
        return result

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
        text_vectors = prompt_vectors(self)
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

        # User-specific tags that are not part of the fixed zero-shot prompt set
        # can still be learned from confirmed positive examples.
        for key, row in prototypes.items():
            if key in existing or feedback.get(key) == -1 or row["tag"] in text_vectors:
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

        # These are ranking scores, not calibrated probabilities. v1 never
        # auto-writes tags; the user confirms or rejects suggestions.
        items.sort(key=lambda row: row["score"], reverse=True)
        return {"ready": True, "items": items[: max(1, min(10, int(limit)))], "reason": "", "calibrated": False}

    def status_with_siglip(self, path: str = ""):
        refresh_encoder(self)
        payload = original_status(self, path)
        payload["encoder"] = self.encoder.name
        payload["semanticModel"] = self.encoder.name == ENCODER_NAME
        payload["model"] = self.siglip_bundle.status()
        payload["suggestionMode"] = "siglip-zero-shot" if payload["semanticModel"] else "visual-prototype"
        return payload

    def queue_with_siglip(self, path: str):
        refresh_encoder(self)
        return original_queue_media(self, path)

    Manager.__init__ = init_with_siglip
    Manager._refresh_siglip_encoder = refresh_encoder
    Manager._siglip_prompt_vectors = prompt_vectors
    Manager.suggestions = semantic_suggestions
    Manager.status = status_with_siglip
    Manager.queue_media = queue_with_siglip
    Manager._localhub_siglip_patched = True


def install(server_module, auto_tag_support_module) -> None:
    _install_manager_patch(auto_tag_support_module)
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
