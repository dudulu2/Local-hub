from __future__ import annotations

import gc
import hashlib
import io
import json
import os
import re
import string
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps, ImageStat

from visual_encoder import EncodedFrame, mean_vector, normalize

MODEL_ID = "siglip-base-patch16-224-int8"
ENCODER_NAME = "siglip-base-patch16-224-int8-v1"
HF_REVISION = "4649052661e53c7000355844105f8a1792088239"
HF_REPO = "Xenova/siglip-base-patch16-224"
MODEL_LICENSE = "Apache-2.0 (base model: google/siglip-base-patch16-224)"
IMAGE_SIZE = 224
TEXT_LENGTH = 64
EMBED_DIM = 768


@dataclass(frozen=True)
class ModelFile:
    name: str
    remote_path: str
    size: int
    sha256: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{HF_REPO}/resolve/{HF_REVISION}/{self.remote_path}?download=true"


MODEL_FILES = (
    ModelFile(
        "vision_model_int8.onnx",
        "onnx/vision_model_int8.onnx",
        94_098_316,
        "6d00762fcb4aef9bdee1b886fcccc7df466f9eae321e180f97d88e24fa13ac72",
    ),
    ModelFile(
        "text_model_int8.onnx",
        "onnx/text_model_int8.onnx",
        110_982_746,
        "9cb5102160e2a2b90c0a999ed6c2b4090865c9d5aa08f09cd10993ad9b38bd5f",
    ),
    ModelFile(
        "spiece.model",
        "spiece.model",
        798_330,
        "1e5036bed065526c3c212dfbe288752391797c4bb1a284aa18c9a0b23fcaf8ec",
    ),
)
TOTAL_DOWNLOAD_BYTES = sum(row.size for row in MODEL_FILES)


