from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from siglip_encoder import HF_REPO, HF_REVISION, LOCAL_PACKAGE_DIR, MODEL_FILES, MODEL_ID, MODEL_LICENSE


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def valid(path: Path, row) -> bool:
    try:
        return path.stat().st_size == row.size and file_hash(path) == row.sha256
    except OSError:
        return False


def download(row, target: Path) -> None:
    if valid(target, row):
        print(f"reuse {row.name}")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    part.unlink(missing_ok=True)
    request = urllib.request.Request(row.url, headers={"User-Agent": "LocalHub-build/2.4"})
    digest = hashlib.sha256()
    written = 0
    print(f"download {row.name} ({row.size / 1_000_000:.1f} MB)")
    with urllib.request.urlopen(request, timeout=90) as response, part.open("wb") as out:
        while True:
            chunk = response.read(4 * 1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            written += len(chunk)
            print(f"  {written / row.size * 100:5.1f}%", end="\r", flush=True)
    print()
    if written != row.size:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{row.name}: size mismatch {written} != {row.size}")
    if digest.hexdigest().lower() != row.sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{row.name}: SHA256 mismatch")
    part.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare LocalHub offline SigLIP package")
    parser.add_argument("destination", nargs="?", default=str(ROOT / "dist" / LOCAL_PACKAGE_DIR))
    args = parser.parse_args()
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    for row in MODEL_FILES:
        download(row, destination / row.name)

    manifest = {
        "package": LOCAL_PACKAGE_DIR,
        "model": MODEL_ID,
        "repo": HF_REPO,
        "revision": HF_REVISION,
        "license": MODEL_LICENSE,
        "files": {
            row.name: {"size": row.size, "sha256": row.sha256}
            for row in MODEL_FILES
        },
    }
    (destination / "model-package.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        "utf-8",
    )
    print(f"offline AI package ready: {destination}")


if __name__ == "__main__":
    main()
