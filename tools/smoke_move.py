from __future__ import annotations

import tempfile
from pathlib import Path

from server import MediaStore
from smart_mode import Catalog


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "A").mkdir()
        (root / "B").mkdir()
        source = root / "A" / "sample.mp4"
        source.write_bytes(b"localhub-move-smoke")

        store = MediaStore(root)
        catalog = Catalog(store)
        catalog.ready.wait(5)
        assert "A/sample.mp4" in catalog.by_id

        moved = store.move(["A/sample.mp4"], "B", create=False)
        assert moved == [{"old": "A/sample.mp4", "new": "B/sample.mp4"}], moved
        assert not source.exists()
        assert (root / "B" / "sample.mp4").is_file()

        catalog.refresh(wait=True)
        assert "A/sample.mp4" not in catalog.by_id
        assert "B/sample.mp4" in catalog.by_id
        home_ids = [item["id"] for item in catalog.home()]
        assert home_ids == ["B/sample.mp4"], home_ids

    js = (Path(__file__).resolve().parents[1] / "move_branding.js").read_text("utf-8")
    assert "await api('/api/smart/rescan')" in js
    assert "松开即取消" in js
    assert "点击目标文件夹" not in js
    print("move smoke test passed")


if __name__ == "__main__":
    main()
