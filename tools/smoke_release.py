from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "2.2.4-rc3"


def main() -> None:
    version = (ROOT / "VERSION").read_text("utf-8").strip()
    assert version == EXPECTED, (version, EXPECTED)

    win = (ROOT / "version_info.txt").read_text("utf-8")
    assert "filevers=(2, 2, 4, 0)" in win
    assert "prodvers=(2, 2, 4, 0)" in win
    assert "FileVersion', '2.2.4-rc3'" in win
    assert "ProductVersion', '2.2.4-rc3'" in win

    notes = (ROOT / "RELEASE_NOTES.md").read_text("utf-8")
    assert notes.startswith("# LocalHub 2.2.4 RC3")
    for required in (
        "播放优先级",
        "统一视频比例",
        "本地推荐",
        "TS 兼容播放",
        "长按移动",
        "首页",
        "批量 TS → MP4",
    ):
        assert required in notes, required

    move = (ROOT / "move_branding.js").read_text("utf-8")
    for required in (
        "LONG_PRESS_MS = 480",
        "setPointerCapture",
        "pointerdown",
        "pointermove",
        "pointerup",
        "await api('/api/smart/rescan')",
        "location.reload()",
        "松开即取消",
        "#moveModeBtn,#rescanBtn,#viewerMoveBtn{display:none!important}",
    ):
        assert required in move, required
    assert "点击目标文件夹" not in move

    stale = list(ROOT.glob("tools/.alpha*-anchor")) + list(ROOT.glob("tools/.alpha*-placeholder"))
    assert not stale, stale

    print(f"release metadata smoke test passed ({EXPECTED})")


if __name__ == "__main__":
    main()
