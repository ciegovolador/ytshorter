# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec del .exe Windows: onefile, prompts/web/ffmpeg embebidos."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parents[1]  # packaging/windows -> raíz del repo

datas = [
    (str(ROOT / "prompts"), "prompts"),
    (str(ROOT / "web" / "static"), "web/static"),
]
binaries = []
hiddenimports = []

vend = ROOT / "packaging" / "windows" / "vendor"  # ffmpeg.exe/ffprobe.exe (CI)
for name in ("ffmpeg.exe", "ffprobe.exe"):
    if (vend / name).exists():
        binaries.append((str(vend / name), "."))

# Paquetes con imports dinámicos que el análisis estático no ve.
for pkg in ("google.genai", "uvicorn", "fastapi", "yt_dlp",
            "youtube_transcript_api", "websockets"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ytshorter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
