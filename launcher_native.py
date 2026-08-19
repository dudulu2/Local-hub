from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import launcher as base
import native_player

WINDOW_TITLE = "LocalHub 2.3 Native"


def focus_existing_window() -> bool:
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def native_self_test() -> int:
    base_result = base.self_test()
    if base_result:
        return base_result
    ok, _detail = native_player.self_test()
    return 0 if ok else 70


def main() -> int:
    root = base.media_root()
    if getattr(sys, "frozen", False):
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    mutex_handle, already_running = base.acquire_instance_mutex(root)
    if already_running:
        if not focus_existing_window():
            base.show_error("LocalHub", "LocalHub 已经在运行。")
        return 0

    httpd = None
    player_api = native_player.NativePlayerAPI(root)
    try:
        import webview

        httpd, port = base.create_http_server(root)
        url = f"http://{base.HOST}:{port}/"
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

        base.write_runtime(root, port)
        try:
            (base.data_dir(root) / "startup-error.log").unlink(missing_ok=True)
            (base.data_dir(root) / "server-error.log").unlink(missing_ok=True)
        except OSError:
            pass

        window = webview.create_window(
            WINDOW_TITLE,
            url=url,
            js_api=player_api,
            width=1420,
            height=900,
            min_size=(900, 620),
            background_color="#0b0b0c",
            text_select=True,
        )
        if window is None:
            raise RuntimeError("WebView2 窗口创建失败")

        def on_shown(*_args):
            # Alpha2 attach only creates the WinForms video panel. libmpv itself
            # is initialized by a daemon worker after this GUI callback returns.
            player_api.attach(window)

        def on_loaded(*_args):
            try:
                script = (
                    Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
                    / "native_player_ui.js"
                ).read_text("utf-8")
                window.evaluate_js(script)
            except Exception as exc:
                player_api.error = f"原生播放器 UI 注入失败：{exc}"

        def on_closed(*_args):
            # Never wait for libmpv from the GUI close callback. A stuck driver
            # must not turn the LocalHub window into a non-responsive window.
            player_api.shutdown(wait=False)

        window.events.shown += on_shown
        window.events.loaded += on_loaded
        window.events.closed += on_closed

        # Explicitly use Edge Chromium/WebView2 for the HTML library shell.
        # libmpv video pixels are rendered in a separate native child surface.
        webview.start(gui="edgechromium", debug=False)
        return 0
    except Exception as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log_path = base.write_startup_log(root, detail)
        message = f"{type(exc).__name__}: {exc}"
        if log_path:
            message += f"\n\n详细日志：{log_path}"
        base.show_error("LocalHub Native 启动失败", message)
        return 1
    finally:
        # The GUI loop is already gone here, so a short bounded wait is safe.
        # The mpv thread is daemonized and cannot prevent process exit.
        player_api.shutdown(wait=True, timeout=1.0)
        base.clear_runtime(root)
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        if mutex_handle and os.name == "nt":
            ctypes.windll.kernel32.CloseHandle(mutex_handle)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(native_self_test())
    raise SystemExit(main())
