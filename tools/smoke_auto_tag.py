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
from siglip_encoder import ENCODER_NAME, HF_REVISION, MODEL_FILES, MODEL_ID, MODEL_LICENSE, TOTAL_DOWNLOAD_BYTES, SiglipModelBundle
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


def fake_installed_bundle(base: Path) -> Path:
    model_dir = base / "LocalHub" / "models" / MODEL_ID
    model_dir.mkdir(parents=True, exist_ok=True)
    for row in MODEL_FILES:
        path = model_dir / row.name
        with path.open("wb") as fp:
            if row.size:
                fp.seek(row.size - 1)
                fp.write(b"\0")
    marker = {
        "model": MODEL_ID,
        "base": "google/siglip-base-patch16-224",
        "onnx": "Xenova/siglip-base-patch16-224",
        "revision": HF_REVISION,
        "license": MODEL_LICENSE,
        "sha256": {row.name: row.sha256 for row in MODEL_FILES},
        "installedAt": 1,
    }
    (model_dir / "manifest.json").write_text(json.dumps(marker), "utf-8")
    return model_dir


def main() -> None:
    scheduler = IOScheduler()
    assert not scheduler.busy()
    scheduler.note(playing=True)
    assert scheduler.busy()
    scheduler.note(playing=False, seeking=False)
    assert not scheduler.busy()

    image = Image.new("RGB", (320, 180), (90, 120, 160))
    stream = io.BytesIO()
    image.save(stream, "JPEG", quality=80)
    encoded = FingerprintEncoder().encode_jpeg(stream.getvalue())
    assert encoded and encoded.vector

    with tempfile.TemporaryDirectory(prefix="localhub-autotag-") as tmp:
        root = Path(tmp) / "media"
        root.mkdir()
        index = VisualIndex(root)
        prompt_vector = tuple([1.0] + [0.0] * 767)
        index.save_text_vector("室内", ENCODER_NAME, "abc", prompt_vector)
        assert len(index.text_vector("室内", ENCODER_NAME, "abc")) == 768
        assert not index.text_vector("室内", ENCODER_NAME, "changed")

        # First verify the normal no-model state.
        old_localappdata = os.environ.get("LOCALAPPDATA")
        empty_appdata = Path(tmp) / "empty-appdata"
        os.environ["LOCALAPPDATA"] = str(empty_appdata)
        bundle = SiglipModelBundle(root)
        status = bundle.status()
        assert status["totalBytes"] == TOTAL_DOWNLOAD_BYTES == sum(row.size for row in MODEL_FILES)
        assert status["installed"] is False

        # Now emulate a fully installed model without loading any ONNX bytes.
        installed_appdata = Path(tmp) / "installed-appdata"
        fake_installed_bundle(installed_appdata)
        os.environ["LOCALAPPDATA"] = str(installed_appdata)

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
            assert auto["model"]["installed"] is True
            assert auto["semanticModel"] is False, "installed model must not auto-enable"
            assert auto["aiEnabled"] is False, "opening/status polling must not start SigLIP"
            assert auto["model"]["enabled"] is False
            assert auto["libraryRunning"] is False
            assert auto.get("current", "") == ""
            assert not auto.get("promptWarmup", False), "prompt warmup must require explicit AI action"
            assert len(DEFAULT_TAG_PROMPTS) >= 8

            active = request_json(base, "/api/io/activity", {"playing": True, "seeking": False})
            assert active["playing"] is True
            preview = request_json(base, "/api/smart/preview-status")
            assert preview["pausedForPlayback"] is True
            request_json(base, "/api/io/activity", {"playing": False, "seeking": False})

            model = request_json(base, "/api/auto-tag/model")
            assert model["installed"] is True
            assert model["enabled"] is False
            assert model["totalBytes"] == TOTAL_DOWNLOAD_BYTES
        finally:
            httpd.shutdown()
            thread.join(timeout=2.0)
            httpd.server_close()
            if old_localappdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = old_localappdata

    print("low-risk Auto Tag explicit opt-in smoke test passed")


if __name__ == "__main__":
    main()
