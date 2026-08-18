from __future__ import annotations

import io
import json
import os
import tempfile
import threading
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import launcher
from auto_tag_prompts import DEFAULT_TAG_PROMPTS
from io_scheduler import IOScheduler
from siglip_encoder import ENCODER_NAME, MODEL_FILES, TOTAL_DOWNLOAD_BYTES, SiglipModelBundle
from visual_encoder import FingerprintEncoder
from visual_index import VisualIndex


def request_json(base: str, path: str, payload: dict | None = None) -> dict:
    url = base + path
    if payload is None:
        request = launcher.urllib.request.Request(url)
    else:
        raw = json.dumps(payload).encode("utf-8")
        request = launcher.urllib.request.Request(
            url,
            data=raw,
            method="POST",
            headers={"Content-Type": "application/json", "Content-Length": str(len(raw))},
        )
    with launcher.local_urlopen(request, timeout=5.0) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    # Scheduler is TTL based and must release background work explicitly.
    scheduler = IOScheduler()
    assert not scheduler.busy()
    scheduler.note(playing=True)
    assert scheduler.busy()
    scheduler.note(playing=False, seeking=False)
    assert not scheduler.busy()

    # The fallback encoder/index remain usable without any model download.
    image = Image.new("RGB", (320, 180), (90, 120, 160))
    stream = io.BytesIO()
    image.save(stream, "JPEG", quality=80)
    encoded = FingerprintEncoder().encode_jpeg(stream.getvalue())
    assert encoded and encoded.vector

    with tempfile.TemporaryDirectory(prefix="localhub-autotag-") as tmp:
        root = Path(tmp)
        index = VisualIndex(root)
        prompt_vector = tuple([1.0] + [0.0] * 767)
        index.save_text_vector("室内", ENCODER_NAME, "abc", prompt_vector)
        assert len(index.text_vector("室内", ENCODER_NAME, "abc")) == 768
        assert not index.text_vector("室内", ENCODER_NAME, "changed")

        bundle = SiglipModelBundle(root)
        status = bundle.status()
        assert status["totalBytes"] == TOTAL_DOWNLOAD_BYTES == sum(row.size for row in MODEL_FILES)
        assert status["installed"] is False, "CI must not depend on a preinstalled model"
        if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
            assert root not in bundle.model_dir.parents, "model weights must not live inside a synced media root"

        httpd, port = launcher.create_http_server(root)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        try:
            assert launcher.wait_health(base, 5.0)
            with launcher.local_urlopen(base + "/", timeout=5.0) as response:
                html = response.read().decode("utf-8")
                assert "/auto_tag_ui.css" in html and "/auto_tag_ui.js" in html
            with launcher.local_urlopen(base + "/auto_tag_ui.js", timeout=5.0) as response:
                assert response.status == 200 and b"/api/io/activity" in response.read()

            auto = request_json(base, "/api/auto-tag/status")
            assert auto["ok"] is True
            assert auto["semanticModel"] is False
            assert auto["model"]["installed"] is False
            assert auto["libraryRunning"] is False, "Auto Tag must be opt-in"
            assert len(DEFAULT_TAG_PROMPTS) >= 8

            active = request_json(base, "/api/io/activity", {"playing": True, "seeking": False})
            assert active["playing"] is True
            preview = request_json(base, "/api/smart/preview-status")
            assert preview["pausedForPlayback"] is True
            request_json(base, "/api/io/activity", {"playing": False, "seeking": False})

            model = request_json(base, "/api/auto-tag/model")
            assert model["installed"] is False
            assert model["totalBytes"] == TOTAL_DOWNLOAD_BYTES
        finally:
            httpd.shutdown()
            thread.join(timeout=2.0)
            httpd.server_close()

    print("low-risk Auto Tag smoke test passed")


if __name__ == "__main__":
    main()
