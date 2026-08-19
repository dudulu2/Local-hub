# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None

imageio_datas, imageio_binaries, imageio_hiddenimports = collect_all('imageio_ffmpeg')
webview_datas, webview_binaries, webview_hiddenimports = collect_all('webview')
pythonnet_datas, pythonnet_binaries, pythonnet_hiddenimports = collect_all('pythonnet')
clr_datas, clr_binaries, clr_hiddenimports = collect_all('clr_loader')

native_binaries = []
libmpv = Path('vendor/libmpv-2.dll')
if libmpv.exists():
    native_binaries.append((str(libmpv), '.'))

a = Analysis(
    ['launcher_native.py'],
    pathex=[],
    binaries=imageio_binaries + webview_binaries + pythonnet_binaries + clr_binaries + native_binaries,
    datas=[
        ('smart_index.html', '.'),
        ('smart_ui.css', '.'),
        ('smart_ui.js', '.'),
        ('ux_enhancements.css', '.'),
        ('ux_enhancements.js', '.'),
        ('move_branding.js', '.'),
        ('recommendation_ui.js', '.'),
        ('native_player_ui.js', '.'),
        ('THIRD_PARTY_NOTICES.md', '.'),
    ] + imageio_datas + webview_datas + pythonnet_datas + clr_datas,
    hiddenimports=[
        'comtypes',
        'comtypes.automation',
    ] + imageio_hiddenimports + webview_hiddenimports + pythonnet_hiddenimports + clr_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LocalHub',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['libmpv-2.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='build_assets/localhub.ico',
    version='version_info.txt',
)
