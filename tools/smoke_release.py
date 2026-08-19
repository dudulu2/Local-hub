from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "2.2.4-mse1"


def main() -> None:
    version = (ROOT / "VERSION").read_text("utf-8").strip()
    assert version == EXPECTED, (version, EXPECTED)

    win = (ROOT / "version_info.txt").read_text("utf-8")
    assert "filevers=(2, 2, 4, 0)" in win
    assert "prodvers=(2, 2, 4, 0)" in win
    assert "FileVersion', '2.2.4-mse1'" in win
    assert "ProductVersion', '2.2.4-mse1'" in win
    assert "MSE1" in win

    # The experiment intentionally keeps RC4 release notes unchanged; it is not
    # a release candidate and must not be confused with a stable release.
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
    launcher = (ROOT / "launcher_mse.py").read_text("utf-8")
    assert "mse_support.install(server)" in launcher

    mse = (ROOT / "mse_support.py").read_text("utf-8")
    assert "new MediaSource()" not in mse  # browser implementation stays in mse_ui.js
    assert "_MP4_HEALTH_SCRIPT" not in mse
    assert "preview_support._PLAYBACK_PRIORITY_SCRIPT" in mse
    assert "preview_support._PORTRAIT_LAYOUT_SCRIPT" in mse

    ui = (ROOT / "mse_ui.js").read_text("utf-8")
    for required in ("new MediaSource()", "MediaSource.isTypeSupported", "addSourceBuffer", "appendBuffer", "MSE 试播"):
        assert required in ui, required

    stale = list(ROOT.glob("tools/.alpha*-anchor")) + list(ROOT.glob("tools/.alpha*-placeholder"))
    assert not stale, stale

    print(f"experiment metadata smoke test passed ({EXPECTED})")


if __name__ == "__main__":
    main()
