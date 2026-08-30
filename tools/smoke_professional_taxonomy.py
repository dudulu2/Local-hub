from __future__ import annotations

import ai_taxonomy_v2


def main() -> None:
    groups = ai_taxonomy_v2.PROFESSIONAL_GROUPS
    assert groups, "professional taxonomy missing"
    assert all(len(group.get("tags", [])) >= 20 for group in groups), "every built-in group must have at least 20 tags"
    names = [str(group.get("name", "")) for group in groups]
    assert len(names) == len(set(names)), "group names must be unique"
    print("professional taxonomy smoke test passed")


if __name__ == "__main__":
    main()
