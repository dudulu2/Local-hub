from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PREFERRED_PORT = 8787
RUNTIME_FILE = "runtime.json"
ERROR_ALREADY_EXISTS = 183

# LocalHub talks only to its own loopback HTTP server. Never let Windows proxy,
# VPN, PAC, or capture-software settings route these requests away from 127.0.0.1.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_urlopen(request_or_url, timeout: float = 1.0):
    return _LOCAL_OPENER.open(request_or_url, timeout=timeout)


def media_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_dir(root: Path) -> Path:
    return root / ".localhub"


def runtime_path(root: Path) -> Path:
    return data_dir(root) / RUNTIME_FILE


def show_error(title: str, message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, str(message), str(title), 0x10)
    else:
        print(f"{title}: {message}", file=sys.stderr)


def write_startup_log(root: Path, message: str) -> Path | None:
    try:
        folder = data_dir(root)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "startup-error.log"
        target.write_text(message, "utf-8")
        return target
    except OSError:
        return None


def write_server_log(root: Path, message: str) -> Path | None:
    try:
        folder = data_dir(root)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "server-error.log"
        with target.open("a", encoding="utf-8") as fp:
            fp.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n")
            fp.write(message.rstrip() + "\n")
        return target
    except OSError:
        return None


def write_launcher_log(root: Path, message: str) -> Path | None:
    """Persist non-fatal browser/tray failures without taking the server down."""
    try:
        folder = data_dir(root)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "launcher-warning.log"
        with target.open("a", encoding="utf-8") as fp:
            fp.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n")
            fp.write(message.rstrip() + "\n")
        return target
    except OSError:
        return None


def acquire_instance_mutex(root: Path):
    if os.name != "nt":
        return None, False
    digest = hashlib.sha256(str(root).casefold().encode("utf-8")).hexdigest()[:24]
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, f"Local\\LocalHub_{digest}")
    already_exists = ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    return handle, already_exists


def server_header_is_localhub(url: str, timeout: float = 0.6) -> bool:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with local_urlopen(request, timeout=timeout) as response:
            return response.headers.get("Server", "").startswith("LocalHub/")
    except urllib.error.HTTPError as exc:
        return exc.headers.get("Server", "").startswith("LocalHub/")
    except Exception:
        return False


