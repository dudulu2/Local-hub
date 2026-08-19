from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

MPV_FORMAT_INT64 = 4
WORKER_POLL_SECONDS = 0.20
WORKER_STALL_SECONDS = 4.0
INIT_TIMEOUT_SECONDS = 10.0


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def find_libmpv() -> Path | None:
    env = os.environ.get("LOCALHUB_LIBMPV_DLL", "").strip()
    candidates = [Path(env)] if env else []
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


def _append_log(root: Path, message: str) -> None:
    try:
        folder = Path(root) / ".localhub"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "native-player.log").open("a", encoding="utf-8") as fp:
            fp.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message.rstrip()}\n")
    except OSError:
        pass


class LibMpv:
    def __init__(self, dll: Path, hwnd: int, log_path: Path | None = None):
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
            # Alpha2 first proves stability. Re-enable hwdec only after real-media
            # validation because Windows decoder/driver interop can hang a VO.
            self._set_option("hwdec", "no")
            self._set_option("vo", "gpu")
            self._set_option("msg-level", "all=warn")
            if log_path:
                self._set_option("log-file", str(log_path))

            # mpv's Win32 wid is an HWND value represented as uint32_t.
            wid = ctypes.c_int64(int(hwnd) & 0xFFFFFFFF)
            result = self.lib.mpv_set_option(
                self.handle, b"wid", MPV_FORMAT_INT64, ctypes.byref(wid)
            )
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
        result = self.lib.mpv_set_option_string(
            self.handle,
            name.encode("utf-8"),
            str(value).encode("utf-8", "surrogatepass"),
        )
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
            return int(
                self.lib.mpv_set_property_string(
                    self.handle,
                    name.encode("utf-8"),
                    str(value).encode("utf-8", "surrogatepass"),
                )
            )

    def get_property(self, name: str, default: str = "") -> str:
        with self._lock:
            if self._destroyed or not self.handle:
                return default
            ptr = self.lib.mpv_get_property_string(self.handle, name.encode("utf-8"))
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
    """Non-blocking pywebview bridge with lazy native video surface creation."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.window = None
        self.form = None
        self.panel = None
        self.player: LibMpv | None = None
        self.error = ""
        self.current = ""
        self._scale = 1.0
        self._action_type = None
        self._commands: queue.Queue[tuple[str, tuple]] = queue.Queue()
        self._worker_stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._status_lock = threading.RLock()
        self._surface_lock = threading.RLock()
        self._surface_creating = False
        self._pending_rect: tuple[float, float, float, float, bool] | None = None
        self._cached_state = {
            "ready": False,
            "paused": True,
            "time": 0.0,
            "duration": 0.0,
            "volume": 100.0,
            "speed": 1.0,
            "videoCodec": "",
            "videoFormat": "",
            "hwdec": "",
            "width": 0,
            "height": 0,
            "error": "",
        }
        self._engine_ready = False
        self._init_started = 0.0
        self._heartbeat = 0.0
        self._worker_error = ""
        self._attached = False

    def attach(self, window) -> None:
        """Capture the WinForms host only. Do not touch its control tree yet."""
        if self._attached:
            return
        self._attached = True
        self.window = window
        try:
            from webview.platforms.winforms import BrowserView
            from System import Action

            self.form = BrowserView.instances[window.uid]
            self._action_type = Action
            try:
                self._scale = float(self.form._scale)
            except Exception:
                self._scale = 1.0
            _append_log(self.root, "WebView host attached; native surface remains lazy")
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            _append_log(self.root, f"attach failed\n{traceback.format_exc()}")

    def _ui(self, fn) -> bool:
        form = self.form
        if form is None or self._action_type is None:
            return False
        try:
            if form.InvokeRequired:
                form.BeginInvoke(self._action_type(fn))
            else:
                fn()
            return True
        except Exception:
            return False

    def _ensure_surface_async(self) -> None:
        with self._surface_lock:
            if self.panel is not None or self._surface_creating or self._worker_stop.is_set():
                return
            self._surface_creating = True

        def create_surface():
            try:
                import System.Windows.Forms as WinForms
                from System.Drawing import Color

                panel = WinForms.Panel()
                panel.Name = "LocalHubNativeVideo"
                panel.BackColor = Color.Black
                panel.Visible = False
                panel.TabStop = False
                self.form.Controls.Add(panel)
                panel.BringToFront()
                self.panel = panel
                pending = self._pending_rect
                if pending:
                    self._apply_rect_ui(*pending)
                hwnd = int(panel.Handle.ToInt64())
                self._init_started = time.monotonic()
                self._worker_thread = threading.Thread(
                    target=self._worker_main,
                    args=(hwnd,),
                    name="LocalHubLibMpv",
                    daemon=True,
                )
                self._worker_thread.start()
                _append_log(self.root, f"lazy video surface created hwnd={int(hwnd) & 0xFFFFFFFF}")
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                _append_log(self.root, f"surface create failed\n{traceback.format_exc()}")
            finally:
                with self._surface_lock:
                    self._surface_creating = False

        if not self._ui(create_surface):
            with self._surface_lock:
                self._surface_creating = False
            self.error = "WinForms 宿主尚未准备好"

    def _worker_main(self, hwnd: int) -> None:
        player = None
        try:
            dll = find_libmpv()
            if not dll:
                raise RuntimeError("找不到 libmpv-2.dll")
            mpv_log = self.root / ".localhub" / "libmpv.log"
            try:
                mpv_log.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                mpv_log = None

            _append_log(self.root, f"worker start dll={dll}")
            player = LibMpv(dll, hwnd, mpv_log)
            self.player = player
            with self._status_lock:
                self._engine_ready = True
                self._worker_error = ""
                self._heartbeat = time.monotonic()
            _append_log(self.root, "libmpv initialized on dedicated worker")

            while not self._worker_stop.is_set():
                try:
                    command, args = self._commands.get(timeout=WORKER_POLL_SECONDS)
                except queue.Empty:
                    command, args = "", ()
                if command == "shutdown":
                    break
                if command:
                    self._process_command(player, command, args)
                snapshot = player.state()
                with self._status_lock:
                    self._cached_state = snapshot
                    self._heartbeat = time.monotonic()
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            with self._status_lock:
                self._worker_error = message
            _append_log(self.root, f"worker crashed\n{traceback.format_exc()}")
        finally:
            with self._status_lock:
                self._engine_ready = False
            if player is not None:
                try:
                    player.destroy()
                except Exception:
                    pass
            self.player = None
            _append_log(self.root, "worker exit")

    def _process_command(self, player: LibMpv, command: str, args: tuple) -> None:
        try:
            if command == "load":
                target, start, relative = args
                player.load(Path(target), float(start))
                self.current = str(relative)
            elif command == "toggle":
                paused = player.get_property("pause", "yes").lower() in {"yes", "true", "1"}
                player.set_property("pause", "no" if paused else "yes")
            elif command == "pause":
                player.set_property("pause", "yes" if bool(args[0]) else "no")
            elif command == "seek":
                player.command("seek", f"{max(0.0, float(args[0])):.3f}", "absolute", "exact")
            elif command == "seek-relative":
                player.command("seek", f"{float(args[0]):.3f}", "relative", "exact")
            elif command == "volume":
                value = max(0.0, min(100.0, float(args[0])))
                player.set_property("volume", f"{value:.2f}")
            elif command == "speed":
                value = max(0.25, min(4.0, float(args[0])))
                player.set_property("speed", f"{value:.3f}")
            elif command == "stop":
                player.command("stop")
                self.current = ""
        except Exception as exc:
            with self._status_lock:
                self._worker_error = f"{command}: {type(exc).__name__}: {exc}"
            _append_log(self.root, self._worker_error)

    def _enqueue(self, command: str, *args) -> None:
        if not self._worker_stop.is_set():
            self._commands.put((command, tuple(args)))

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

    def _apply_rect_ui(self, x: float, y: float, width: float, height: float, visible: bool) -> None:
        if not self.panel or not self.form:
            return
        from System.Drawing import Rectangle

        try:
            scale = float(getattr(self.form, "_scale", self._scale) or 1.0)
        except Exception:
            scale = self._scale or 1.0
        left = max(0, int(round(float(x) * scale)))
        top = max(0, int(round(float(y) * scale)))
        w = max(1, int(round(float(width) * scale)))
        h = max(1, int(round(float(height) * scale)))
        self.panel.Bounds = Rectangle(left, top, w, h)
        self.panel.Visible = bool(visible)
        if visible:
            self.panel.BringToFront()

    def player_status(self) -> dict:
        if self.error:
            return {"ok": False, "error": self.error}
        now = time.monotonic()
        with self._status_lock:
            engine_ready = bool(self._engine_ready)
            worker_error = self._worker_error
            heartbeat = float(self._heartbeat or 0.0)
            state = dict(self._cached_state)
        if worker_error:
            return {"ok": False, "error": worker_error, "state": state}
        if self.panel is None:
            return {
                "ok": True,
                "engine": "libmpv",
                "initializing": bool(self.current),
                "surfacePending": bool(self.current),
                "state": state,
                "path": self.current,
            }
        if not engine_ready:
            elapsed = now - self._init_started if self._init_started else 0.0
            if self._init_started and elapsed > INIT_TIMEOUT_SECONDS:
                return {
                    "ok": False,
                    "error": "libmpv 后台初始化超过 10 秒。主界面仍可操作；诊断见 .localhub/native-player.log。",
                    "state": state,
                }
            return {
                "ok": True,
                "engine": "libmpv",
                "initializing": True,
                "state": state,
                "path": self.current,
            }
        if heartbeat and now - heartbeat > WORKER_STALL_SECONDS:
            return {
                "ok": False,
                "error": "libmpv 控制线程超过 4 秒无心跳。主界面没有等待这个线程。",
                "stalled": True,
                "state": state,
                "path": self.current,
            }
        return {
            "ok": True,
            "engine": "libmpv",
            "initializing": False,
            "state": state,
            "path": self.current,
        }

    def player_load(self, path: str, start: float = 0.0) -> dict:
        try:
            if self.form is None:
                raise RuntimeError("WebView2 宿主尚未准备好")
            target = self._resolve(path)
            self.current = str(path)
            self._enqueue("load", str(target), max(0.0, float(start or 0.0)), self.current)
            self._ensure_surface_async()
            return {"ok": True, "path": self.current, "queued": True}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def player_rect(self, x: float, y: float, width: float, height: float, visible: bool = True) -> dict:
        self._pending_rect = (float(x), float(y), float(width), float(height), bool(visible))
        if self.panel is None:
            return {"ok": True, "pending": True}
        pending = self._pending_rect
        self._ui(lambda: self._apply_rect_ui(*pending))
        return {"ok": True}

    def player_toggle_pause(self) -> dict:
        self._enqueue("toggle")
        return {"ok": True}

    def player_pause(self, paused: bool) -> dict:
        self._enqueue("pause", bool(paused))
        return {"ok": True}

    def player_seek(self, seconds: float) -> dict:
        self._enqueue("seek", max(0.0, float(seconds)))
        return {"ok": True}

    def player_seek_relative(self, seconds: float) -> dict:
        self._enqueue("seek-relative", float(seconds))
        return {"ok": True}

    def player_volume(self, value: float) -> dict:
        self._enqueue("volume", max(0.0, min(100.0, float(value))))
        return {"ok": True}

    def player_speed(self, value: float) -> dict:
        self._enqueue("speed", max(0.25, min(4.0, float(value))))
        return {"ok": True}

    def player_stop(self) -> dict:
        self.current = ""
        self._enqueue("stop")
        self._pending_rect = None
        self._ui(lambda: setattr(self.panel, "Visible", False) if self.panel else None)
        return {"ok": True}

    def player_fullscreen(self) -> dict:
        try:
            if self.window:
                self.window.toggle_fullscreen()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def shutdown(self, wait: bool = False, timeout: float = 1.0) -> None:
        self._worker_stop.set()
        try:
            self._commands.put_nowait(("shutdown", ()))
        except Exception:
            pass
        self._ui(lambda: setattr(self.panel, "Visible", False) if self.panel else None)
        if wait:
            worker = self._worker_thread
            if worker and worker.is_alive() and worker is not threading.current_thread():
                worker.join(timeout=max(0.0, float(timeout)))


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
