from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import smart_thumbnail
import stable2_support


class FakeStore:
    def __init__(self, root: Path):
        self.root = root

    def resolve_media(self, relative: str) -> Path:
        target = (self.root / relative).resolve()
        target.relative_to(self.root.resolve())
        if not target.exists():
            raise FileNotFoundError(relative)
        return target


def row(prefix: str, idx: int, folder: str) -> dict:
    return {"id": f"{folder + '/' if folder else ''}{prefix}{idx}.mp4", "type": "video", "folder": folder}


def main() -> int:
    ux = (ROOT / "stable2_ux.js").read_text("utf-8")
    rec = (ROOT / "recommendation_ui.js").read_text("utf-8")
    preview = (ROOT / "preview_support.py").read_text("utf-8")
    player = (ROOT / "player_v4.js").read_text("utf-8")

    for marker in ("ArrowLeft", "ArrowRight", "/api/stable2/playback"):
        if marker not in ux:
            raise RuntimeError(f"Stable2 UX marker missing: {marker}")
    for marker in (
        "EXPANDED_KEY = 'localhub:tree-expanded-v1'",
        "DRAG_DWELL_MS = 800",
        "TEMP_COLLAPSE_MS = 8000",
        "lh-tree-expander",
        "lh-tree-open",
        "tempExpanded",
        "sourceButtons.get(row.path)?.click()",
        "sessionStorage.setItem(EXPANDED_KEY",
    ):
        if marker not in ux:
            raise RuntimeError(f"Stable3 tree marker missing: {marker}")
    for forbidden in ("ROOT_RESET_MS", "setLevel(path)", "lh-folder-tree-back"):
        if forbidden in ux:
            raise RuntimeError(f"obsolete level-switch navigation survived Stable3: {forbidden}")
    if "expander.addEventListener('click'" not in ux or "open.addEventListener('click'" not in ux:
        raise RuntimeError("tree expand and folder-open actions must be separate controls")
    if "tempExpanded.clear()" not in ux or "manualExpanded.clear()" in ux:
        raise RuntimeError("8-second cleanup must collapse only temporary drag expansion")

    for marker in ("/api/recommend/hover", "includeHover:true", "hover-previewing"):
        if marker not in rec:
            raise RuntimeError(f"recommendation cached-preview marker missing: {marker}")
    for marker in ("stable2_support.install_home_rotation", "/api/recommend/hover", "/api/stable2/warm", "persistentPreviewCache"):
        if marker not in preview:
            raise RuntimeError(f"Stable2 backend marker missing: {marker}")
    if "stable2" in player.casefold() or "stable3" in player.casefold():
        raise RuntimeError("Player V4 core must stay frozen for Stable2/Stable3 UX changes")

    roots = [row("root", i, "") for i in range(30)]
    others = [row("other", i, f"folder{i % 7}") for i in range(100)]
    first = stable2_support.select_home_items(roots, others, 15, random.Random(11))
    second = stable2_support.select_home_items(roots, others, 15, random.Random(12))
    if len(first) != 15 or len({x["id"] for x in first}) != 15:
        raise RuntimeError("home mix must contain 15 unique videos when enough media exists")
    if sum(1 for x in first if not x.get("folder")) > 5:
        raise RuntimeError("root videos exceeded one-third home quota")
    if [x["id"] for x in first] == [x["id"] for x in second]:
        raise RuntimeError("home mixes should rotate instead of using a fixed daily seed")

    small_root = roots[:2]
    mixed = stable2_support.select_home_items(small_root, others, 15, random.Random(20))
    if sum(1 for x in mixed if not x.get("folder")) != 2 or len(mixed) != 15:
        raise RuntimeError("small root pool should contribute fewer root videos and fill from the rest of the library")

    root_only = stable2_support.select_home_items(roots, [], 15, random.Random(30))
    if len(root_only) != 5:
        raise RuntimeError("root-only library must still respect the five-slot root cap")

    with tempfile.TemporaryDirectory(prefix="localhub-stable2-cache-") as tmp:
        root = Path(tmp)
        media = root / "sample.mp4"
        media.write_bytes(b"x" * 1024)
        manager = stable2_support.PersistentPreviewCache(FakeStore(root), smart_thumbnail, {".mp4"})
        try:
            cover = manager._cache_path(media)
            if cover is None:
                raise RuntimeError("cache path was not created")
            manager._write(cover, b"J" * 500)
            if manager.read_cover("sample.mp4") != b"J" * 500:
                raise RuntimeError("persistent cover cache read failed")
            old_name = cover.name
            time.sleep(0.01)
            media.write_bytes(b"y" * 2048)
            new_cover = manager._cache_path(media)
            if new_cover is None or new_cover.name == old_name:
                raise RuntimeError("cache identity did not invalidate after media changed")
        finally:
            manager.close()

    print("Stable3 tree UX + Stable2 cache/home smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
