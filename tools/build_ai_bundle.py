from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

MODEL_ID = "siglip-base-patch16-224-int8"
HF_REVISION = "4649052661e53c7000355844105f8a1792088239"
HF_REPO = "Xenova/siglip-base-patch16-224"
MODEL_LICENSE = "Apache-2.0 (base model: google/siglip-base-patch16-224)"

MODEL_FILES = (
    (
        "vision_model_int8.onnx",
        "onnx/vision_model_int8.onnx",
        94_098_316,
        "6d00762fcb4aef9bdee1b886fcccc7df466f9eae321e180f97d88e24fa13ac72",
    ),
    (
        "text_model_int8.onnx",
        "onnx/text_model_int8.onnx",
        110_982_746,
        "9cb5102160e2a2b90c0a999ed6c2b4090865c9d5aa08f09cd10993ad9b38bd5f",
    ),
    (
        "spiece.model",
        "spiece.model",
        798_330,
        "1e5036bed065526c3c212dfbe288752391797c4bb1a284aa18c9a0b23fcaf8ec",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def download_model(target: Path, remote_path: str, expected_size: int, expected_sha256: str) -> None:
    if target.exists() and target.stat().st_size == expected_size and sha256_file(target) == expected_sha256:
        print(f"reuse {target.name}")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    temp.unlink(missing_ok=True)
    url = f"https://huggingface.co/{HF_REPO}/resolve/{HF_REVISION}/{remote_path}?download=true"
    request = urllib.request.Request(url, headers={"User-Agent": "LocalHub-AI-Bundle/1.0"})
    digest = hashlib.sha256()
    written = 0
    print(f"download {target.name}")
    with urllib.request.urlopen(request, timeout=90) as response, temp.open("wb") as out:
        while True:
            chunk = response.read(4 * 1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            written += len(chunk)

    actual_sha = digest.hexdigest().lower()
    if written != expected_size:
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"{target.name}: size mismatch {written} != {expected_size}")
    if actual_sha != expected_sha256:
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"{target.name}: SHA256 mismatch {actual_sha} != {expected_sha256}")
    temp.replace(target)


def write_launcher(path: Path) -> None:
    path.write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        f"set \"MODEL_ID={MODEL_ID}\"\r\n"
        "set \"SOURCE=%~dp0models\\%MODEL_ID%\"\r\n"
        "set \"TARGET=%LOCALAPPDATA%\\LocalHub\\models\\%MODEL_ID%\"\r\n"
        "if not exist \"%TARGET%\\manifest.json\" (\r\n"
        "  echo Installing LocalHub AI model locally...\r\n"
        "  if not exist \"%TARGET%\" mkdir \"%TARGET%\"\r\n"
        "  copy /Y \"%SOURCE%\\vision_model_int8.onnx\" \"%TARGET%\\vision_model_int8.onnx\" >nul\r\n"
        "  copy /Y \"%SOURCE%\\text_model_int8.onnx\" \"%TARGET%\\text_model_int8.onnx\" >nul\r\n"
        "  copy /Y \"%SOURCE%\\spiece.model\" \"%TARGET%\\spiece.model\" >nul\r\n"
        "  copy /Y \"%SOURCE%\\manifest.json\" \"%TARGET%\\manifest.json\" >nul\r\n"
        ")\r\n"
        "start \"\" \"%~dp0LocalHub.exe\"\r\n",
        encoding="utf-8",
    )


def build_bundle(exe: Path, output_dir: Path) -> Path:
    if not exe.is_file():
        raise FileNotFoundError(exe)

    package_root = output_dir / "LocalHub-with-AI"
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True)
    shutil.copy2(exe, package_root / "LocalHub.exe")

    model_dir = package_root / "models" / MODEL_ID
    hashes = {}
    for name, remote_path, size, expected_sha in MODEL_FILES:
        target = model_dir / name
        download_model(target, remote_path, size, expected_sha)
        hashes[name] = expected_sha

    manifest = {
        "model": MODEL_ID,
        "base": "google/siglip-base-patch16-224",
        "onnx": HF_REPO,
        "revision": HF_REVISION,
        "license": MODEL_LICENSE,
        "sha256": hashes,
        "installedAt": 0,
    }
    (model_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_launcher(package_root / "LocalHub with AI.cmd")
    (package_root / "README-AI.txt").write_text(
        "LocalHub with AI\n\n"
        "1. Extract the ZIP to a normal folder.\n"
        "2. Double-click 'LocalHub with AI.cmd'.\n"
        "3. On first launch, the bundled AI model is copied to %LOCALAPPDATA%\\LocalHub\\models.\n"
        "4. After that, LocalHub can use the local AI model without downloading it again.\n\n"
        "The AI model is SigLIP Base Patch16-224 INT8 (ONNX).\n"
        f"Source: {HF_REPO}@{HF_REVISION}\n"
        f"License: {MODEL_LICENSE}\n\n"
        "Your media files are not included in the package and do not need to be uploaded for local AI tagging.\n",
        encoding="utf-8",
    )

    zip_path = output_dir / "LocalHub-with-AI.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(package_root.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(output_dir))

    print(f"created {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the LocalHub-with-AI release ZIP")
    parser.add_argument("--exe", default="dist/LocalHub.exe")
    parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args()
    build_bundle(Path(args.exe), Path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
