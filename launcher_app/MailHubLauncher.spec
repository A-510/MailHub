# -*- mode: python ; coding: utf-8 -*-
"""MailHub Launcher PyInstaller 单文件打包配置。"""

from pathlib import Path

ROOT_DIR = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT_DIR / "launcher_app" / "main.py")],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=[
        (str(ROOT_DIR / "launcher_app" / "assets"), "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy",
        "scipy",
        "pandas",
        "matplotlib",
        "torch",
        "cv2",
        "PIL",
        "tkinter",
        "PyQt5",
        "PySide6",
        "pytest",
    ],
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
    name="MailHubLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT_DIR / "launcher_app" / "assets" / "app_icon.ico"),
)
