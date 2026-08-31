from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import catalog_cache
import server
import smart_mode

catalog_cache.install(smart_mode)
Catalog = smart_mode.Catalog


def touch(path: Path, size: int = 128) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)


def main() -> None:
    # The product intentionally writes the metadata snapshot in a daemon thread.
    # Windows may still hold the .localhub directory for a few milliseconds after
    # all business assertions have completed, so test cleanup must tolerate that.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        for i in range(5):
            touch(root / f"root-{i:02}.mp4", 500 + i)
        for folder in range(12):
            base = root / f"collection-{folder:02}"
            touch(base / f"video-{folder:02}.mp4", 800 + folder)
            for image in range(6):
                touch(base / f"page_{image:03}.jpg", 1000 + image * 3)
        touch(root / "book-only" / "alpha.jpg", 200)
        touch(root / "book-only" / "totally-different-name.png", 7000)

        store = server.MediaStore(root)
        catalog = Catalog(store)
        assert catalog.ready.wait(10), "catalog did not become ready"

        # Home is now a paged random browsing sequence. With only five videos
        # directly beside LocalHub, page one keeps all five and fills the rest
        # from subfolders up to 15.
        home = catalog.home(offset=0, limit=15, seed="initial-home")
        assert home["total"] == 17, home
        assert len(home["items"]) == 15, home
        assert all(item["kind"] == "video" for item in home["items"])
        assert sum(1 for item in home["items"] if not item["folder"]) == 5
        assert home["hasMore"] is True

        folder = catalog.list_view("folder", "collection-00", limit=30)
        kinds = [item["kind"] for item in folder["items"]]
        assert kinds.count("video") == 1, kinds
        assert kinds.count("pack") == 1, kinds
        assert "image" not in kinds, kinds

        book = catalog.list_view("folder", "book-only", limit=30)
        assert [item["kind"] for item in book["items"]] == ["pack"], book["items"]
        assert book["items"][0]["count"] == 2

        videos = catalog.list_view("videos", limit=30)
        assert videos["total"] == 17, videos["total"]
        assert len(videos["items"]) == 17

        packs = catalog.list_view("packs", limit=60)
        assert packs["total"] == 13, packs["total"]

        found = catalog.list_view("search", q="collection-03", limit=30)
        assert found["total"] >= 1

        # Existing media is the launch baseline and must never appear as "new".
        new_before = catalog.list_view("new", limit=30)
        assert new_before["total"] == 0, new_before

        # Dropping a video into an existing or new folder should be discovered by
        # the cheap path watcher, then promoted through a real catalog refresh.
        touch(root / "incoming" / "fresh-video.mp4", 2048)
        catalog.last_change_check = 0.0
        new_after = catalog.list_view("new", limit=30)
        assert new_after["catalogChanged"] is True, new_after
        assert new_after["total"] == 1, new_after
        assert new_after["items"][0]["id"] == "incoming/fresh-video.mp4"
        assert catalog.stats()["videos"] == 18
        assert any(row["path"] == "incoming" for row in catalog.folders())

        # Folder navigation is a tree, not a list grouped globally by depth.
        # A child must be emitted immediately after its real parent before the
        # next unrelated root folder, otherwise the sidebar visually nests it
        # under the wrong root.
        touch(root / "Videos" / "上课" / "lesson.mp4", 1500)
        touch(root / "亚洲" / "asia.mp4", 1500)
        catalog.refresh(wait=True, track_new=False)
        folder_paths = [row["path"] for row in catalog.folders()]
        videos_index = folder_paths.index("Videos")
        lesson_index = folder_paths.index("Videos/上课")
        asia_index = folder_paths.index("亚洲")
        assert videos_index < lesson_index < asia_index, folder_paths
        assert catalog.stats()["videos"] == 20

        # A manual refresh is also used after LocalHub rename/move operations.
        # Path changes from those workflows must not look like newly copied media.
        touch(root / "manual-only.mp4", 1900)
        catalog.refresh(wait=True, track_new=False)
        manual_view = catalog.list_view("new", limit=30)
        assert manual_view["total"] == 1, manual_view
        assert all(item["id"] != "manual-only.mp4" for item in manual_view["items"])
        assert catalog.stats()["videos"] == 21

        # Home browsing is a stable random sequence: 15 per page, no repeats
        # until every video has appeared. Reusing the same seed makes Back/Next
        # deterministic instead of reshuffling the page under the user.
        home_round_one = catalog.home(offset=0, limit=15, seed="smoke-home")
        home_round_two = catalog.home(offset=15, limit=15, seed="smoke-home")
        assert len(home_round_one["items"]) == 15
        first_ids = [row["id"] for row in home_round_one["items"]]
        second_ids = [row["id"] for row in home_round_two["items"]]
        assert not (set(first_ids) & set(second_ids)), (first_ids, second_ids)
        assert len(first_ids + second_ids) == len(set(first_ids + second_ids)) == 21
        repeat_first = catalog.home(offset=0, limit=15, seed="smoke-home")
        assert [row["id"] for row in repeat_first["items"]] == first_ids

        # Re-polling does not duplicate the same discovery.
        catalog.last_change_check = 0.0
        new_again = catalog.list_view("new", limit=30)
        assert new_again["total"] == 1, new_again

        deadline = time.monotonic() + 5
        while catalog.building and time.monotonic() < deadline:
            time.sleep(0.02)

        print("smart catalog smoke test passed")


if __name__ == "__main__":
    main()
