from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server
from smart_mode import Catalog


def touch(path: Path, size: int = 128) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        # Root videos must be preferred on Home.
        for i in range(5):
            touch(root / f"root-{i:02}.mp4", 500 + i)
        # Several folders give Home enough diversity to fill 13-15 slots.
        for folder in range(12):
            base = root / f"collection-{folder:02}"
            touch(base / f"video-{folder:02}.mp4", 800 + folder)
            # Mixed folder: images should collapse into one pack card.
            for image in range(6):
                touch(base / f"page_{image:03}.jpg", 1000 + image * 3)

        store = server.MediaStore(root)
        catalog = Catalog(store)
        assert catalog.ready.wait(10), "catalog did not become ready"

        home = catalog.home()
        assert 13 <= len(home) <= 15, len(home)
        assert all(item["kind"] == "video" for item in home)
        assert sum(1 for item in home if not item["folder"]) == 5

        folder = catalog.list_view("folder", "collection-00", limit=30)
        kinds = [item["kind"] for item in folder["items"]]
        assert kinds.count("video") == 1, kinds
        assert kinds.count("pack") == 1, kinds
        assert "image" not in kinds, kinds

        videos = catalog.list_view("videos", limit=30)
        assert videos["total"] == 17, videos["total"]
        assert len(videos["items"]) == 17

        found = catalog.list_view("search", q="collection-03", limit=30)
        assert found["total"] >= 1

        print("smart catalog smoke test passed")


if __name__ == "__main__":
    main()
