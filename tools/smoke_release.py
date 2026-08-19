from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "2.2.4-rc4"


def main() -> None:
    version = (ROOT / "VERSION").read_text("utf-8").strip()
    assert version == EXPECTED, (version, EXPECTED)

    win = (ROOT / "version_info.txt").read_text("utf-8")
    assert "filevers=(2, 2, 4, 0)" in win
    assert "prodvers=(2, 2, 4, 0)" in win
    assert "FileVersion', '2.2.4-rc4'" in win
    assert "ProductVersion', '2.2.4-rc4'" in win

    notes = (ROOT / "RELEASE_NOTES.md").read_text("utf-8")
    assert notes.startswith("# LocalHub 2.2.4 RC4")
    for required in (
        "播放优先级",
        "统一视频比例",
        "本地推荐",
        "TS 兼容播放",
        "长按移动",
        "上一级",
        "MP4 时间轴",
        "批量 TS → MP4",
    ):
        assert required in notes, required

    move = (ROOT / "move_branding.js").read_text("utf-8")
    for required in (
        "LONG_PRESS_MS = 500",
        "LONG_PRESS_SLOP = 30",
        "card.draggable = false",
        "img.draggable = false",
        "pointerdown",
        "pointermove",
        "pointerup",
        "folderBackBtn",
        "await api('/api/smart/rescan')",
        "location.reload()",
        "#moveModeBtn,#rescanBtn,#viewerMoveBtn{display:none!important}",
    ):
        assert required in move, required
    assert "setPointerCapture" not in move

    preview = (ROOT / "preview_support.py").read_text("utf-8")
    assert "_MP4_HEALTH_SCRIPT" in preview
    assert "backwardHits.length>=2" in preview
    assert "compatMode!=='remux'" in preview

    stale = list(ROOT.glob("tools/.alpha*-anchor")) + list(ROOT.glob("tools/.alpha*-placeholder"))
    assert not stale, stale

    print(f"release metadata smoke test passed ({EXPECTED})")


if __name__ == "__main__":
    main()
