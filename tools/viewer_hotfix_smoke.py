from pathlib import Path

checks = {
    "v23_features.js": "LH_RECOMMEND_NAVIGATION_FIX_V2",
    "playback_stability.js": "LH_PORTRAIT_HARD_FIT_V2",
}

for filename, marker in checks.items():
    text = Path(filename).read_text("utf-8")
    assert marker in text, f"missing {marker} in {filename}"

print("viewer hotfix markers: OK")
