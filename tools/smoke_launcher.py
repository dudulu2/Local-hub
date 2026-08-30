import json
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import launcher


class EmptyCompat:
    pass


class RootCompat:
    called = False

    @staticmethod
    def cleanup_root(root: Path) -> None:
        RootCompat.called = True
        assert root.exists()


# The historical failure was an AttributeError when a cleanup helper was
# renamed. The launcher must tolerate a compat module with no known cleanup
# helper at all.
with TemporaryDirectory() as tmp:
    root = Path(tmp)

    original_import = __import__
    try:
        import builtins

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "compat_support":
                return EmptyCompat
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = fake_import
        launcher.cleanup_compat_cache(root)
    finally:
        builtins.__import__ = original_import

    try:
        import builtins

        def fake_import_root(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "compat_support":
                return RootCompat
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = fake_import_root
        launcher.cleanup_compat_cache(root)
    finally:
        builtins.__import__ = original_import

    assert RootCompat.called, "cleanup_root was not called"


# Regression: a tray backend may return immediately without raising. That must
# be treated as a non-fatal UI failure; it must not signal the core server to
# stop. Persist a warning so packaged failures remain diagnosable.
with TemporaryDirectory() as tmp:
    root = Path(tmp)
    shutdown_event = threading.Event()
    original_run_tray = launcher.run_tray

    try:
        launcher.run_tray = lambda root, url, event: None
        tray_thread = launcher.start_tray_thread(root, "http://127.0.0.1:8787/", shutdown_event)
        tray_thread.join(timeout=2.0)

        assert not tray_thread.is_alive(), "fake tray thread did not return"
        assert not shutdown_event.is_set(), "unexpected tray return must not stop LocalHub"

        warning_log = root / ".localhub" / "launcher-warning.log"
        assert warning_log.exists(), "unexpected tray return was not logged"
        warning_text = warning_log.read_text("utf-8")
        assert "TRAY LOOP ENDED UNEXPECTEDLY" in warning_text
    finally:
        launcher.run_tray = original_run_tray


# Browser launch is auxiliary too. A browser integration failure must be logged
# and reported as False rather than propagating into main server shutdown.
with TemporaryDirectory() as tmp:
    root = Path(tmp)
    original_web_open = launcher.webbrowser.open

    try:
        def fail_browser(url):
            raise RuntimeError("simulated browser failure")

        launcher.webbrowser.open = fail_browser
        assert launcher.open_browser(root, "http://127.0.0.1:8787/") is False
        warning_log = root / ".localhub" / "launcher-warning.log"
        assert warning_log.exists(), "browser failure was not logged"
        assert "BROWSER FAILURE" in warning_log.read_text("utf-8")
    finally:
        launcher.webbrowser.open = original_web_open


# The real launcher composition must include the dedicated AI Center, its
# persistent Tag-group settings API, and the default balanced background mode.
# This catches wiring errors before PyInstaller runs.
with TemporaryDirectory() as tmp:
    root = Path(tmp)
    httpd, port = launcher.create_http_server(root)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        assert launcher.wait_health(base, 5.0), "AI-center launcher server did not become healthy"
        with launcher.local_urlopen(base + "/", timeout=5.0) as response:
            html = response.read().decode("utf-8")
        assert "/ai_center.js" in html and "/ai_center.css" in html, "AI Center assets are not injected"
        assert 'id="tagCategoryNav"' in html and "Tag / 分类" in html, "Tag/category sidebar entry is missing"
        assert '<button data-route="packs"><span>▦</span>图包 / 图册</button>' not in html, "legacy image-pack sidebar entry returned"

        with launcher.local_urlopen(base + "/api/ai/overview", timeout=5.0) as response:
            overview = json.loads(response.read().decode("utf-8"))
        assert overview.get("ok") is True, "AI overview endpoint is unavailable"
        assert overview["settings"]["backgroundMode"] == "balanced"
        group_names = [group.get("name") for group in overview["settings"].get("groups", [])]
        for expected in ("全部视频", "生活", "学习", "风景", "娱乐", "色情"):
            assert expected in group_names, f"missing default AI Tag group: {expected}"

        import ai_balanced_siglip
        import siglip_encoder
        assert ai_balanced_siglip.get_mode(root) == "balanced", "balanced AI mode was not activated"
        assert getattr(siglip_encoder.SiglipOnnxEncoder, "_localhub_balanced_playback_patched", False) is True
    finally:
        httpd.shutdown()
        thread.join(timeout=2.0)
        httpd.server_close()


print("launcher startup cleanup, lifecycle, AI-center, Tag-navigation, and balanced-playback smoke test passed")
