from __future__ import annotations

import ai_taxonomy_v2


def main() -> None:
    groups = ai_taxonomy_v2.PROFESSIONAL_GROUPS
    assert groups, "professional taxonomy missing"
    assert all(len(group.get("tags", [])) >= 20 for group in groups), "every built-in group must have at least 20 tags"
    names = [str(group.get("name", "")) for group in groups]
    assert len(names) == len(set(names)), "group names must be unique"
    for expected in ("全部视频", "生活", "学习", "风景", "娱乐", "色情"):
        assert expected in names, f"missing product-facing group: {expected}"
    assert any(group.get("id") == "adult" for group in groups), "opt-in content group missing"
    print("professional taxonomy smoke test passed")


if __name__ == "__main__":
    main()
