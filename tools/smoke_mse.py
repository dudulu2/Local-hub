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
import mse_support


def make_h264(exe: str, path: Path) -> None:
    command = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
        "-t", "4", "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-g", "24", "-keyint_min", "24",
        "-y", str(path),
    ]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0 and path.exists(), result.stderr.decode("utf-8", "replace")


def wait_job(manager: mse_support.MSEManager, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = manager.status(job_id)
        assert row is not None
        if row.get("status") in {"ready", "error"}:
            return row
        time.sleep(0.08)
    raise AssertionError("MSE job timeout")


def main() -> None:
    exe = media_probe.ffmpeg_exe()
    assert exe and Path(exe).exists(), "ffmpeg missing"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        source = root / "sample.mp4"
        make_h264(exe, source)
        probe = media_probe.probe_media(source)
        assert probe.get("videoCodec") == "h264", probe

        manager = mse_support.MSEManager(root)
        started = manager.start(source)
        result = wait_job(manager, started["id"])
        assert result["status"] == "ready", result
        assert result["streamReady"] is True, result
        output = root / ".localhub" / "mse" / f"{started['id']}.mse.mp4"
        raw = output.read_bytes()
        assert raw.find(b"ftyp") >= 0
        assert raw.find(b"moov") >= 0
        assert raw.find(b"moof") >= 0
        assert raw.find(b"mdat") >= 0
        assert raw.find(b"moov") < raw.find(b"moof"), "init segment must precede media fragments"

        # Regression: a completed short clip must be readable even when its
        # total fMP4 output is below the streaming 64 KiB head-start threshold.
        tiny = root / ".localhub" / "mse" / "tiny.mse.mp4"
        tiny.parent.mkdir(parents=True, exist_ok=True)
        tiny.write_bytes(b"0" * (mse_support.COMPLETE_READY_BYTES + 1))
        tiny_job = mse_support.MSEJob(
            job_id="tiny",
            source=source,
            output=tiny,
            status="ready",
        )
        tiny_public = tiny_job.public()
        assert tiny_public["streamReady"] is True, tiny_public
        assert tiny_public["url"] and "/api/mse/stream?id=tiny" in tiny_public["url"]

    backend = (ROOT / "mse_support.py").read_text("utf-8")
    ui = (ROOT / "mse_ui.js").read_text("utf-8")
    for required in (
        '"-use_editlist", "0"',
        '"-video_track_timescale", "90000"',
        '"+frag_keyframe+empty_moov+default_base_moof+dash"',
        'preview_support._PLAYBACK_PRIORITY_SCRIPT',
        'preview_support._PORTRAIT_LAYOUT_SCRIPT',
        'COMPLETE_READY_BYTES',
    ):
        assert required in backend, required
    assert "_MP4_HEALTH_SCRIPT" not in backend, "experiment must not auto-remux MP4 before A/B test"
    for required in (
        "new MediaSource()",
        "MediaSource.isTypeSupported",
        "addSourceBuffer",
        "appendBuffer",
        "avcC",
        "MSE 试播",
        "MSE 正在准备",
        "MSE 试播失败",
        "nextPath !== activePath",
    ):
        assert required in ui, required
    assert "if (jobId && currentPath())" not in ui

    print("MSE2 fragmented MP4 experiment smoke test passed")


if __name__ == "__main__":
    main()
