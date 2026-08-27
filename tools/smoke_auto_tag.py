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
from auto_tag_prompts import DEFAULT_TAG_PROMPTS, STARTER_TAG_PACKS
from auto_tag_profile import AutoTagProfile
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
        request = launcher.urllib.request.Request(url,data=raw,method="POST",headers={"Content-Type":"application/json","Content-Length":str(len(raw))})
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
                fp.seek(row.size - 1); fp.write(b"\0")
    marker = {"model":MODEL_ID,"base":"google/siglip-base-patch16-224","onnx":"Xenova/siglip-base-patch16-224","revision":HF_REVISION,"license":MODEL_LICENSE,"sha256":{row.name:row.sha256 for row in MODEL_FILES},"installedAt":1}
    (model_dir / "manifest.json").write_text(json.dumps(marker), "utf-8")
    return model_dir


def main() -> None:
    scheduler = IOScheduler(); assert not scheduler.busy(); scheduler.note(playing=True); assert scheduler.busy(); scheduler.note(playing=False,seeking=False); assert not scheduler.busy()
    image = Image.new("RGB", (320,180), (90,120,160)); stream=io.BytesIO(); image.save(stream,"JPEG",quality=80)
    encoded=FingerprintEncoder().encode_jpeg(stream.getvalue()); assert encoded and encoded.vector

    assert {"gaming","life","film","footage","learning","adult","all","custom"}.issubset(STARTER_TAG_PACKS)
    assert STARTER_TAG_PACKS["adult"]["label"] == "成人内容"
    assert STARTER_TAG_PACKS["all"]["label"] == "全部视频"

    with tempfile.TemporaryDirectory(prefix="localhub-autotag-") as tmp:
        root=Path(tmp)/"media"; root.mkdir()
        profile=AutoTagProfile(root)
        assert profile.snapshot()["configured"] is False
        adult=profile.select_pack("adult"); assert adult["configured"] is True and adult["packId"] == "adult" and len(adult["tags"]) >= 10
        edited=profile.update(tags=[{"tag":"Boss战","description":"只包括正式 Boss 战"},{"tag":"高光","description":"值得保留的精彩片段"}])
        assert [row["tag"] for row in edited["tags"]] == ["Boss战","高光"]
        assert AutoTagProfile(root).snapshot()["tags"][0]["description"] == "只包括正式 Boss 战"

        index=VisualIndex(root); prompt_vector=tuple([1.0]+[0.0]*767); index.save_text_vector("室内",ENCODER_NAME,"abc",prompt_vector); assert len(index.text_vector("室内",ENCODER_NAME,"abc"))==768
        old_localappdata=os.environ.get("LOCALAPPDATA"); empty_appdata=Path(tmp)/"empty-appdata"; os.environ["LOCALAPPDATA"]=str(empty_appdata)
        bundle=SiglipModelBundle(root); status=bundle.status(); assert status["totalBytes"]==TOTAL_DOWNLOAD_BYTES==sum(row.size for row in MODEL_FILES); assert status["installed"] is False
        installed_appdata=Path(tmp)/"installed-appdata"; fake_installed_bundle(installed_appdata); os.environ["LOCALAPPDATA"]=str(installed_appdata)

        # Reset profile to first-use state for API checks.
        (root/".localhub"/"auto-tag-profile.json").unlink(missing_ok=True)
        (root/"sample.mp4").write_bytes(b"not-a-real-video")
        httpd,port=launcher.create_http_server(root); thread=threading.Thread(target=httpd.serve_forever,kwargs={"poll_interval":0.05},daemon=True); thread.start(); base=f"http://127.0.0.1:{port}"
        try:
            assert launcher.wait_health(base,5.0)
            profile_api=request_json(base,"/api/auto-tag/profile")
            assert profile_api["ok"] and profile_api["profile"]["configured"] is False
            labels={row["label"] for row in profile_api["packs"]}; assert "成人内容" in labels and "全部视频" in labels
            selected=request_json(base,"/api/auto-tag/profile",{"action":"select-pack","packId":"gaming"}); assert selected["profile"]["packId"]=="gaming"
            updated=request_json(base,"/api/auto-tag/profile",{"action":"update","tags":[{"tag":"Boss","description":"只标正式 Boss"},{"tag":"探索","description":"地图探索"}],"configured":True})
            assert updated["profile"]["tags"][0]["description"]=="只标正式 Boss"
            feedback=request_json(base,"/api/auto-tag/feedback-v2",{"path":"sample.mp4","tag":"Boss","value":-1}); assert feedback["rematchPending"]>=1
            rematch=request_json(base,"/api/auto-tag/rematch",{}); assert rematch["count"]>=1
            new_media=request_json(base,"/api/auto-tag/new-media"); assert "sample.mp4" in new_media["paths"]
            auto=request_json(base,"/api/auto-tag/status"); assert auto["ok"] is True and auto["model"]["installed"] is True and auto["semanticModel"] is False and auto["aiEnabled"] is False
            assert len(DEFAULT_TAG_PROMPTS)>=8
        finally:
            httpd.shutdown(); thread.join(timeout=2.0); httpd.server_close()
            if old_localappdata is None: os.environ.pop("LOCALAPPDATA",None)
            else: os.environ["LOCALAPPDATA"]=old_localappdata

    print("Auto Tag V2 starter-pack/profile/learning smoke test passed")


if __name__ == "__main__":
    main()
