# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

block_cipher = None

imageio_datas, imageio_binaries, imageio_hiddenimports = collect_all('imageio_ffmpeg')

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=imageio_binaries,
    datas=[
        ('smart_index.html', '.'),
        ('smart_ui.css', '.'),
        ('smart_ui.js', '.'),
        ('ux_enhancements.css', '.'),
        ('ux_enhancements.js', '.'),
        ('move_branding.js', '.'),
        ('recommendation_ui.js', '.'),
    ] + imageio_datas,
    hiddenimports=[
        'pystray._win32',
        'comtypes',
        'comtypes.automation',
    ] + imageio_hiddenimports,
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
    upx_exclude=[],
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
