from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fit(stage_w: float, stage_h: float, aspect: float) -> tuple[int, int]:
    assert stage_w > 0 and stage_h > 0 and aspect > 0
    width = stage_w
    height = width / aspect
    if height > stage_h:
        height = stage_h
        width = height * aspect
    return max(1, int(width // 1)), max(1, int(height // 1))


def main() -> None:
    source = (ROOT / "preview_support.py").read_text("utf-8")

    # The exact-fit algorithm must apply to every known aspect ratio, not only portrait.
    assert "if(!displayAspect)return;" in source
    assert "if(!displayAspect||!viewer.classList.contains('lh-probe-portrait'))return;" not in source
    assert "apply(p.displayAspect,p.width,p.height)" in source
    assert ".viewer.lh-probe-landscape .viewer-stage video{width:var(--lh-fit-w,auto)!important" in source

    aspect = 1906 / 1080

    # Real regression case: a very wide/short non-fullscreen stage must fit by height.
    w, h = fit(2019, 654, aspect)
    assert h == 654
    assert 1153 <= w <= 1155, (w, h)
    assert w <= 2019 and h <= 654

    # Fullscreen 2048x1152 should keep the complete frame and leave a small side letterbox.
    w, h = fit(2048, 1152, aspect)
    assert h == 1152
    assert 2032 <= w <= 2034, (w, h)
    assert w <= 2048 and h <= 1152

    # Portrait remains exact-fit after unifying the path.
    w, h = fit(600, 800, 1080 / 1920)
    assert (w, h) == (450, 800), (w, h)

    # Square and classic 4:3 also stay fully inside the stage.
    assert fit(1280, 720, 1.0) == (720, 720)
    assert fit(1280, 720, 4 / 3) == (960, 720)

    print("unified exact-fit smoke test passed")


if __name__ == "__main__":
    main()
