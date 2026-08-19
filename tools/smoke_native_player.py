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
    assert version == "2.3.0-alpha1", version

    launcher = (ROOT / "launcher_native.py").read_text("utf-8")
    ui = (ROOT / "native_player_ui.js").read_text("utf-8")
    spec = (ROOT / "LocalHub.spec").read_text("utf-8")

    for required in (
        "webview.create_window",
        "player_api.attach(window)",
        "window.evaluate_js(script)",
        "libmpv",
    ):
        assert required in launcher, required

    for required in (
        "player_load",
        "player_rect",
        "player_seek",
        "player_volume",
        "player_speed",
        "Native · libmpv",
        ".card[data-id]",
        ".video-thumb",
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

    print("native player source smoke passed")


if __name__ == "__main__":
    main()
