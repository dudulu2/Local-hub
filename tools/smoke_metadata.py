from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server
import smart_mode
import rating_support


def main() -> None:
    rating_support.install(server, smart_mode)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        media = root / "demo.mp4"
        media.write_bytes(b"0" * 2048)
        store = server.MediaStore(root)

        store.set_tags(["demo.mp4"], ["人物"], mode="replace")
        store.set_tags(["demo.mp4"], ["室内"], mode="add")
        assert store.tags_for("demo.mp4") == ["人物", "室内"], store.tags_for("demo.mp4")

        store.set_rating("demo.mp4", 4)
        rows = store.scan()
        assert rows[0]["rating"] == 4, rows[0]

        moved = store.rename("demo.mp4", "renamed")
        assert moved["new"] == "renamed.mp4", moved
        assert store.tags_for("renamed.mp4") == ["人物", "室内"]
        assert store.rating_for("renamed.mp4") == 4

        store.set_tags(["renamed.mp4"], ["人物"], mode="remove")
        assert store.tags_for("renamed.mp4") == ["室内"]

    print("metadata UX smoke test passed")


if __name__ == "__main__":
    main()