class SiglipModelBundle:
    """External model bundle with explicit opt-in download and SHA256 verification."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.model_dir = root / ".localhub" / "models" / MODEL_ID
        self.marker = self.model_dir / "manifest.json"
        self.lock = threading.RLock()
        self.installing = False
        self.downloaded_bytes = 0
        self.total_bytes = TOTAL_DOWNLOAD_BYTES
        self.error = ""
        self.current_file = ""
        self.thread: threading.Thread | None = None

    def file_path(self, name: str) -> Path:
        return self.model_dir / name

    def _marker_valid(self) -> bool:
        try:
            data = json.loads(self.marker.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if data.get("revision") != HF_REVISION:
            return False
        for row in MODEL_FILES:
            path = self.file_path(row.name)
            try:
                if path.stat().st_size != row.size:
                    return False
            except OSError:
                return False
            if data.get("sha256", {}).get(row.name) != row.sha256:
                return False
        return True

    def available(self) -> bool:
        return self._marker_valid()

    def status(self) -> dict:
        with self.lock:
            installed = self.available()
            return {
                "id": MODEL_ID,
                "encoder": ENCODER_NAME,
                "installed": installed,
                "installing": self.installing,
                "downloadedBytes": int(self.downloaded_bytes),
                "totalBytes": int(self.total_bytes),
                "currentFile": self.current_file,
                "error": self.error,
                "license": MODEL_LICENSE,
                "source": f"{HF_REPO}@{HF_REVISION[:12]}",
                "directory": str(self.model_dir),
            }

    def start_install(self) -> None:
        with self.lock:
            if self.installing or self.available():
                return
            self.installing = True
            self.downloaded_bytes = 0
            self.error = ""
            self.current_file = ""
            self.thread = threading.Thread(target=self._install_worker, name="LocalHubSiglipInstall", daemon=True)
            self.thread.start()

    def _existing_valid(self, row: ModelFile) -> bool:
        path = self.file_path(row.name)
        try:
            if path.stat().st_size != row.size:
                return False
        except OSError:
            return False
        digest = hashlib.sha256()
        try:
            with path.open("rb") as fp:
                while True:
                    chunk = fp.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError:
            return False
        return digest.hexdigest().lower() == row.sha256

    def _download(self, row: ModelFile) -> None:
        target = self.file_path(row.name)
        if self._existing_valid(row):
            with self.lock:
                self.downloaded_bytes += row.size
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + ".part")
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        request = urllib.request.Request(row.url, headers={"User-Agent": "LocalHub/2.4 AutoTag"})
        digest = hashlib.sha256()
        written = 0
        with urllib.request.urlopen(request, timeout=45) as response, part.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                with self.lock:
                    self.downloaded_bytes += len(chunk)
        if written != row.size:
            raise RuntimeError(f"{row.name} 下载大小不一致：{written} != {row.size}")
        actual = digest.hexdigest().lower()
        if actual != row.sha256:
            raise RuntimeError(f"{row.name} SHA256 校验失败")
        os.replace(part, target)

    def _install_worker(self) -> None:
        try:
            self.model_dir.mkdir(parents=True, exist_ok=True)
            for row in MODEL_FILES:
                with self.lock:
                    self.current_file = row.name
                self._download(row)
            marker = {
                "model": MODEL_ID,
                "base": "google/siglip-base-patch16-224",
                "onnx": HF_REPO,
                "revision": HF_REVISION,
                "license": MODEL_LICENSE,
                "sha256": {row.name: row.sha256 for row in MODEL_FILES},
                "installedAt": int(time.time() * 1000),
            }
            temp = self.marker.with_suffix(".tmp")
            temp.write_text(json.dumps(marker, ensure_ascii=False, indent=2), "utf-8")
            os.replace(temp, self.marker)
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
        finally:
            with self.lock:
                self.installing = False
                self.current_file = ""


class SiglipOnnxEncoder:
    """SigLIP Base Patch16-224 INT8 using ONNX Runtime, without PyTorch."""

    name = ENCODER_NAME
    semantic = True

    def __init__(self, bundle: SiglipModelBundle) -> None:
        self.bundle = bundle
        self.lock = threading.RLock()
        self._vision = None
        self._text = None
        self._sp = None
        self._np = None
        self._ort = None

    def ready(self) -> bool:
        if not self.bundle.available():
            return False
        try:
            import numpy  # noqa: F401
            import onnxruntime  # noqa: F401
            import sentencepiece  # noqa: F401
            return True
        except Exception:
            return False

    def _deps(self):
        if self._np is None or self._ort is None:
            try:
                import numpy as np
                import onnxruntime as ort
            except Exception as exc:
                raise RuntimeError(f"SigLIP 运行依赖不可用: {exc}") from exc
            self._np = np
            self._ort = ort
        return self._np, self._ort

    def _session_options(self):
        _, ort = self._deps()
        options = ort.SessionOptions()
        # Auto Tag is background work. One inference thread keeps playback and
        # browser work responsive even on machines with few CPU cores.
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        return options

    def _vision_session(self):
        with self.lock:
            if self._vision is None:
                if not self.bundle.available():
                    raise RuntimeError("SigLIP 模型尚未安装")
                _, ort = self._deps()
                self._vision = ort.InferenceSession(
                    str(self.bundle.file_path("vision_model_int8.onnx")),
                    sess_options=self._session_options(),
                    providers=["CPUExecutionProvider"],
                )
            return self._vision

    def _text_session(self):
        with self.lock:
            if self._text is None:
                if not self.bundle.available():
                    raise RuntimeError("SigLIP 模型尚未安装")
                _, ort = self._deps()
                self._text = ort.InferenceSession(
                    str(self.bundle.file_path("text_model_int8.onnx")),
                    sess_options=self._session_options(),
                    providers=["CPUExecutionProvider"],
                )
            return self._text

    @staticmethod
    def _pick_embedding(outputs) -> tuple[float, ...]:
        for value in outputs:
            shape = getattr(value, "shape", ())
            if len(shape) == 2 and shape[-1] == EMBED_DIM:
                return normalize(value[0].tolist())
        raise RuntimeError("SigLIP ONNX 没有返回预期的 768 维 pooler_output")

    def encode_jpeg(self, data: bytes) -> EncodedFrame | None:
        try:
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image = image.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BICUBIC)
                gray = image.convert("L").resize((64, 64), Image.Resampling.BILINEAR)
                quality = min(1.0, (ImageStat.Stat(gray).stddev[0] / 64.0))
                np, _ = self._deps()
                pixels = np.asarray(image, dtype=np.float32) / 255.0
                pixels = (pixels - 0.5) / 0.5
                pixels = np.transpose(pixels, (2, 0, 1))[None, ...]
        except Exception:
            return None
        session = self._vision_session()
        inputs = session.get_inputs()
        if not inputs:
            return None
        try:
            outputs = session.run(None, {inputs[0].name: pixels})
            return EncodedFrame(self._pick_embedding(outputs), quality)
        except Exception:
            return None

    def _sentencepiece(self):
        with self.lock:
            if self._sp is None:
                try:
                    import sentencepiece as spm
                except Exception as exc:
                    raise RuntimeError(f"SentencePiece 不可用: {exc}") from exc
                processor = spm.SentencePieceProcessor()
                if not processor.Load(str(self.bundle.file_path("spiece.model"))):
                    raise RuntimeError("无法读取 SigLIP spiece.model")
                self._sp = processor
            return self._sp

    @staticmethod
    def _canonicalize(text: str) -> str:
        text = str(text or "").lower()
        text = text.translate(str.maketrans("", "", string.punctuation))
        return re.sub(r"\s+", " ", text).strip()

    def _tokenize(self, text: str):
        np, _ = self._deps()
        sp = self._sentencepiece()
        canonical = self._canonicalize(text)
        unk = "<unk>"
        unk_len = len(sp.encode(unk, out_type=int))
        ids = list(sp.encode(unk + canonical, out_type=int))
        if len(ids) >= unk_len:
            ids = ids[unk_len:]
        eos = 1
        if len(ids) >= TEXT_LENGTH:
            ids = ids[: TEXT_LENGTH - 1]
        if not ids or ids[-1] != eos:
            ids.append(eos)
        real = len(ids)
        if len(ids) < TEXT_LENGTH:
            ids.extend([eos] * (TEXT_LENGTH - len(ids)))
        mask = [1] * real + [0] * (TEXT_LENGTH - real)
        return np.asarray(ids, dtype=np.int64), np.asarray(mask, dtype=np.int64)

    def encode_texts(self, texts: Iterable[str], batch_size: int = 12) -> list[tuple[float, ...]]:
        rows = [str(text) for text in texts]
        if not rows:
            return []
        np, _ = self._deps()
        session = self._text_session()
        input_defs = session.get_inputs()
        results: list[tuple[float, ...]] = []
        for start in range(0, len(rows), max(1, int(batch_size))):
            batch = rows[start : start + max(1, int(batch_size))]
            tokens = [self._tokenize(text) for text in batch]
            ids = np.stack([row[0] for row in tokens], axis=0)
            masks = np.stack([row[1] for row in tokens], axis=0)
            feed = {}
            for item in input_defs:
                if item.name == "input_ids" or not feed:
                    feed[item.name] = ids
                elif "attention" in item.name:
                    feed[item.name] = masks
                elif "position" in item.name:
                    feed[item.name] = np.tile(np.arange(TEXT_LENGTH, dtype=np.int64), (len(batch), 1))
            outputs = session.run(None, feed)
            embedding_array = None
            for value in outputs:
                shape = getattr(value, "shape", ())
                if len(shape) == 2 and shape[-1] == EMBED_DIM:
                    embedding_array = value
                    break
            if embedding_array is None:
                raise RuntimeError("SigLIP text ONNX 没有返回预期的 768 维 pooler_output")
            for vector in embedding_array:
                results.append(normalize(vector.tolist()))
        return results

    def encode_prompt_group(self, prompts: Iterable[str]) -> tuple[float, ...]:
        return mean_vector(self.encode_texts(prompts))

    def unload_text(self) -> None:
        with self.lock:
            self._text = None
            self._sp = None
        gc.collect()

    def unload_all(self) -> None:
        with self.lock:
            self._vision = None
            self._text = None
            self._sp = None
        gc.collect()
