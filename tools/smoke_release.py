from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "2.2.4-rc1"


def main() -> None:
    version = (ROOT / "VERSION").read_text("utf-8").strip()
    assert version == EXPECTED, (version, EXPECTED)

    win = (ROOT / "version_info.txt").read_text("utf-8")
    assert "filevers=(2, 2, 4, 0)" in win
    assert "prodvers=(2, 2, 4, 0)" in win
    assert "FileVersion', '2.2.4-rc1'" in win
    assert "ProductVersion', '2.2.4-rc1'" in win

    notes = (ROOT / "RELEASE_NOTES.md").read_text("utf-8")
    assert notes.startswith("# LocalHub 2.2.4 RC1")
    for required in (
        "播放优先级",
        "统一视频比例",
        "本地推荐",
        "TS 兼容播放",
        "批量 TS → MP4",
    ):
        assert required in notes, required

    # Release candidates must not accidentally ship one of the temporary CI
    # anchor files used while iterating on the alpha branches.
    stale = list(ROOT.glob("tools/.alpha*-anchor")) + list(ROOT.glob("tools/.alpha*-placeholder"))
    assert not stale, stale

    print(f"release metadata smoke test passed ({EXPECTED})")


if __name__ == "__main__":
    main()
