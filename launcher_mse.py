from __future__ import annotations

import sys
from pathlib import Path

import launcher as base
import mse_support


_original_configure_server = base.configure_server
_original_cleanup_compat_cache = base.cleanup_compat_cache


def cleanup_media_experiments(root: Path) -> None:
    _original_cleanup_compat_cache(root)
    mse_support.cleanup_root(root)


def configure_server_with_mse(root: Path):
    server = _original_configure_server(root)
    # Install MSE last so its experimental root page can omit RC4's automatic
    # MP4-remux health guard while retaining every other RC4 server layer.
    mse_support.install(server)
    return server


base.cleanup_compat_cache = cleanup_media_experiments
base.configure_server = configure_server_with_mse


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(base.self_test())
    raise SystemExit(base.main())
