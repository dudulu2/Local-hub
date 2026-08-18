from __future__ import annotations

import math

import media_probe


def main() -> None:
    # 1080x1920 is exactly 9:16 and is a perfectly normal vertical video frame.
    ratio = media_probe._display_aspect(1080, 1920, 1, 1, None, None)
    assert math.isclose(ratio, 9 / 16, rel_tol=1e-6), ratio

    # Non-square pixels must affect display aspect, not just coded dimensions.
    anamorphic = media_probe._display_aspect(720, 576, 16, 15, None, None)
    assert math.isclose(anamorphic, 4 / 3, rel_tol=1e-6), anamorphic

    # A 90-degree display rotation inverts the final display aspect.
    rotated = media_probe._display_aspect(1920, 1080, 1, 1, None, 90.0)
    assert math.isclose(rotated, 9 / 16, rel_tol=1e-6), rotated

    # Explicit DAR is authoritative before rotation.
    explicit = media_probe._display_aspect(1920, 1080, 1, 1, (4, 3), None)
    assert math.isclose(explicit, 4 / 3, rel_tol=1e-6), explicit

    print('portrait display-aspect smoke test passed')


if __name__ == '__main__':
    main()
