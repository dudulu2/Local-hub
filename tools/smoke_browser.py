from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import launcher


def find_edge() -> Path | None:
    found = shutil.which("msedge")
    if found:
        return Path(found)
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((p for p in candidates if p.exists()), None)


def main() -> None:
    if os.name != "nt":
        print("browser smoke test skipped outside Windows")
        return
    edge = find_edge()
    assert edge and edge.exists(), "Microsoft Edge not found on Windows runner"

    httpd = None
    with tempfile.TemporaryDirectory(prefix="localhub-browser-") as tmp:
        root = Path(tmp)
        try:
            httpd, port = launcher.create_http_server(root)
            thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            assert launcher.wait_health(f"http://127.0.0.1:{port}", 5.0), "LocalHub HTTP health check failed"
            profile = root / "edge-profile"
            cmd = [
                str(edge),
                "--headless=new",
                "--disable-gpu",
                "--disable-extensions",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=3000",
                "--dump-dom",
                f"http://127.0.0.1:{port}/",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=15, check=False)
            assert result.returncode == 0, result.stderr[-2000:]
            dom = result.stdout
            assert "LocalHub" in dom and 'id="pageTitle"' in dom, "homepage did not render"
            assert "正在建立索引" not in dom or "首页" in dom, "homepage JS did not finish initial render"
            assert 'data-interaction-fix="2.4-probe-failfast"' in dom, "probe fail-fast interaction layer did not execute in Edge"
        finally:
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
    print("real Edge homepage smoke test passed")


if __name__ == "__main__":
    main()
