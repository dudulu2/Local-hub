from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "build_tools" / "localhub-media-engine.exe"
PLAYER = ROOT / "player_v4.js"


def local_open(url: str, headers: dict[str, str] | None = None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers=headers or {})
    return opener.open(request, timeout=4)


def main() -> int:
    if not ENGINE.exists():
        raise RuntimeError(f"missing media engine: {ENGINE}")
    text = PLAYER.read_text("utf-8")
    for marker in ("/direct", "/transcode.mp4", "localhubOffset", "200", "videojs.use"):
        if marker not in text:
            raise RuntimeError(f"player V4 marker missing: {marker}")

    with tempfile.TemporaryDirectory(prefix="localhub-v4-smoke-") as tmp:
        root = Path(tmp)
        payload = bytes(range(64)) * 16
        media = root / "range-test.mp4"
        media.write_bytes(payload)

        kwargs = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process = subprocess.Popen(
            [str(ENGINE), "--root", str(root), "--ffmpeg", "ffmpeg", "--port", "0"],
            **kwargs,
        )
        try:
            assert process.stdout is not None
            line = process.stdout.readline().strip()
            data = json.loads(line)
            port = int(data["port"])
            base = f"http://127.0.0.1:{port}"

            with local_open(base + "/health") as response:
                health = json.loads(response.read().decode("utf-8"))
                if health.get("ok") is not True:
                    raise RuntimeError("media engine health failed")

            url = base + "/direct?path=range-test.mp4"
            with local_open(url, {"Range": "bytes=5-12"}) as response:
                body = response.read()
                if response.status != 206:
                    raise RuntimeError(f"Range request returned {response.status}")
                if body != payload[5:13]:
                    raise RuntimeError("Range payload mismatch")
                if response.headers.get("Accept-Ranges") != "bytes":
                    raise RuntimeError("Accept-Ranges header missing")
        finally:
            try:
                if process.stdin:
                    process.stdin.close()
            except Exception:
                pass
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    print("Player V4 smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
