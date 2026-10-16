"""download.py (F2) — wrapper yt-dlp idempotente. Una sola forma de descargar."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

MAX_ATTEMPTS = 3  # reintentos a nivel pipeline (yt-dlp además reintenta fragmentos)


def extract_video_id(url: str) -> str:
    """Extrae el ID de 11 chars de una URL de YouTube, o 'local' si es archivo."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    p = Path(url)
    if p.exists():
        return p.stem[:32] or "local"
    return "unknown"


def download_url(url: str, out_root: str = "work", force: bool = False) -> dict:
    """Descarga video+audio merge mp4 en work/<id>/source.mp4 + info.json. Idempotente."""
    from yt_dlp import YoutubeDL

    vid = extract_video_id(url)
    if vid == "unknown":
        return {"ok": False, "cached": False, "video_id": vid,
                "error": "URL sin video_id válido de 11 caracteres (¿link truncado?)"}
    dest = Path(out_root) / vid
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "source.mp4"
    info_path = dest / "info.json"

    if target.exists() and info_path.exists() and not force:
        try:
            info = json.loads(info_path.read_text())
            return {"ok": True, "cached": True, "video_id": vid,
                    "video": str(target), "info": str(info_path),
                    "title": info.get("title", ""), "duration": info.get("duration", 0)}
        except (OSError, ValueError):
            print("[download] info.json corrupto, re-descargando", file=sys.stderr)

    opts = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest / "source.%(ext)s"),
        "writeinfojson": True,
        "infojson_filename": str(info_path),
        "restrictfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # Red flaky (Read timed out en googlevideo): reintentos con backoff.
        # Los .part se conservan entre intentos: yt-dlp retoma, no re-descarga.
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 60,
    }
    # Si YouTube pide login/bot-check, el usuario puede exportar cookies (YAGNI: manual por ahora).
    import os

    cookies = os.getenv("YT_SHORTER_COOKIES", "")
    if cookies and Path(cookies).exists():
        opts["cookiefile"] = cookies

    last_err = "desconocido"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
            break
        except Exception as e:  # noqa: BLE001 — cualquier fallo de red/antibot
            last_err = str(e)[-300:]
            print(f"[download] intento {attempt}/{MAX_ATTEMPTS} falló: {last_err}",
                  file=sys.stderr)
            if attempt < MAX_ATTEMPTS:
                time.sleep(5 * attempt)
    else:
        return {"ok": False, "cached": False, "video_id": vid,
                "error": f"descarga falló tras {MAX_ATTEMPTS} intentos: {last_err}"}

    # yt-dlp puede dejar source.webm según formato; normalizar a source.mp4 ya pedido con merge.
    if not target.exists():
        cands = sorted(dest.glob("source.*"))
        if not cands:
            return {"ok": False, "cached": False, "video_id": vid, "error": "descarga sin archivo"}
        cands[0].rename(target)
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    return {"ok": True, "cached": False, "video_id": vid,
            "video": str(target), "info": str(info_path),
            "title": info.get("title", ""), "duration": info.get("duration", 0)}
