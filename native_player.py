from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path

MPV_FORMAT_INT64 = 4


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def find_libmpv() -> Path | None:
    env = os.environ.get("LOCALHUB_LIBMPV_DLL", "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    base = _app_dir()
    candidates += [
        base / "libmpv-2.dll",
        base / "mpv-2.dll",
        base / "vendor" / "libmpv-2.dll",
        base / "vendor" / "mpv-2.dll",
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            pass
    return None


class LibMpv:
    def __init__(self, dll: Path, hwnd: int):
        self.dll_path = Path(dll)
        self.lib = ctypes.CDLL(str(self.dll_path))
        self._bind()
        self.handle = self.lib.mpv_create()
        if not self.handle:
            raise RuntimeError("libmpv 无法创建播放实例")
        self._destroyed = False
        self._lock = threading.RLock()
        try:
            self._set_option("terminal", "no")
            self._set_option("input-default-bindings", "no")
            self._set_option("input-vo-keyboard", "no")
            self._set_option("osc", "no")
            self._set_option("keep-open", "yes")
            self._set_option("idle", "yes")
            self._set_option("hwdec", "auto-safe")
            self._set_option("vo", "gpu-next")
            wid = ctypes.c_int64(int(hwnd) & 0xFFFFFFFF)
            result = self.lib.mpv_set_option(self.handle, b"wid", MPV_FORMAT_INT64, ctypes.byref(wid))
            if result < 0:
                raise RuntimeError(f"libmpv 无法绑定视频窗口 ({result})")
            result = self.lib.mpv_initialize(self.handle)
            if result < 0:
                raise RuntimeError(f"libmpv 初始化失败 ({result})")
        except Exception:
            self.destroy()
            raise

    def _bind(self) -> None:
        lib = self.lib
        lib.mpv_create.argtypes = []
        lib.mpv_create.restype = ctypes.c_void_p
        lib.mpv_initialize.argtypes = [ctypes.c_void_p]
        lib.mpv_initialize.restype = ctypes.c_int
        lib.mpv_terminate_destroy.argtypes = [ctypes.c_void_p]
        lib.mpv_terminate_destroy.restype = None
        lib.mpv_set_option_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.mpv_set_option_string.restype = ctypes.c_int
        lib.mpv_set_option.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        lib.mpv_set_option.restype = ctypes.c_int
        lib.mpv_command.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
        lib.mpv_command.restype = ctypes.c_int
        lib.mpv_set_property_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.mpv_set_property_string.restype = ctypes.c_int
        lib.mpv_get_property_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.mpv_get_property_string.restype = ctypes.c_void_p
        lib.mpv_free.argtypes = [ctypes.c_void_p]
        lib.mpv_free.restype = None

    def _set_option(self, name: str, value: str) -> None:
        result = self.lib.mpv_set_option_string(self.handle, name.encode(), value.encode())
        if result < 0:
            raise RuntimeError(f"libmpv 选项失败：{name} ({result})")

    def command(self, *args: str) -> int:
        with self._lock:
            if self._destroyed or not self.handle:
                return -1
            encoded = [str(x).encode("utf-8", "surrogatepass") for x in args]
            array = (ctypes.c_char_p * (len(encoded) + 1))()
            for i, value in enumerate(encoded):
                array[i] = value
            array[len(encoded)] = None
            return int(self.lib.mpv_command(self.handle, array))

    def set_property(self, name: str, value: str) -> int:
        with self._lock:
            if self._destroyed or not self.handle:
                return -1
            return int(self.lib.mpv_set_property_string(self.handle, name.encode(), str(value).encode()))

    def get_property(self, name: str, default: str = "") -> str:
        with self._lock:
            if self._destroyed or not self.handle:
                return default
            ptr = self.lib.mpv_get_property_string(self.handle, name.encode())
            if not ptr:
                return default
            try:
                return ctypes.string_at(ptr).decode("utf-8", "replace")
            finally:
                self.lib.mpv_free(ptr)

    def load(self, path: Path, start: float = 0.0) -> None:
        result = self.command("loadfile", str(path), "replace")
        if result < 0:
            raise RuntimeError(f"libmpv 无法加载视频 ({result})")
        if start > 0:
            self.command("seek", f"{start:.3f}", "absolute", "exact")

    def state(self) -> dict:
        def number(name: str, fallback: float = 0.0) -> float:
            try:
                return float(self.get_property(name, str(fallback)))
            except (TypeError, ValueError):
                return fallback

        paused = self.get_property("pause", "yes").lower() in {"yes", "true", "1"}
        idle = self.get_property("idle-active", "yes").lower() in {"yes", "true", "1"}
        return {
            "ready": not idle,
            "paused": paused,
            "time": max(0.0, number("time-pos")),
            "duration": max(0.0, number("duration")),
            "volume": max(0.0, min(100.0, number("volume", 100.0))),
            "speed": max(0.1, number("speed", 1.0)),
            "videoCodec": self.get_property("video-codec", ""),
            "videoFormat": self.get_property("video-format", ""),
            "hwdec": self.get_property("hwdec-current", ""),
            "width": int(number("width")),
            "height": int(number("height")),
            "error": "",
        }

    def destroy(self) -> None:
        with getattr(self, "_lock", threading.RLock()):
            if getattr(self, "_destroyed", True):
                return
            self._destroyed = True
            handle = getattr(self, "handle", None)
            self.handle = None
            if handle:
                try:
                    self.lib.mpv_terminate_destroy(handle)
                except Exception:
                    pass


class NativePlayerAPI:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.window = None
        self.form = None
        self.panel = None
        self.player: LibMpv | None = None
        self.error = ""
        self.current = ""
        self._scale = 1.0
        self._lock = threading.RLock()

    def attach(self, window) -> None:
        self.window = window
        try:
            from webview.platforms.winforms import BrowserView
            import System.Windows.Forms as WinForms
            from System import Action
            from System.Drawing import Color

            form = BrowserView.instances[window.uid]
            panel = WinForms.Panel()
            panel.Name = "LocalHubNativeVideo"
            panel.BackColor = Color.Black
            panel.Visible = False
            panel.TabStop = False
            form.Controls.Add(panel)
            panel.BringToFront()
            self.form = form
            self.panel = panel
            try:
                self._scale = float(form._scale)
            except Exception:
                self._scale = 1.0
            dll = find_libmpv()
            if not dll:
                raise RuntimeError("找不到 libmpv-2.dll")
            hwnd = int(panel.Handle.ToInt64())
            self.player = LibMpv(dll, hwnd)
            self._action_type = Action
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def _resolve(self, relative: str) -> Path:
        text = str(relative or "").replace("\\", "/").lstrip("/")
        if not text:
            raise ValueError("视频路径为空")
        target = (self.root / Path(text)).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("视频路径超出媒体目录") from exc
        if not target.is_file():
            raise FileNotFoundError("视频文件不存在")
        return target

    def _ui(self, fn) -> None:
        form = self.form
        if form is None:
            return
        try:
            if form.InvokeRequired:
                form.BeginInvoke(self._action_type(fn))
            else:
                fn()
        except Exception:
            pass

    def player_status(self) -> dict:
        if self.error:
            return {"ok": False, "error": self.error}
        if not self.player:
            return {"ok": False, "error": "libmpv 尚未初始化"}
        return {"ok": True, "engine": "libmpv", "state": self.player.state(), "path": self.current}

    def player_load(self, path: str, start: float = 0.0) -> dict:
        try:
            target = self._resolve(path)
            if not self.player:
                raise RuntimeError(self.error or "libmpv 尚未初始化")
            self.player.load(target, max(0.0, float(start or 0.0)))
            self.current = str(path)
            self._ui(lambda: (setattr(self.panel, "Visible", True), self.panel.BringToFront()) if self.panel else None)
            return {"ok": True, "path": self.current}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def player_rect(self, x: float, y: float, width: float, height: float, visible: bool = True) -> dict:
        if not self.panel or not self.form:
            return {"ok": False, "error": self.error or "原生视频窗口未初始化"}
        try:
            scale = float(getattr(self.form, "_scale", self._scale) or 1.0)
        except Exception:
            scale = self._scale or 1.0
        left = max(0, int(round(float(x) * scale)))
        top = max(0, int(round(float(y) * scale)))
        w = max(1, int(round(float(width) * scale)))
        h = max(1, int(round(float(height) * scale)))

        def apply():
            from System.Drawing import Rectangle
            self.panel.Bounds = Rectangle(left, top, w, h)
            self.panel.Visible = bool(visible)
            if visible:
                self.panel.BringToFront()

        self._ui(apply)
        return {"ok": True}

    def player_toggle_pause(self) -> dict:
        if not self.player:
            return {"ok": False, "error": self.error or "libmpv 尚未初始化"}
        paused = self.player.get_property("pause", "yes").lower() in {"yes", "true", "1"}
        self.player.set_property("pause", "no" if paused else "yes")
        return {"ok": True}

    def player_pause(self, paused: bool) -> dict:
        if not self.player:
            return {"ok": False, "error": self.error or "libmpv 尚未初始化"}
        self.player.set_property("pause", "yes" if paused else "no")
        return {"ok": True}

    def player_seek(self, seconds: float) -> dict:
        if not self.player:
            return {"ok": False, "error": self.error or "libmpv 尚未初始化"}
        self.player.command("seek", f"{max(0.0, float(seconds)):.3f}", "absolute", "exact")
        return {"ok": True}

    def player_seek_relative(self, seconds: float) -> dict:
        if not self.player:
            return {"ok": False, "error": self.error or "libmpv 尚未初始化"}
        self.player.command("seek", f"{float(seconds):.3f}", "relative", "exact")
        return {"ok": True}

    def player_volume(self, value: float) -> dict:
        if not self.player:
            return {"ok": False, "error": self.error or "libmpv 尚未初始化"}
        self.player.set_property("volume", f"{max(0.0, min(100.0, float(value))):.2f}")
        return {"ok": True}

    def player_speed(self, value: float) -> dict:
        if not self.player:
            return {"ok": False, "error": self.error or "libmpv 尚未初始化"}
        self.player.set_property("speed", f"{max(0.25, min(4.0, float(value))):.3f}")
        return {"ok": True}

    def player_stop(self) -> dict:
        if self.player:
            self.player.command("stop")
        self.current = ""
        self._ui(lambda: setattr(self.panel, "Visible", False) if self.panel else None)
        return {"ok": True}

    def player_fullscreen(self) -> dict:
        try:
            if self.window:
                self.window.toggle_fullscreen()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def shutdown(self) -> None:
        try:
            if self.player:
                self.player.destroy()
        finally:
            self.player = None
            self._ui(lambda: setattr(self.panel, "Visible", False) if self.panel else None)


def self_test(dll_path: str | None = None) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "native player is Windows-only"
    dll = Path(dll_path).resolve() if dll_path else find_libmpv()
    if not dll or not dll.is_file():
        return False, "libmpv-2.dll missing"
    try:
        lib = ctypes.CDLL(str(dll))
        create = lib.mpv_create
        create.argtypes = []
        create.restype = ctypes.c_void_p
        destroy = lib.mpv_terminate_destroy
        destroy.argtypes = [ctypes.c_void_p]
        destroy.restype = None
        handle = create()
        if not handle:
            return False, "mpv_create returned null"
        destroy(handle)
        return True, str(dll)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
