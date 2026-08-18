from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "smart_index.html").read_text("utf-8")
features = (ROOT / "v23_features.js").read_text("utf-8")

marker = "LocalHub 2.3.1 bootstrap guard"
assert marker in html, "frontend loop guard missing"
assert "<script src=\"/v23_features.js\"></script>" in html
assert html.index(marker) < html.index("<script src=\"/v23_features.js\"></script>"), "guard must run before v23_features.js"
assert "target?.id==='rescanBtn'" in html
assert "attributeFilter:['disabled']" in html

# This exact observer is what caused the 2.3.0 microtask loop. Keeping this
# assertion documents why the bootstrap guard is required until v23_features
# is refactored to stop rewriting an observed childList.
assert "new MutationObserver(repaint).observe(rescan" in features
print("frontend observer loop guard smoke test passed")
