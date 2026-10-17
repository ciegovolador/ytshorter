"""doctor: verifica entorno (ffmpeg, yt-dlp, whisper, Gemini key). Solo diagnostica."""
from __future__ import annotations

import json
import shutil
import sys


def run_doctor(as_json: bool = False) -> int:
    from . import __version__
    from .config import load_settings

    settings = load_settings()
    try:
        import faster_whisper  # noqa: F401
        whisper_local = f"ok ({faster_whisper.__version__ if hasattr(faster_whisper, '__version__') else 'instalado'})"
    except ImportError:
        whisper_local = "MISSING (extra local no instalado; solo youtube-captions)"
    checks = {
        "version": __version__,
        "python": sys.version.split()[0],
        "ffmpeg": shutil.which("ffmpeg") or "MISSING",
        "ffprobe": shutil.which("ffprobe") or "MISSING",
        "yt-dlp": shutil.which("yt-dlp") or "MISSING (pip package ok)",
        "GEMINI_API_KEY": "set" if settings.llm_configured() else "MISSING",
        "GEMINI_MODEL": settings.gemini_model,
        "whisper_model": settings.whisper_model,
        "whisper_local": whisper_local,
    }
    ok = (
        checks["ffmpeg"] != "MISSING"
        and checks["ffprobe"] != "MISSING"
        and checks["GEMINI_API_KEY"] == "set"
    )
    if as_json:
        print(json.dumps({"ok": ok, "checks": checks}, indent=2))
    else:
        for k, v in checks.items():
            print(f"{k}: {v}")
        if not ok:
            print("\nFalta algo. Fija GEMINI_API_KEY y apt install ffmpeg.", file=sys.stderr)
    return 0 if ok else 1
