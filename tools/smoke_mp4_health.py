from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import preview_support


def main() -> None:
    script = preview_support._MP4_HEALTH_SCRIPT
    for required in (
        "nativeSource",
        "/media/",
        "backwardHits.length>=2",
        "triggerRepair('loop')",
        "triggerRepair('seek')",
        "videoCodec",
        "compatMode!=='remux'",
        "compat.click()",
        "MP4 时间轴",
    ):
        assert required in script, required

    priority = preview_support._PLAYBACK_PRIORITY_SCRIPT
    assert "document.addEventListener('click'" in priority
    assert "document.addEventListener('pointerdown'" not in priority

    node = shutil.which("node")
    if node:
        match = re.search(r"<script>\s*(.*?)\s*</script>", script, re.S)
        assert match, "MP4 health script block missing"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(match.group(1))
            name = fh.name
        try:
            proc = subprocess.run([node, "--check", name], capture_output=True, text=True, check=False)
            assert proc.returncode == 0, proc.stderr
        finally:
            Path(name).unlink(missing_ok=True)

    print("mp4 timeline health smoke test passed")


if __name__ == "__main__":
    main()
