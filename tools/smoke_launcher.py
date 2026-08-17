import sys
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

print("launcher startup cleanup smoke test passed")
