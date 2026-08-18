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


def make_video(exe: str, path: Path, codec: str, fmt_args: list[str] | None = None) -> None:
    command = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12",
        "-t", "3", "-an", "-c:v", codec,
    ]
    if codec == "libx264":
        command += ["-pix_fmt", "yuv420p"]
    if fmt_args:
        command += fmt_args
    command += ["-y", str(path)]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=25, check=False)
    assert result.returncode == 0 and path.exists(), result.stderr.decode("utf-8", "replace")


def make_ts(exe: str, path: Path) -> None:
    command = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
        "-t", "6",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "mpegts", "-y", str(path),
    ]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30, check=False)
    assert result.returncode == 0 and path.exists() and path.stat().st_size > 4096, result.stderr.decode("utf-8", "replace")


def wait_job(manager: compat_support.CompatManager, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = manager.status(job_id)
        assert row is not None
        if row.get("backgroundStatus") in {"ready", "error"}:
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
        transport = root / "transport.ts"
        make_video(exe, native, "libx264")
        make_video(exe, legacy, "mpeg2video")
        make_video(exe, mov, "libx264")
        make_ts(exe, transport)

        p_native = media_probe.probe_media(native)
        p_legacy = media_probe.probe_media(legacy)
        p_mov = media_probe.probe_media(mov)
        p_ts = media_probe.probe_media(transport)
        assert p_native["ok"] and p_native["videoCodec"] == "h264", p_native
        assert p_native["strategy"] == "native", p_native
        assert p_legacy["strategy"] == "compat" and p_legacy["compatMode"] == "transcode", p_legacy
        assert p_mov["compatMode"] == "remux", p_mov
        assert p_ts["ok"] and p_ts["videoCodec"] == "h264", p_ts
        assert p_ts["strategy"] == "compat" and p_ts["compatMode"] == "remux", p_ts

        # Client-visible fast-start behavior: once a fragmented TS remux has
        # enough data, the existing UI should receive a playable stream URL even
        # though the background job is still working.
        partial = root / "partial.mp4"
        partial.write_bytes(b"0" * compat_support.STREAM_READY_BYTES)
        fake = compat_support.CompatJob(
            job_id="faststart",
            source=transport,
            output=partial,
            mode="remux",
            source_size=transport.stat().st_size,
            status="working",
        )
        fast = fake.public()
        assert fast["status"] == "ready" and fast["backgroundStatus"] == "working", fast
        assert fast["streaming"] is True and "/api/compat/stream?id=faststart" in fast["url"], fast

        manager = compat_support.CompatManager(root)
        first = manager.start(legacy)
        result = wait_job(manager, first["id"])
        assert result["backgroundStatus"] == "ready", result
        out = manager.output_for(first["id"])
        assert out and out.exists() and out.stat().st_size > 1024
        converted = media_probe.probe_media(out)
        assert converted["videoCodec"] == "h264", converted

        second = manager.start(mov, "remux")
        result2 = wait_job(manager, second["id"])
        assert result2["backgroundStatus"] == "ready" and result2["mode"] == "remux", result2

        third = manager.start(transport)
        assert third["mode"] == "remux", third
        result3 = wait_job(manager, third["id"])
        assert result3["backgroundStatus"] == "ready" and result3["mode"] == "remux", result3
        ts_out = manager.output_for(third["id"])
        assert ts_out and ts_out.exists() and ts_out.stat().st_size > 4096
        raw = ts_out.read_bytes()
        assert b"moof" in raw, "TS output is not fragmented MP4"
        ts_probe = media_probe.probe_media(ts_out)
        assert ts_probe["ok"] and ts_probe["videoCodec"] == "h264", ts_probe
        assert ts_probe["strategy"] == "native", ts_probe

    print("compatibility playback smoke test passed")


if __name__ == "__main__":
    main()