def existing_url(root: Path) -> str | None:
    path = runtime_path(root)
    try:
        payload = json.loads(path.read_text("utf-8"))
        port = int(payload.get("port", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not (1 <= port <= 65535):
        return None
    url = f"http://{HOST}:{port}/"
    if server_header_is_localhub(url):
        return url
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def wait_existing_url(root: Path, seconds: float = 8.0) -> str | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        url = existing_url(root)
        if url:
            return url
        time.sleep(0.2)
    return None


def wait_health(base_url: str, seconds: float = 8.0) -> bool:
    """Probe LocalHub directly on loopback, explicitly bypassing all proxies."""
    url = base_url.rstrip("/") + "/api/health"
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with local_urlopen(url, timeout=0.6) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    return payload.get("ok") is True
        except Exception:
            time.sleep(0.1)
    return False


def write_runtime(root: Path, port: int) -> None:
    folder = data_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    target = runtime_path(root)
    temp = target.with_suffix(".tmp")
    temp.write_text(
        json.dumps({"pid": os.getpid(), "port": port, "root": str(root)}, ensure_ascii=False, indent=2),
        "utf-8",
    )
    os.replace(temp, target)


def clear_runtime(root: Path) -> None:
    path = runtime_path(root)
    try:
        payload = json.loads(path.read_text("utf-8"))
        if int(payload.get("pid", -1)) != os.getpid():
            return
    except Exception:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_compat_cache(root: Path) -> None:
    try:
        import compat_support
        cleaner = getattr(compat_support, "cleanup_root", None)
        if not callable(cleaner):
            cleaner = getattr(compat_support, "cleanup_compat_dir", None)
        if callable(cleaner):
            cleaner(root)
            return
    except Exception:
        pass
    try:
        shutil.rmtree(root / ".localhub" / "compat", ignore_errors=True)
    except OSError:
        pass


def cleanup_runtime(root: Path) -> None:
    try:
        import smart_thumbnail
        smart_thumbnail.clear_memory_cache()
    except Exception:
        pass
    cleanup_compat_cache(root)


def configure_server(root: Path):
    """Install LocalHub extensions exactly once for this process and return server module."""
    import server
    import smart_mode
    import catalog_cache
    import preview_support
    import compat_support
    import rating_support
    import recommendation_support
    import io_support
    import auto_tag_support
    import siglip_support
    import ai_center_support

    app_dir = Path(server.APP_DIR)
    server.STATIC_FILES["/ux_enhancements.js"] = app_dir / "ux_enhancements.js"
    server.STATIC_FILES["/ux_enhancements.css"] = app_dir / "ux_enhancements.css"
    server.STATIC_FILES["/move_branding.js"] = app_dir / "move_branding.js"
    server.STATIC_FILES["/v23_features.js"] = app_dir / "v23_features.js"
    server.STATIC_FILES["/v23_features.css"] = app_dir / "v23_features.css"
    server.STATIC_FILES["/v23_player_fix.js"] = app_dir / "v23_player_fix.js"
    server.STATIC_FILES["/v23_player_fix.css"] = app_dir / "v23_player_fix.css"

    rating_support.install(server, smart_mode)
    catalog_cache.cleanup_legacy_thumbnail_cache(root)
    catalog_cache.install(smart_mode)
    smart_mode.install(server)
    preview_support.install(server)
    compat_support.install(server)
    recommendation_support.install(server, smart_mode)
    io_support.install(server)
    auto_tag_support.install(server, smart_mode)
    siglip_support.install(server, auto_tag_support)
    ai_center_support.install(server, auto_tag_support, siglip_support)
    cleanup_compat_cache(root)
    return server


def create_http_server(root: Path):
    """Synchronously bind the HTTP server and persist request-thread exceptions."""
    server_module = configure_server(root)
    store = server_module.MediaStore(root)
    handler = server_module.make_handler(store)

    class LoggedThreadingHTTPServer(server_module.ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            detail = "".join(traceback.format_exception(*sys.exc_info()))
            write_server_log(root, f"client={client_address!r}\n{detail}")

    try:
        httpd = LoggedThreadingHTTPServer((HOST, PREFERRED_PORT), handler)
    except OSError:
        httpd = LoggedThreadingHTTPServer((HOST, 0), handler)
    httpd.daemon_threads = True
    httpd.quiet = True
    port = int(httpd.server_address[1])
    return httpd, port


def self_test() -> int:
    """Exercise the real packaged startup path, including actual HTTP requests."""
    httpd = None
    try:
        import server
        import compat_support
        import recommendation_support
        import auto_tag_support
        import siglip_support
        import ai_center_support
        import interactive_preview_support
        if not callable(getattr(compat_support, "install", None)):
            return 11
        if not callable(getattr(recommendation_support, "install", None)):
            return 12
        if not callable(getattr(auto_tag_support, "install", None)):
            return 13
        if not callable(getattr(siglip_support, "install", None)):
            return 14
        if not callable(getattr(interactive_preview_support, "install", None)):
            return 15
        if not callable(getattr(ai_center_support, "install", None)):
            return 16
        app_dir = Path(server.APP_DIR)
        for name in (
            "smart_index.html", "smart_ui.css", "smart_ui.js", "ux_enhancements.css", "ux_enhancements.js",
            "move_branding.js", "v23_features.js", "v23_features.css", "v23_player_fix.js", "v23_player_fix.css",
            "auto_tag_ui.js", "auto_tag_ui.css", "playback_stability.js", "playback_stability.css",
            "ai_center.js", "ai_center.css",
        ):
            if not (app_dir / name).exists():
                return 20

        with tempfile.TemporaryDirectory(prefix="localhub-selftest-") as tmp:
            root = Path(tmp)
            httpd, port = create_http_server(root)
            thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            base = f"http://{HOST}:{port}"
            if not wait_health(base, 5.0):
                return 30
            with local_urlopen(base + "/", timeout=3.0) as response:
                body = response.read()
                if response.status != 200 or b"LocalHub" not in body or b"playback_stability.js" not in body or b"ai_center.js" not in body:
                    return 31
            with local_urlopen(base + "/api/smart/home", timeout=5.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if "items" not in payload or "stats" not in payload:
                    return 32
            with local_urlopen(base + "/api/auto-tag/status", timeout=5.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("ok") is not True or "model" not in payload:
                    return 33
            httpd.shutdown()
            thread.join(timeout=2.0)
            httpd.server_close()
            httpd = None
        return 0
    except Exception as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        write_startup_log(media_root(), "PACKAGED SELF-TEST FAILURE\n\n" + detail)
        return 99
    finally:
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass


def create_tray_image():
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (64, 64), (12, 12, 13, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((3, 3, 61, 61), radius=14, fill=(255, 151, 0, 255))
    draw.rounded_rectangle((10, 10, 54, 54), radius=10, fill=(18, 18, 20, 255))
    draw.polygon(((27, 19), (27, 45), (47, 32)), fill=(255, 151, 0, 255))
    return image


def run_tray(root: Path, url: str, shutdown_event: threading.Event) -> None:
    import pystray

    def open_library(icon=None, item=None):
        open_browser(root, url)

    def open_folder(icon=None, item=None):
        if os.name == "nt":
            os.startfile(root)  # type: ignore[attr-defined]

    def quit_app(icon, item=None):
        shutdown_event.set()
        try:
            icon.stop()
        except Exception:
            pass

    menu = pystray.Menu(
        pystray.MenuItem("打开 LocalHub", open_library, default=True),
        pystray.MenuItem("打开媒体文件夹", open_folder),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出 LocalHub", quit_app),
    )
    icon = pystray.Icon("LocalHub", create_tray_image(), "LocalHub · 本地媒体库", menu)
    icon.run()


def open_browser(root: Path, url: str) -> bool:
    """Best-effort browser launch. Browser integration must never own server lifetime."""
    if os.environ.get("LOCALHUB_NO_BROWSER", "").strip() == "1":
        return False
    try:
        opened = bool(webbrowser.open(url))
        if not opened:
            write_launcher_log(root, f"Browser launch returned false for {url}")
        return opened
    except Exception as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        write_launcher_log(root, "BROWSER FAILURE\n" + detail)
        return False


def start_tray_thread(root: Path, url: str, shutdown_event: threading.Event) -> threading.Thread:
    """Start the optional tray UI without allowing it to terminate the core server."""
    def tray_worker() -> None:
        failure: str | None = None
        try:
            run_tray(root, url, shutdown_event)
        except BaseException as exc:
            failure = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            write_launcher_log(root, "TRAY FAILURE\n" + failure)
        finally:
            if not shutdown_event.is_set():
                if failure is None:
                    write_launcher_log(
                        root,
                        "TRAY LOOP ENDED UNEXPECTEDLY\n"
                        "The tray UI returned without an Exit request. LocalHub will keep serving in the background.",
                    )

    thread = threading.Thread(target=tray_worker, name="LocalHubTray", daemon=True)
    thread.start()
    return thread


def wait_for_shutdown(server_thread: threading.Thread, shutdown_event: threading.Event) -> None:
    """Keep the process alive for the HTTP server even if the tray UI disappears."""
    while not shutdown_event.wait(0.5):
        if not server_thread.is_alive():
            raise RuntimeError("HTTP 服务线程意外退出。")


def main() -> int:
    root = media_root()
    if getattr(sys, "frozen", False):
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    mutex_handle, already_running = acquire_instance_mutex(root)
    if already_running:
        url = wait_existing_url(root)
        if url:
            open_browser(root, url)
            return 0
        show_error("LocalHub", "LocalHub 已经在启动中，请稍后再试。")
        return 0

    httpd = None
    shutdown_event = threading.Event()
    try:
        httpd, port = create_http_server(root)
        url = f"http://{HOST}:{port}/"
        thread = threading.Thread(
            target=httpd.serve_forever,
            kwargs={"poll_interval": 0.2},
            name="LocalHubServer",
            daemon=True,
        )
        thread.start()

        time.sleep(0.12)
        if not thread.is_alive():
            raise RuntimeError("HTTP 服务线程启动后立即退出。")

        write_runtime(root, port)
        try:
            (data_dir(root) / "startup-error.log").unlink(missing_ok=True)
            (data_dir(root) / "server-error.log").unlink(missing_ok=True)
            (data_dir(root) / "launcher-warning.log").unlink(missing_ok=True)
        except OSError:
            pass

        open_browser(root, url)
        start_tray_thread(root, url, shutdown_event)
        wait_for_shutdown(thread, shutdown_event)
        return 0
    except Exception as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log_path = write_startup_log(root, detail)
        message = f"{type(exc).__name__}: {exc}"
        if log_path:
            message += f"\n\n详细日志：{log_path}"
        show_error("LocalHub 启动失败", message)
        return 1
    finally:
        clear_runtime(root)
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        cleanup_runtime(root)
        if mutex_handle and os.name == "nt":
            ctypes.windll.kernel32.CloseHandle(mutex_handle)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main())
