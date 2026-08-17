from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PREFERRED_PORT = 8787
RUNTIME_FILE = "runtime.json"
ERROR_ALREADY_EXISTS = 183


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
        with urllib.request.urlopen(request, timeout=timeout) as response:
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


def wait_http(url: str, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if 200 <= response.status < 500:
                    return True
        except Exception:
            time.sleep(0.12)
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


def create_tray_image():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (12, 12, 13, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((3, 3, 61, 61), radius=14, fill=(255, 151, 0, 255))
    draw.rounded_rectangle((10, 10, 54, 54), radius=10, fill=(18, 18, 20, 255))
    draw.polygon(((27, 19), (27, 45), (47, 32)), fill=(255, 151, 0, 255))
    return image


def run_tray(root: Path, url: str) -> None:
    import pystray

    def open_library(icon=None, item=None):
        webbrowser.open(url)

    def open_folder(icon=None, item=None):
        if os.name == "nt":
            os.startfile(root)  # type: ignore[attr-defined]

    def quit_app(icon, item=None):
        clear_runtime(root)
        try:
            import smart_thumbnail
            smart_thumbnail.clear_memory_cache()
        except Exception:
            pass
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("打开 LocalHub", open_library, default=True),
        pystray.MenuItem("打开媒体文件夹", open_folder),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出 LocalHub", quit_app),
    )
    icon = pystray.Icon("LocalHub", create_tray_image(), "LocalHub · 本地媒体库", menu)
    icon.run()


def main() -> int:
    root = media_root()
    if getattr(sys, "frozen", False):
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    mutex_handle, already_running = acquire_instance_mutex(root)
    if already_running:
        url = wait_existing_url(root)
        if url:
            webbrowser.open(url)
            return 0
        show_error("LocalHub", "LocalHub 已经在启动中，请稍后再试。")
        return 0

    try:
        import server
        import smart_mode

        # LocalHub 2: the browser receives only the current page, while a
        # lightweight in-memory catalog handles search/folders/collections.
        smart_mode.install(server)

        port = server.pick_port(HOST, PREFERRED_PORT)
        url = f"http://{HOST}:{port}/"

        def serve() -> None:
            old_argv = list(sys.argv)
            try:
                sys.argv = [
                    "LocalHub",
                    "--root", str(root),
                    "--host", HOST,
                    "--port", str(port),
                    "--no-open",
                    "--quiet",
                ]
                server.main()
            finally:
                sys.argv = old_argv

        thread = threading.Thread(target=serve, name="LocalHubServer", daemon=True)
        thread.start()

        if not wait_http(url):
            show_error("LocalHub 启动失败", "本地服务没有成功启动。请检查 .localhub 目录或重新下载最新版。")
            return 1

        write_runtime(root, port)
        webbrowser.open(url)
        run_tray(root, url)
        return 0
    except Exception as exc:
        show_error("LocalHub 启动失败", str(exc))
        return 1
    finally:
        clear_runtime(root)
        if mutex_handle and os.name == "nt":
            ctypes.windll.kernel32.CloseHandle(mutex_handle)


if __name__ == "__main__":
    raise SystemExit(main())
