from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import compat_support
import media_probe


def main() -> None:
    js = (ROOT / "playback_stability.js").read_text("utf-8")
    css = (ROOT / "playback_stability.css").read_text("utf-8")
    smart = (ROOT / "smart_ui.js").read_text("utf-8")
    probe_source = (ROOT / "media_probe.py").read_text("utf-8")

    # The enhancement layer may observe playback, but smart_ui.js is the only
    # front-end owner of source selection / compatibility startup.
    assert "video.addEventListener('click'" in js
    assert "/api/compat/cancel" in js
    assert "hover-interactive" in js
    assert "lh-player-portrait" in js and "lh-player-portrait" in css
    assert "video.addEventListener('stalled'" in js and "video.addEventListener('waiting'" in js
    assert "/api/media/probe" not in js, "playback enhancement must not run a second probe chain"
    assert "startForcedTranscode" not in js, "watchdog must not auto-start hidden transcoding"
    assert "GATED_EXTS" not in js, "enhancement layer must not gate/remove smart_ui sources"
    assert "video.removeAttribute('src')" not in js, "enhancement layer must never clear the current source"
    assert "video.src =" not in js, "enhancement layer must never replace the current source"
    assert "async function getProbe(item)" in smart and "async function startCompatibility" in smart
    assert "_PROBE_EXECUTOR = threading.BoundedSemaphore(1)" in probe_source

    # A nominal H.264 MP4 with no reliable frame-rate metadata must not be sent
    # straight into Chromium by the media strategy.
    risks = media_probe._timeline_risks(
        ext=".mp4",
        text="",
        width=1920,
        height=1080,
        duration=120.0,
        fps=None,
        fps_source="",
    )
    assert "无法确认可靠帧率" in risks
    strategy, mode, _ = media_probe._strategy(".mp4", "h264", "aac", timeline_risk=True)
    assert strategy == "compat" and mode == "transcode"

    # AVI/MPG/TS never use a plain H.264 stream copy: that can preserve broken
    # DTS/PTS and reproduce the frame-bouncing failure.
    legacy_strategy, legacy_mode, _ = media_probe._strategy(".avi", "h264", "mp3", timeline_risk=False)
    assert legacy_strategy == "compat" and legacy_mode == "transcode"

    with tempfile.TemporaryDirectory(prefix="localhub-ts-guard-") as tmp:
        root = Path(tmp)
        source = root / "large.ts"
        with source.open("wb") as fp:
            fp.seek(compat_support.LARGE_TS_BYTES + 1024)
            fp.write(b"\0")
        manager = compat_support.CompatManager(root)
        reason = manager._auto_block_reason(
            source,
            {"ok": True, "duration": 2.5 * 3600, "size": source.stat().st_size, "compatMode": "transcode"},
            "transcode",
        )
        assert reason and "系统播放器" in reason

        long_mpg = root / "long.mpg"
        long_mpg.write_bytes(b"x")
        legacy_reason = manager._auto_block_reason(
            long_mpg,
            {"ok": True, "duration": 87 * 60, "size": 800_000_000, "compatMode": "transcode"},
            "transcode",
        )
        assert legacy_reason and "系统播放器" in legacy_reason

    print("playback stability smoke test passed")


if __name__ == "__main__":
    main()
