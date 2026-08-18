from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import compat_support
import media_probe


def make_video(exe: str, path: Path, codec: str, fmt_args: list[str] | None = None, size: str = "320x180") -> None:
    command = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=12",
        "-t", "3", "-an", "-c:v", codec,
    ]
    if codec == "libx264":
        command += ["-pix_fmt", "yuv420p"]
    if fmt_args:
        command += fmt_args
    command += ["-y", str(path)]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=25, check=False)
    assert result.returncode == 0 and path.exists(), result.stderr.decode("utf-8", "replace")


def wait_job(manager: compat_support.CompatManager, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = manager.status(job_id)
        assert row is not None
        if row["status"] in {"ready", "error"}:
            return row
        time.sleep(0.1)
    raise AssertionError("compat job timeout")


def main() -> None:
    exe = media_probe.ffmpeg_exe()
    assert exe and Path(exe).exists(), "ffmpeg missing"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        native = root / "native.mp4"
        legacy = root / "legacy.mpg"
        mov = root / "indexed.mov"
        portrait = root / "portrait.mov"
        make_video(exe, native, "libx264")
        make_video(exe, legacy, "mpeg2video")
        make_video(exe, mov, "libx264")
        make_video(exe, portrait, "libx264", size="180x320")

        p_native = media_probe.probe_media(native)
        p_legacy = media_probe.probe_media(legacy)
        p_mov = media_probe.probe_media(mov)
        p_portrait = media_probe.probe_media(portrait)
        assert p_native["ok"] and p_native["videoCodec"] == "h264", p_native
        assert p_native["strategy"] == "native", p_native
        assert p_legacy["strategy"] == "compat" and p_legacy["compatMode"] == "transcode", p_legacy
        assert p_mov["compatMode"] == "remux", p_mov
        assert p_portrait["displayWidth"] == 180 and p_portrait["displayHeight"] == 320, p_portrait

        manager = compat_support.CompatManager(root)
        first = manager.start(legacy)
        result = wait_job(manager, first["id"])
        assert result["status"] == "ready", result
        out = manager.output_for(first["id"])
        assert out and out.exists() and out.stat().st_size > 1024
        converted = media_probe.probe_media(out)
        assert converted["videoCodec"] == "h264", converted

        second = manager.start(mov, "remux")
        result2 = wait_job(manager, second["id"])
        assert result2["status"] == "ready" and result2["mode"] == "remux", result2

        portrait_job = manager.start(portrait, "remux")
        portrait_result = wait_job(manager, portrait_job["id"])
        assert portrait_result["status"] == "ready" and portrait_result["mode"] == "remux", portrait_result
        portrait_out = manager.output_for(portrait_job["id"])
        assert portrait_out and portrait_out.exists()
        portrait_probe = media_probe.probe_media(portrait_out)
        assert portrait_probe["displayWidth"] == 180 and portrait_probe["displayHeight"] == 320, portrait_probe

    print("compatibility playback smoke test passed")


if __name__ == "__main__":
    main()
