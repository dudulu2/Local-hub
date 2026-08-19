from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "2.2.4-timeline1"


def main() -> None:
    version = (ROOT / "VERSION").read_text("utf-8").strip()
    assert version == EXPECTED, (version, EXPECTED)

    win = (ROOT / "version_info.txt").read_text("utf-8")
    assert "filevers=(2, 2, 4, 0)" in win
    assert "prodvers=(2, 2, 4, 0)" in win
    assert "FileVersion', '2.2.4-timeline1'" in win
    assert "ProductVersion', '2.2.4-timeline1'" in win
    assert "Timeline Repair" in win

    notes = (ROOT / "RELEASE_NOTES.md").read_text("utf-8")
    assert notes.startswith("# LocalHub 2.2.4 RC4")

    move = (ROOT / "move_branding.js").read_text("utf-8")
    for required in (
        "LONG_PRESS_MS = 500",
        "LONG_PRESS_SLOP = 30",
        "card.draggable = false",
        "img.draggable = false",
        "folderBackBtn",
        "await api('/api/smart/rescan')",
        "location.reload()",
    ):
        assert required in move, required
    assert "setPointerCapture" not in move

    spec = (ROOT / "LocalHub.spec").read_text("utf-8")
    assert "launcher_mse.py" in spec
    assert "mse_ui.js" in spec
    assert "repair_ui.js" in spec

    launcher = (ROOT / "launcher_mse.py").read_text("utf-8")
    assert "mse_support.install(server)" in launcher
    assert "repair_support.install(server)" in launcher
    assert "repair_page_support.install(server)" in launcher

    mse = (ROOT / "mse_support.py").read_text("utf-8")
    assert "_MP4_HEALTH_SCRIPT" not in mse
    assert "COMPLETE_READY_BYTES" in mse
    assert 'status == "ready" and size > COMPLETE_READY_BYTES' in mse
    assert "|mse2" in mse

    repair = (ROOT / "repair_support.py").read_text("utf-8")
    for required in (
        '"-c:v", "libx264"',
        '"-fps_mode", "cfr"',
        "fps=",
        "setpts=N/(\",
        "aresample=async=1:first_pts=0",
        "/api/repair/file",
    ):
        assert required in repair, required

    repair_ui = (ROOT / "repair_ui.js").read_text("utf-8")
    for required in ("修复播放", "/api/repair/start", "/api/repair/status", "修复播放已接管"):
        assert required in repair_ui, required

    page = (ROOT / "repair_page_support.py").read_text("utf-8")
    assert '<script src="/repair_ui.js"></script>' in page

    stale = list(ROOT.glob("tools/.alpha*-anchor")) + list(ROOT.glob("tools/.alpha*-placeholder"))
    assert not stale, stale

    print(f"experiment metadata smoke test passed ({EXPECTED})")


if __name__ == "__main__":
    main()
