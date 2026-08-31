from __future__ import annotations

import json
import tempfile
import threading
import urllib.request
from pathlib import Path

import launcher


def get_json(url: str):
    with launcher.local_urlopen(url, timeout=5.0) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict):
    request = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with launcher.local_urlopen(request, timeout=5.0) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    httpd = None
    with tempfile.TemporaryDirectory(prefix="localhub-ai-center-") as tmp:
        root = Path(tmp)
        httpd, port = launcher.create_http_server(root)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        assert launcher.wait_health(base, 5.0)

        with launcher.local_urlopen(base + "/", timeout=5.0) as response:
            html = response.read().decode("utf-8")
        assert "/ai_center.js" in html
        assert "/ai_center.css" in html

        overview = get_json(base + "/api/ai/overview")
        assert overview["ok"] is True
        assert overview["settings"]["backgroundMode"] == "balanced"
        names = [group["name"] for group in overview["settings"]["groups"]]
        for expected in ("全部视频", "生活", "学习", "风景", "娱乐", "色情"):
            assert expected in names
        adult = next(group for group in overview["settings"]["groups"] if group["name"] == "色情")
        assert adult["enabled"] is False

        settings = overview["settings"]
        settings["backgroundMode"] = "idle"
        settings["groups"][1]["tags"].append({
            "tag": "测试分类",
            "prompts": ["A test semantic video category."],
        })
        saved = post_json(base + "/api/ai/settings", {"action": "save", "settings": settings})
        assert saved["ok"] is True
        assert saved["settings"]["backgroundMode"] == "idle"
        assert any(row["tag"] == "测试分类" for row in saved["settings"]["groups"][1]["tags"])

        reset = post_json(base + "/api/ai/settings", {"action": "reset"})
        assert reset["ok"] is True
        assert reset["settings"]["backgroundMode"] == "balanced"

        import auto_tag_support
        assert getattr(auto_tag_support.AutoTagManager, "_localhub_ai_center_patched", False) is True

        httpd.shutdown()
        thread.join(timeout=2.0)
        httpd.server_close()
        httpd = None

    print("AI center smoke test: OK")


if __name__ == "__main__":
    main()
