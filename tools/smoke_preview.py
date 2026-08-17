from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image
import imageio_ffmpeg
import smart_thumbnail


def assert_jpeg(data: bytes | None, label: str) -> None:
    assert data is not None, f"{label}: no data"
    assert len(data) > 300, f"{label}: too small ({len(data)})"
    assert data[:2] == b"\xff\xd8", f"{label}: not JPEG"


def main() -> None:
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    assert exe and Path(exe).exists(), "bundled ffmpeg missing"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        image_path = root / "cover.jpg"
        Image.new("RGB", (640, 360), (40, 80, 120)).save(image_path, quality=90)
        assert_jpeg(smart_thumbnail.get_thumbnail(image_path, 360), "image thumbnail")

        video_path = root / "preview.mp4"
        command = [
            exe, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=6",
            "-t", "18", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-y", str(video_path),
        ]
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=25, check=False)
        assert result.returncode == 0 and video_path.exists(), result.stderr.decode("utf-8", "replace")
        assert smart_thumbnail.ffmpeg_available(), "ffmpeg_available() is false"
        assert_jpeg(smart_thumbnail.get_thumbnail(video_path, 360), "video thumbnail")
        for slot in range(6):
            assert_jpeg(smart_thumbnail.get_hover_frame(video_path, slot, 360), f"hover frame {slot}")

    print("preview extraction smoke test passed")


if __name__ == "__main__":
    main()
