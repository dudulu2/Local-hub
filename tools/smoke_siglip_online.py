from __future__ import annotations

import io
import math
import os
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from siglip_encoder import EMBED_DIM, LOCAL_PACKAGE_DIR, MODEL_FILES, SiglipModelBundle, SiglipOnnxEncoder
from tools.prepare_siglip_bundle import download
from visual_encoder import cosine


def norm(vector) -> float:
    return math.sqrt(sum(float(x) * float(x) for x in vector))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="localhub-siglip-offline-real-") as tmp:
        temp = Path(tmp)
        if os.name == "nt":
            os.environ["LOCALAPPDATA"] = str(temp / "localapp")
        media_root = temp / "media"
        media_root.mkdir()

        # Network access is used only to prepare the distributor-side portable
        # package. The runtime installation itself must consume local files only.
        package = media_root / LOCAL_PACKAGE_DIR
        package.mkdir()
        for row in MODEL_FILES:
            download(row, package / row.name)

        bundle = SiglipModelBundle(media_root)
        assert bundle.status()["localPackageAvailable"] is True
        bundle.start_install()
        assert bundle.thread is not None
        bundle.thread.join(timeout=480)
        status = bundle.status()
        assert not status["installing"], "model install did not finish"
        assert status["installed"], status.get("error") or status
        assert not package.exists(), "portable package must be removed after verified install"

        encoder = SiglipOnnxEncoder(bundle)
        assert encoder.ready(), "onnxruntime/sentencepiece model runtime is not ready"

        # Synthetic but non-uniform frame: runtime/input/output compatibility is
        # the purpose of this smoke, not semantic accuracy benchmarking.
        image = Image.new("RGB", (320, 180))
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                pixels[x, y] = (40 + x * 180 // image.width, 70 + y * 140 // image.height, 180)
        stream = io.BytesIO()
        image.save(stream, "JPEG", quality=88)
        frame = encoder.encode_jpeg(stream.getvalue())
        assert frame is not None and len(frame.vector) == EMBED_DIM
        assert abs(norm(frame.vector) - 1.0) < 1e-3

        texts = encoder.encode_texts([
            "This is an indoor scene.",
            "This is an outdoor scene.",
            "This is a photo of one person.",
        ])
        assert len(texts) == 3
        for vector in texts:
            assert len(vector) == EMBED_DIM
            assert abs(norm(vector) - 1.0) < 1e-3
        scores = [cosine(frame.vector, vector) for vector in texts]
        assert all(math.isfinite(value) and -1.0 <= value <= 1.0 for value in scores)

        encoder.unload_all()
        print("SigLIP offline-package smoke passed; cosine scores:", [round(value, 4) for value in scores])


if __name__ == "__main__":
    main()
