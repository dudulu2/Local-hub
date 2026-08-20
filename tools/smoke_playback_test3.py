from __future__ import annotations

import inspect
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import compat_v3
import playback_guard


def validate_embedded_js() -> None:
    start = playback_guard.SCRIPT.find('>') + 1
    end = playback_guard.SCRIPT.rfind('</script>')
    source = playback_guard.SCRIPT[start:end]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'playback-guard.js'
        path.write_text(source, 'utf-8')
        result = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def main() -> None:
    ui = playback_guard.STYLE + playback_guard.SCRIPT
    assert 'SEEK_GUARD_MS=1500' in ui
    assert '__LOCALHUB_AUTO_COMPAT_DISABLED__' in ui
    assert '/api/compat/start' in ui
    assert 'object-fit:contain' in ui
    assert 'grid-template-rows:minmax(0,1fr) 54px' in ui
    assert '/api/recommend' not in ui
    assert 'SCHEDULER' not in ui
    validate_embedded_js()

    execute_source = inspect.getsource(compat_v3._execute)
    assert '+genpts+discardcorrupt' in execute_source
    assert 'setpts=PTS-STARTPTS' in execute_source
    assert 'expr:gte(t,n_forced*2)' in execute_source
    assert '+faststart' in execute_source
    assert '_validate_output' in execute_source

    start_source = inspect.getsource(compat_v3._start)
    assert 'video_codec == "h264"' in start_source
    assert 'mode = "transcode"' in start_source
    assert 'output.exists()' in start_source

    cleanup_source = inspect.getsource(compat_v3._cleanup_root)
    assert 'shutil.rmtree' not in cleanup_source
    print('Test3 playback isolation smoke test passed')


if __name__ == '__main__':
    main()
