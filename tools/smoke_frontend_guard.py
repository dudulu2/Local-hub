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

# v23_features still contains the original rescan repaint implementation. The
# guard above narrows its observer to disabled only, preventing self-triggering
# childList loops.
assert "new MutationObserver(repaint).observe(rescan" in features

# The interaction repair owns the capture-phase drag path. It may wrap global
# fetch solely to time-bound /api/media/probe, but it must never add a second
# source-selection/probe controller or mutate video.src.
assert "document.documentElement.dataset.interactionFix = '2.4-probe-failfast'" in player_fix
assert "window.addEventListener('dragstart'" in player_fix
assert "function cleanDrag(state = armedDrag" in player_fix
assert "event.stopPropagation();" in player_fix
assert "dropTargetAt(event.clientX, event.clientY" in player_fix
assert "url.includes('/api/media/probe')" in player_fix
assert "setTimeout(() => controller.abort(), 3500)" in player_fix
assert "video.removeAttribute('src')" not in player_fix
assert "video.src =" not in player_fix
assert "compatBtn.click()" not in player_fix
assert "autoCompat(" not in player_fix

# Timeline input is UI-only while dragging. Exactly one real seek is committed
# on release/change; failure may recommend compatibility but never launches it.
assert "window.addEventListener('input'" in player_fix
assert "event.stopImmediatePropagation();" in player_fix
assert "function commitSeek()" in player_fix
assert "video.currentTime = target" in player_fix
assert "}, 8000);" in player_fix

print("frontend interaction guard smoke test passed")
