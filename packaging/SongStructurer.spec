# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller --noconfirm --clean packaging/SongStructurer.spec
# Every path is relative to this file, so the build works on any machine.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

here = Path(SPECPATH)

a = Analysis(
    [str(here / "launcher.py")],
    pathex=[str(here.parent / "src")],
    binaries=[],
    datas=collect_data_files("librosa"),
    hiddenimports=["matplotlib.backends.backend_tkagg"],
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["TkAgg", "Agg"]}},
    runtime_hooks=[],
    excludes=["pytest", "IPython", "PyQt5", "PyQt6", "PySide2", "PySide6", "pygame"],
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
    name="SongStructurer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed executables are routinely flagged by antivirus software.
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(here / "SongStructurer.ico"),
)
