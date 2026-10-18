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


def find_info_json(dest) -> "Path | None":
    """Ubica el sidecar de yt-dlp: el real es `source.info.json` (el opt
    `infojson_filename` se ignora y el template antepone `source.`);
    tolera el legado `info.json`."""
    for name in ("source.info.json", "info.json"):
        p = Path(dest) / name
        if p.exists():
            return p
    return None


def download_url(url: str, out_root: str = "work", force: bool = False) -> dict:
    """Descarga video+audio merge mp4 en work/<id>/source.mp4 + source.info.json. Idempotente."""
    from yt_dlp import YoutubeDL

    vid = extract_video_id(url)
    if vid == "unknown":
        return {"ok": False, "cached": False, "video_id": vid,
                "error": "URL sin video_id válido de 11 caracteres (¿link truncado?)"}
    dest = Path(out_root) / vid
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "source.mp4"
    info_path = find_info_json(dest)

    if target.exists() and info_path is not None and not force:
        try:
            info = json.loads(info_path.read_text())
            return {"ok": True, "cached": True, "video_id": vid,
                    "video": str(target), "info": str(info_path),
                    "title": info.get("title", ""), "duration": info.get("duration", 0)}
        except (OSError, ValueError):
            print("[download] sidecar info corrupto, re-descargando", file=sys.stderr)

    opts = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest / "source.%(ext)s"),
        "writeinfojson": True,  # cae en source.info.json (mismo template)
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

    # yt-dlp puede dejar source.webm según formato; normalizar a source.mp4 ya
    # pedido con merge. Solo extensiones de video (nunca source.info.json/.part).
    if not target.exists():
        exts = (".mp4", ".mkv", ".mov", ".m4v", ".webm")
        cands = [p for p in dest.glob("source.*") if p.suffix.lower() in exts]
        if not cands:
            return {"ok": False, "cached": False, "video_id": vid,
                    "error": "descarga sin archivo de video"}
        cands.sort(key=lambda p: exts.index(p.suffix.lower()))
        cands[0].rename(target)
    info_path = find_info_json(dest)
    info = json.loads(info_path.read_text()) if info_path is not None else {}
    return {"ok": True, "cached": False, "video_id": vid,
            "video": str(target), "info": str(info_path or ""),
            "title": info.get("title", ""), "duration": info.get("duration", 0)}
