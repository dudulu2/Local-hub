from __future__ import annotations

import tempfile
from pathlib import Path

import compat_support


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    js = (repo / "playback_stability.js").read_text("utf-8")
    css = (repo / "playback_stability.css").read_text("utf-8")

    assert "video.addEventListener('click'" in js
    assert "/api/compat/cancel" in js
    assert "hover-interactive" in js
    assert "lh-player-portrait" in js and "lh-player-portrait" in css

    with tempfile.TemporaryDirectory(prefix="localhub-ts-guard-") as tmp:
        root = Path(tmp)
        source = root / "large.ts"
        # Sparse file: validates the size guard without writing gigabytes.
        with source.open("wb") as fp:
            fp.seek(compat_support.LARGE_TS_BYTES + 1024)
            fp.write(b"\0")
        manager = compat_support.CompatManager(root)
        reason = manager._auto_block_reason(
            source,
            {"duration": 2.5 * 3600, "size": source.stat().st_size, "compatMode": "transcode"},
            "transcode",
        )
        assert reason and "系统播放器" in reason

    print("playback stability smoke test passed")


if __name__ == "__main__":
    main()
