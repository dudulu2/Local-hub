from __future__ import annotations

import io
import os
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageOps

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".tif", ".tiff"}

_CACHE_LOCK = threading.RLock()
_CACHE: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
_CACHE_MAX = 48
_CACHE_TTL = 180.0
_EXTRACTORS = threading.BoundedSemaphore(2)


def _cache_get(key: str) -> bytes | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if not hit:
            return None
        created, data = hit
        if now - created > _CACHE_TTL:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return data


def _cache_put(key: str, data: bytes) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), data)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _identity(path: Path, size: int) -> str:
    stat = path.stat()
    return f"{path}\n{stat.st_size}\n{stat.st_mtime_ns}\n{size}"


def _shell_thumbnail(path: Path, size: int) -> bytes | None:
    """Use Windows Explorer's shared Shell thumbnail cache when possible."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import POINTER, Structure, byref, c_int, c_long, c_void_p
        from ctypes import wintypes
        from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

        class SIZE(Structure):
            _fields_ = [("cx", c_int), ("cy", c_int)]

        class IShellItemImageFactory(IUnknown):
            _iid_ = GUID("{BCC18B79-BA16-442F-80C4-8A59C30C463B}")
            _methods_ = [
                COMMETHOD(
                    [], HRESULT, "GetImage",
                    (["in"], SIZE, "size"),
                    (["in"], ctypes.c_uint, "flags"),
                    (["out"], POINTER(wintypes.HBITMAP), "phbm"),
                )
            ]

        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        create_item = shell32.SHCreateItemFromParsingName
        create_item.argtypes = [wintypes.LPCWSTR, c_void_p, POINTER(GUID), POINTER(POINTER(IShellItemImageFactory))]
        create_item.restype = c_long

        ole32.CoInitialize(None)
        try:
            factory = POINTER(IShellItemImageFactory)()
            iid = IShellItemImageFactory._iid_
            hr = create_item(str(path), None, byref(iid), byref(factory))
            if hr != 0 or not factory:
                return None

            try:
                # comtypes returns a sole [out] parameter as the Python return value.
                # First do cache-only work; this mirrors Explorer and avoids decoding.
                hbitmap = factory.GetImage(SIZE(size, size), 0x08 | 0x10)
            except Exception:
                try:
                    # Cache miss: let the registered Shell provider extract/cache it
                    # on this background worker rather than on the browser/UI thread.
                    hbitmap = factory.GetImage(SIZE(size, size), 0x08 | 0x01)
                except Exception:
                    return None
            if not hbitmap:
                return None

            class BITMAP(Structure):
                _fields_ = [
                    ("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                    ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                    ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                    ("bmBits", c_void_p),
                ]

            class BITMAPINFOHEADER(Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            class BITMAPINFO(Structure):
                _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

            bmp = BITMAP()
            if not gdi32.GetObjectW(hbitmap, ctypes.sizeof(BITMAP), byref(bmp)):
                gdi32.DeleteObject(hbitmap)
                return None
            width, height = int(bmp.bmWidth), abs(int(bmp.bmHeight))
            if width <= 0 or height <= 0:
                gdi32.DeleteObject(hbitmap)
                return None

            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = 0
            raw = ctypes.create_string_buffer(width * height * 4)
            dc = user32.GetDC(None)
            try:
                lines = gdi32.GetDIBits(dc, hbitmap, 0, height, raw, byref(info), 0)
            finally:
                user32.ReleaseDC(None, dc)
                gdi32.DeleteObject(hbitmap)
            if lines == 0:
                return None
            image = Image.frombuffer("RGBA", (width, height), raw, "raw", "BGRA", 0, 1).convert("RGB")
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=72, optimize=False)
            return out.getvalue()
        finally:
            ole32.CoUninitialize()
    except Exception:
        return None


def _pil_thumbnail(path: Path, size: int) -> bytes | None:
    if path.suffix.lower() not in IMAGE_EXTS:
        return None
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if getattr(im, "is_animated", False):
                im.seek(0)
            im = im.convert("RGB")
            im.thumbnail((size, size), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=72, optimize=False)
            return out.getvalue()
    except Exception:
        return None


def _ffmpeg_exe() -> str | None:
    if imageio_ffmpeg is not None:
        try:
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and Path(exe).exists():
                return exe
        except Exception:
            pass
    return shutil.which("ffmpeg")


def _ffmpeg_thumbnail(path: Path, size: int) -> bytes | None:
    exe = _ffmpeg_exe()
    if not exe:
        return None
    command = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", "1.0", "-noaccurate_seek", "-i", str(path),
        "-an", "-sn", "-dn", "-frames:v", "1",
        "-vf", f"scale='min({size},iw)':-2",
        "-q:v", "8", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8, check=False)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(command, **kwargs)
        data = result.stdout or b""
        return data if result.returncode == 0 and len(data) > 300 else None
    except (OSError, subprocess.SubprocessError):
        return None


def get_thumbnail(path: Path, size: int = 360) -> bytes | None:
    try:
        key = _identity(path, size)
    except OSError:
        return None
    hit = _cache_get(key)
    if hit is not None:
        return hit
    with _EXTRACTORS:
        hit = _cache_get(key)
        if hit is not None:
            return hit
        data = _shell_thumbnail(path, size)
        if data is None:
            data = _pil_thumbnail(path, size)
        if data is None:
            data = _ffmpeg_thumbnail(path, size)
        if data:
            _cache_put(key, data)
        return data


def clear_memory_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
