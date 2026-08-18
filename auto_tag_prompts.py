from __future__ import annotations

# Auto Tag v1 intentionally starts with a small, high-level prompt vocabulary.
# These are suggestions only; LocalHub does not auto-write them to metadata.
DEFAULT_TAG_PROMPTS: dict[str, tuple[str, ...]] = {
    "室内": (
        "This is a photo taken indoors.",
        "This is an indoor scene.",
        "This is inside a room.",
        "The scene is indoors.",
    ),
    "户外": (
        "This is a photo taken outdoors.",
        "This is an outdoor scene.",
        "This is outside.",
        "The scene is outdoors.",
    ),
    "单人": (
        "This is a photo of one person.",
        "There is a single person in the scene.",
        "One person is visible.",
        "This scene contains one person alone.",
    ),
    "多人": (
        "This is a photo of multiple people.",
        "There is a group of people in the scene.",
        "Several people are visible.",
        "This scene contains more than one person.",
    ),
    "白天": (
        "This is a daytime scene.",
        "This scene is in daylight.",
        "This is a photo taken during the day.",
    ),
    "夜晚": (
        "This is a nighttime scene.",
        "This scene is at night.",
        "This is a photo taken during the night.",
    ),
    "动画": (
        "This is animated artwork.",
        "This is an anime or cartoon scene.",
        "This is a computer generated animated scene.",
    ),
    "真人": (
        "This is live action footage of real people.",
        "This is a real photograph or live action video frame.",
        "This scene shows real people rather than animation.",
    ),
}
