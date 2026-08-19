from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import native_player


def main() -> None:
    version = (ROOT / "VERSION").read_text("utf-8").strip()
    assert version == "2.3.0-alpha2", version

    launcher = (ROOT / "launcher_native.py").read_text("utf-8")
    player = (ROOT / "native_player.py").read_text("utf-8")
    ui = (ROOT / "native_player_ui.js").read_text("utf-8")
    spec = (ROOT / "LocalHub.spec").read_text("utf-8")

    for required in (
        "webview.create_window",
        "player_api.attach(window)",
        "window.evaluate_js(script)",
        'webview.start(gui="edgechromium"',
        "shutdown(wait=False)",
    ):
        assert required in launcher, required

    # Alpha2 regression: merely showing the home page must not create a native
    # video surface or initialize libmpv. Both happen lazily after player_load.
    attach_block = player.split("def attach(self, window)", 1)[1].split("def _ui", 1)[0]
    assert "WinForms.Panel" not in attach_block
    assert "LibMpv(" not in attach_block
    assert "native surface remains lazy" in attach_block
    assert "def _ensure_surface_async" in player
    assert "self._ensure_surface_async()" in player
    assert "target=self._worker_main" in player
    assert 'self._set_option("hwdec", "no")' in player
    assert "daemon=True" in player
    assert "WORKER_STALL_SECONDS" in player
    assert "surfacePending" in player

    for required in (
        "player_load",
        "player_rect",
        "player_seek",
        "player_volume",
        "player_speed",
        "Native · libmpv",
        ".card[data-id]",
        ".video-thumb",
        "主界面不会等待播放器初始化",
    ):
        assert required in ui, required

    for required in (
        "launcher_native.py",
        "native_player_ui.js",
        "vendor/libmpv-2.dll",
        "collect_all('webview')",
    ):
        assert required in spec, required

    dll = os.environ.get("LOCALHUB_LIBMPV_DLL", "").strip()
    if dll:
        ok, detail = native_player.self_test(dll)
        assert ok, detail
        print(f"libmpv load/create smoke passed: {detail}")
    else:
        print("libmpv binary smoke skipped (LOCALHUB_LIBMPV_DLL not set)")

    print("native player alpha2 lazy-surface source smoke passed")


if __name__ == "__main__":
    main()
