from __future__ import annotations

import io
import threading
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from io_scheduler import SCHEDULER
from visual_encoder import EncodedFrame


_lock = threading.RLock()
_modes: dict[str, str] = {}


def set_mode(root: Path, mode: str) -> None:
    clean = "idle" if str(mode) == "idle" else "balanced"
    with _lock:
        _modes[str(Path(root).resolve()).casefold()] = clean


def get_mode(root: Path) -> str:
    with _lock:
        return _modes.get(str(Path(root).resolve()).casefold(), "balanced")


def install() -> None:
    import siglip_encoder as module

    Encoder = module.SiglipOnnxEncoder
    if getattr(Encoder, "_localhub_balanced_playback_patched", False):
        return
    original = Encoder.encode_jpeg

    def encode_jpeg(self, data: bytes):
        if get_mode(self.bundle.root) != "balanced":
            return original(self, data)

        # In balanced mode normal playback is allowed. A seek/scrub remains a
        # hard priority boundary because timeline responsiveness matters more
        # than finishing a background embedding.
        if SCHEDULER.snapshot().get("seeking"):
            return None
        try:
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image = image.resize((module.IMAGE_SIZE, module.IMAGE_SIZE), Image.Resampling.BICUBIC)
                gray = image.convert("L").resize((64, 64), Image.Resampling.BILINEAR)
                quality = min(1.0, (ImageStat.Stat(gray).stddev[0] / 64.0))
                np, _ = self._deps()
                pixels = np.asarray(image, dtype=np.float32) / 255.0
                pixels = (pixels - 0.5) / 0.5
                pixels = np.transpose(pixels, (2, 0, 1))[None, ...]
        except Exception:
            return None
        if SCHEDULER.snapshot().get("seeking"):
            return None

        # siglip_encoder already configures ONNX Runtime with one intra-op
        # thread, one inter-op thread and sequential execution. We deliberately
        # reuse those sessions rather than introducing a second inference path.
        session = self._vision_session()
        inputs = session.get_inputs()
        if not inputs:
            return None
        try:
            outputs = session.run(None, {inputs[0].name: pixels})
            if SCHEDULER.snapshot().get("seeking"):
                return None
            return EncodedFrame(self._pick_embedding(outputs), quality)
        except Exception:
            return None

    Encoder.encode_jpeg = encode_jpeg
    Encoder._localhub_balanced_playback_patched = True


install()
