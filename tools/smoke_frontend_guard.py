from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "smart_index.html").read_text("utf-8")
features = (ROOT / "v23_features.js").read_text("utf-8")
player_fix = (ROOT / "v23_player_fix.js").read_text("utf-8")

marker = "2.3.2 observer guard"
assert marker in html, "frontend observer guard missing"
assert "<script src=\"/ux_enhancements.js\"></script>" in html
assert "<script src=\"/v23_features.js\"></script>" in html
assert html.index(marker) < html.index("<script src=\"/ux_enhancements.js\"></script>"), "observer guard must run before UX observer"
assert html.index(marker) < html.index("<script src=\"/v23_features.js\"></script>"), "observer guard must run before v23 features"
assert "target===document.body" in html
assert "target?.id==='rescanBtn'" in html
assert "attributeFilter:['disabled']" in html

# 2.3.0's rescan observer rewrites the same childList it observes. The guard
# above must remain until this implementation is refactored.
assert "new MutationObserver(repaint).observe(rescan" in features

# 2.3.2 intercepts the old document-level drag before it arms, disables native
# image dragging, and always tears the ghost down through an explicit state.
assert "document.documentElement.dataset.interactionFix = '2.3.2'" in player_fix
assert "window.addEventListener('dragstart'" in player_fix
assert "function cleanDrag(state = armedDrag" in player_fix
assert "event.stopPropagation();" in player_fix
assert "dropTargetAt(event.clientX, event.clientY" in player_fix

# Timeline input must preview only. The real media seek is committed once on
# release/change and the old 650ms false-positive path is stopped in capture.
assert "window.addEventListener('input'" in player_fix
assert "event.stopImmediatePropagation();" in player_fix
assert "function commitSeek()" in player_fix
assert "video.currentTime = target" in player_fix
assert "}, 8000);" in player_fix

print("frontend interaction guard smoke test passed")
