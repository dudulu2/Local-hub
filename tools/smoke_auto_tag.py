from __future__ import annotations

import hashlib
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
import ai_taxonomy_v2
import ai_settings_support
from ai_tag_sync_support import AITagReconciler
import siglip_encoder as siglip_module
from auto_tag_prompts import DEFAULT_TAG_PROMPTS
from io_scheduler import IOScheduler
from siglip_encoder import (
    ENCODER_NAME,
    HF_REVISION,
    LOCAL_PACKAGE_DIR,
    MODEL_FILES,
    MODEL_ID,
    MODEL_LICENSE,
    TOTAL_DOWNLOAD_BYTES,
    ModelFile,
    SiglipModelBundle,
)
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


def smoke_offline_install(tmp: Path, root: Path) -> None:
    original_rows = siglip_module.MODEL_FILES
    original_total = siglip_module.TOTAL_DOWNLOAD_BYTES
    old_localappdata = os.environ.get("LOCALAPPDATA")
    try:
        payloads = {
            "vision_model_int8.onnx": b"vision-localhub-test" * 31,
            "text_model_int8.onnx": b"text-localhub-test" * 37,
            "spiece.model": b"sentencepiece-localhub-test" * 7,
        }
        tiny_rows = tuple(
            ModelFile(name, name, len(data), hashlib.sha256(data).hexdigest())
            for name, data in payloads.items()
        )
        siglip_module.MODEL_FILES = tiny_rows
        siglip_module.TOTAL_DOWNLOAD_BYTES = sum(row.size for row in tiny_rows)

        package = root / LOCAL_PACKAGE_DIR
        package.mkdir(parents=True)
        for name, data in payloads.items():
            (package / name).write_bytes(data)

        appdata = tmp / "offline-install-appdata"
        os.environ["LOCALAPPDATA"] = str(appdata)
        bundle = SiglipModelBundle(root)
        before = bundle.status()
        assert before["installed"] is False
        assert before["localPackageAvailable"] is True
        assert before["source"] == "offline-package"

        bundle.start_install()
        assert bundle.thread is not None
        bundle.thread.join(timeout=5.0)
        assert not bundle.thread.is_alive()
        after = bundle.status()
        assert after["installed"] is True, after
        assert after["error"] == "", after
        assert after["downloadedBytes"] == siglip_module.TOTAL_DOWNLOAD_BYTES
        assert not package.exists(), "verified portable model package should be deleted after installation"
        assert (bundle.model_dir / "manifest.json").exists()
        assert bundle.ui_dismissed() is False
        bundle.set_ui_dismissed(True)
        assert bundle.ui_dismissed() is True
    finally:
        siglip_module.MODEL_FILES = original_rows
        siglip_module.TOTAL_DOWNLOAD_BYTES = original_total
        if old_localappdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old_localappdata


def main() -> None:
    # Professional built-ins all have enough semantic granularity for a useful
    # within-group competition. Old v1 settings upgrade without losing opt-ins.
    assert all(len(group["tags"]) >= 20 for group in ai_taxonomy_v2.PROFESSIONAL_GROUPS)
    migrated = ai_settings_support.normalize_settings({
        "version": 1,
        "aiOptIn": True,
        "groups": [{"id":"adult", "name":"色情", "enabled":True, "tags":[]}],
    })
    assert migrated["version"] == 2
    adult = next(group for group in migrated["groups"] if group["id"] == "adult")
    assert adult["enabled"] is True and len(adult["tags"]) >= 20

    grouped_settings = {"groups":[
        {"id":"entertainment","enabled":True,"tags":[{"tag":"直播"},{"tag":"播客"},{"tag":"访谈"},{"tag":"综艺"}]},
        {"id":"scenery","enabled":True,"tags":[{"tag":"海边"},{"tag":"山地"},{"tag":"森林"},{"tag":"雪景"}]},
    ]}
    picked = AITagReconciler._select(
        [("直播",.31),("播客",.282),("访谈",.274),("综艺",.268),("海边",.201),("山地",.199),("森林",.198),("雪景",.197)],
        grouped_settings,
    )
    assert "直播" in picked and not any(tag in picked for tag in {"海边","山地","森林","雪景"}), picked

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

    with tempfile.TemporaryDirectory(prefix="localhub-autotag-") as tmp_text:
        tmp = Path(tmp_text)
        root = tmp / "media"
        root.mkdir()
        index = VisualIndex(root)
        prompt_vector = tuple([1.0] + [0.0] * 767)
        index.save_text_vector("室内", ENCODER_NAME, "abc", prompt_vector)
        assert len(index.text_vector("室内", ENCODER_NAME, "abc")) == 768
        assert not index.text_vector("室内", ENCODER_NAME, "changed")

        # Runtime installation must work entirely from the package beside the EXE
        # and remove that package only after hashes have been verified.
        smoke_offline_install(tmp, root)

        # First verify the normal no-model state.
        old_localappdata = os.environ.get("LOCALAPPDATA")
        empty_appdata = tmp / "empty-appdata"
        os.environ["LOCALAPPDATA"] = str(empty_appdata)
        bundle = SiglipModelBundle(root)
        status = bundle.status()
        assert status["totalBytes"] == TOTAL_DOWNLOAD_BYTES == sum(row.size for row in MODEL_FILES)
        assert status["installed"] is False
        assert status["localPackageAvailable"] is False

        # Now emulate a fully installed model without loading any ONNX bytes.
        installed_appdata = tmp / "installed-appdata"
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
                ui_source = response.read()
                assert response.status == 200 and b"/api/io/activity" in ui_source
                assert b"LocalHub-AI-Model" in ui_source
                assert b"localhub_ai_hidden" in ui_source

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
            assert model["source"] == "offline-package"
        finally:
            httpd.shutdown()
            thread.join(timeout=2.0)
            httpd.server_close()
            if old_localappdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = old_localappdata

    print("low-risk Auto Tag offline explicit opt-in smoke test passed")


if __name__ == "__main__":
    main()
