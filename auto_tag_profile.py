from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from auto_tag_prompts import DEFAULT_PACK_ID, STARTER_TAG_PACKS, pack_payload


class AutoTagProfile:
    """Small local-first configuration for one LocalHub media library."""

    def __init__(self, root: Path) -> None:
        self.path = root / ".localhub" / "auto-tag-profile.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.data = self._load()

    def _default(self) -> dict:
        return {
            "configured": False,
            "packId": DEFAULT_PACK_ID,
            "packLabel": STARTER_TAG_PACKS[DEFAULT_PACK_ID]["label"],
            "tags": pack_payload(DEFAULT_PACK_ID)["tags"],
            "revision": 1,
            "updatedAt": int(time.time() * 1000),
        }

    def _sanitize_tags(self, rows) -> list[dict]:
        result: list[dict] = []
        seen: set[str] = set()
        if not isinstance(rows, list):
            return result
        for raw in rows[:64]:
            if isinstance(raw, str):
                tag = raw.strip()
                description = ""
            elif isinstance(raw, dict):
                tag = str(raw.get("tag", "")).strip()
                description = str(raw.get("description", "")).strip()
            else:
                continue
            if not tag or len(tag) > 48:
                continue
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append({"tag": tag, "description": description[:400]})
        return result

    def _load(self) -> dict:
        base = self._default()
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return base
        if not isinstance(raw, dict):
            return base
        pack_id = str(raw.get("packId", DEFAULT_PACK_ID))
        if pack_id not in STARTER_TAG_PACKS:
            pack_id = DEFAULT_PACK_ID
        tags = self._sanitize_tags(raw.get("tags"))
        if not tags:
            tags = pack_payload(pack_id)["tags"]
        return {
            "configured": bool(raw.get("configured", False)),
            "packId": pack_id,
            "packLabel": str(raw.get("packLabel") or STARTER_TAG_PACKS[pack_id]["label"]),
            "tags": tags,
            "revision": max(1, int(raw.get("revision", 1) or 1)),
            "updatedAt": int(raw.get("updatedAt", 0) or 0),
        }

    def _save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.path)

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.data, ensure_ascii=False))

    def packs(self) -> list[dict]:
        return [
            {"id": key, "label": row["label"], "tagCount": len(row["tags"])}
            for key, row in STARTER_TAG_PACKS.items()
        ]

    def select_pack(self, pack_id: str) -> dict:
        if pack_id not in STARTER_TAG_PACKS:
            raise ValueError("未知 Tag 初始包")
        payload = pack_payload(pack_id)
        with self.lock:
            self.data.update(
                {
                    "configured": True,
                    "packId": pack_id,
                    "packLabel": payload["label"],
                    "tags": payload["tags"],
                    "revision": int(self.data.get("revision", 1)) + 1,
                    "updatedAt": int(time.time() * 1000),
                }
            )
            self._save()
            return self.snapshot()

    def update(self, *, tags=None, pack_id: str | None = None, configured: bool | None = None) -> dict:
        with self.lock:
            if pack_id is not None:
                if pack_id not in STARTER_TAG_PACKS:
                    raise ValueError("未知 Tag 初始包")
                self.data["packId"] = pack_id
                self.data["packLabel"] = STARTER_TAG_PACKS[pack_id]["label"]
            if tags is not None:
                cleaned = self._sanitize_tags(tags)
                if not cleaned:
                    raise ValueError("至少保留一个 Tag")
                self.data["tags"] = cleaned
            if configured is not None:
                self.data["configured"] = bool(configured)
            self.data["revision"] = int(self.data.get("revision", 1)) + 1
            self.data["updatedAt"] = int(time.time() * 1000)
            self._save()
            return self.snapshot()
