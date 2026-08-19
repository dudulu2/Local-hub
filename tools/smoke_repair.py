from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import media_probe
import repair_support


def make_problem_like(exe: str, path: Path) -> None:
    cmd = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "testsrc2=size=720x480:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=44100",
        "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-y", str(path),
    ]
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30, check=False)
    assert r.returncode == 0 and path.exists(), r.stderr.decode("utf-8", "replace")


def wait(manager: repair_support.RepairManager, job_id: str) -> dict:
    end = time.monotonic() + 35
    while time.monotonic() < end:
        row = manager.status(job_id)
        assert row
        if row["status"] in {"ready", "error"}:
            return row
        time.sleep(.08)
    raise AssertionError("repair timeout")


def main() -> None:
    exe = media_probe.ffmpeg_exe()
    assert exe and Path(exe).exists()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        src = root / "sample.mp4"
        make_problem_like(exe, src)
        manager = repair_support.RepairManager(root)
        started = manager.start(src)
        assert abs(float(started["fps"]) - 24.0) < .2, started
        done = wait(manager, started["id"])
        assert done["status"] == "ready", done
        out = manager.file(started["id"])
        assert out and out.exists() and out.stat().st_size > 1024
        probe = media_probe.probe_media(out)
        assert probe["ok"] and probe["videoCodec"] == "h264", probe
        assert abs(float(probe.get("fps") or 0) - 24.0) < .3, probe

    backend = (ROOT / "repair_support.py").read_text("utf-8")
    ui = (ROOT / "repair_ui.js").read_text("utf-8")
    for required in ("fps=", "setpts=N/(", '"-fps_mode", "cfr"', '"-c:v", "libx264"', "aresample=async=1:first_pts=0"):
        assert required in backend, required
    for required in ("修复播放", "/api/repair/start", "/api/repair/status", "修复播放已接管"):
        assert required in ui, required
    print("timeline repair experiment smoke test passed")


if __name__ == "__main__":
    main()
