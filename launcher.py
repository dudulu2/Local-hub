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
    temp.write_text(json.dumps({"pid": os.getpid(), "port": port, "root": str(root)}, ensure_ascii=False, indent=2), "utf-8")
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


def configure_server(root: Path):
    import server
    import smart_mode
    import catalog_cache
    import preview_support
    import compat_support
    import rating_support
    import recommendation_support
    import io_support
    import auto_tag_support
    import auto_tag_v2
    import siglip_support

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
    # Install SigLIP first so AI Tag V2 wraps the fully-patched manager/handler.
    siglip_support.install(server, auto_tag_support)
    auto_tag_v2.install(server, auto_tag_support)
    cleanup_compat_cache(root)
    return server


def create_http_server(root: Path):
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
    httpd = None
    try:
        import server
        import compat_support
        import recommendation_support
        import auto_tag_support
        import auto_tag_v2
        import siglip_support
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
        if not callable(getattr(auto_tag_v2, "install", None)):
            return 16
        return 0
    except Exception:
        return 99


# Remaining launcher runtime functions are unchanged in behavior.

def main() -> int:
    root = media_root()
    httpd, port = create_http_server(root)
    base = f"http://{HOST}:{port}"
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    if not wait_health(base, 8.0):
        return 2
    webbrowser.open(base + "/")
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
