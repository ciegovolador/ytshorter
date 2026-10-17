"""transcribe.py (F2) — subtítulos de YouTube primero (API + fallback yt-dlp), whisper local opcional.

Orden: subs ya bajados en el workdir → youtube-transcript-api (reintentos en
errores transitorios) → yt-dlp (json3/srt, reusa cookies) → faster-whisper.
El error final incluye el motivo real de cada vía (nunca "sin subtítulos" a ciegas).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

_CAPTION_ATTEMPTS = 3  # reintentos ante bloqueos transitorios de YouTube
_YTDLP_LANGS = ("es", "es-orig", "en", "en-orig")

# Clasificación por nombre: las clases de youtube-transcript-api cambian entre versiones.
_TRANSIENT = {
    "RequestBlocked", "IpBlocked", "TooManyRequests", "YouTubeRequestFailed",
    "YouTubeDataUnparsable", "ConnectionError", "ConnectTimeout", "ReadTimeout",
    "Timeout", "SSLError", "ChunkedEncodingError",
}


def _fetch_captions_once(api, video_id: str) -> list[dict]:
    """Un intento: list()+fetch() (API >=1.x) o get_transcript() (API vieja)."""
    try:
        tracks = api.list(video_id)
        transcript = None
        for pref in ("es", "en"):
            try:
                transcript = tracks.find_transcript([pref])
                break
            except Exception:
                continue
        if transcript is None:
            transcript = tracks.find_manually_created_transcript(
                [t.language_code for t in tracks])
        fetched = transcript.fetch()
    except AttributeError:  # API vieja sin list()
        from youtube_transcript_api import YouTubeTranscriptApi
        fetched = YouTubeTranscriptApi.get_transcript(video_id, languages=["es", "en"])
    segs = []
    for s in fetched:
        if isinstance(s, dict):  # API vieja
            segs.append({"start": float(s["start"]),
                         "end": float(s["start"] + s.get("duration", 2.0)),
                         "text": s["text"]})
        else:  # FetchedTranscriptSnippet (>=1.x)
            segs.append({"start": float(s.start),
                         "end": float(s.start + s.duration),
                         "text": s.text})
    return segs


def _try_youtube_captions(video_id: str) -> "tuple[list[dict] | None, str]":
    """API de subtítulos con reintentos. Devuelve (segmentos|None, motivo del fallo)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None, "youtube-transcript-api no instalado"
    api = YouTubeTranscriptApi()
    reason = "sin resultado"
    for attempt in range(1, _CAPTION_ATTEMPTS + 1):
        try:
            segs = _fetch_captions_once(api, video_id)
        except Exception as e:  # noqa: BLE001 — clasificamos por nombre (versiones varían)
            reason = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}".rstrip(": ")
            if type(e).__name__ not in _TRANSIENT:
                break
        else:
            if segs:
                return segs, ""
            reason = "sin segmentos usables"
            break
        if attempt < _CAPTION_ATTEMPTS:
            time.sleep(2 * attempt)
    return None, reason


def _dedupe_rolling(segs: list[dict]) -> list[dict]:
    """Colapsa repeticiones consecutivas (ventanas rodantes) y normaliza espacios."""
    out: list[dict] = []
    for s in segs:
        text = " ".join(s.get("text", "").split())
        if not text:
            continue
        if out and (text == out[-1]["text"] or text.startswith(out[-1]["text"])):
            out[-1]["text"] = text
            out[-1]["end"] = max(out[-1]["end"], float(s["end"]))
            continue
        out.append({"start": float(s["start"]), "end": float(s["end"]), "text": text})
    return out


def _parse_json3(text: str) -> list[dict]:
    """json3 de YouTube: eventos con `segs[].utf8` + `tStartMs`/`dDurationMs`."""
    events = json.loads(text).get("events", [])
    segs = []
    for ev in events:
        body = "".join(s.get("utf8", "") for s in ev.get("segs", []))
        if not body.strip():  # eventos de relleno (\n) o cabecera
            continue
        start = float(ev.get("tStartMs", 0)) / 1000.0
        dur = float(ev.get("dDurationMs") or 2000) / 1000.0
        segs.append({"start": start, "end": start + dur, "text": body})
    return _dedupe_rolling(segs)


def _parse_srt(text: str) -> list[dict]:
    segs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = re.search(
            r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", block)
        if not m:
            continue
        t = [int(x) for x in m.groups()]
        body = re.sub(r"<[^>]+>", "", block[m.end():]).strip()
        if not body:
            continue
        segs.append({"start": t[0] * 3600 + t[1] * 60 + t[2] + t[3] / 1000.0,
                     "end": t[4] * 3600 + t[5] * 60 + t[6] + t[7] / 1000.0,
                     "text": body})
    return _dedupe_rolling(segs)


def _load_local_subs(wd: Path) -> "list[dict] | None":
    """Subs ya bajados al workdir (`subs.<lang>.json3/.srt`), preferencia json3."""
    for pattern, parser in (("subs.*.json3", _parse_json3), ("subs.*.srt", _parse_srt)):
        for f in sorted(wd.glob(pattern)):
            try:
                segs = parser(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — un archivo corrupto no mata la etapa
                continue
            if segs:
                return segs
    return None


def _ytdlp_subs(video_id: str, wd: Path) -> "tuple[list[dict] | None, str]":
    """Fallback: baja subtítulos es/en con yt-dlp (reusa YT_SHORTER_COOKIES).

    Un idioma por intento: un 429 en `en` no invalida un `es` ya bajado.
    """
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        return None, "yt-dlp no instalado"
    cookies = os.getenv("YT_SHORTER_COOKIES", "")
    reason = "sin subtítulos es/en"
    for lang in _YTDLP_LANGS:
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "json3/srt/best",
            "outtmpl": str(wd / "subs.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 3,
            "socket_timeout": 30,
        }
        if cookies and Path(cookies).exists():
            opts["cookiefile"] = cookies
        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        except Exception as e:  # noqa: BLE001 — probamos el siguiente idioma
            reason = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}".rstrip(": ")
        segs = _load_local_subs(wd)
        if segs:
            return segs, ""
    return None, reason


def _extract_audio(video: Path, audio_wav: Path) -> None:
    audio_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video),
         "-ac", "1", "-ar", "16000", str(audio_wav)],
        check=True,
    )


def transcribe_workdir(workdir: str, whisper_model: str = "base",
                       use_yt_subs_first: bool = True, force: bool = False) -> dict:
    """Transcribe work/<id>/ → transcript.json. Idempotente salvo --force."""
    wd = Path(workdir)
    out = wd / "transcript.json"
    if out.exists() and not force:
        data = json.loads(out.read_text())
        return {"ok": True, "cached": True, "transcript": str(out),
                "segments": len(data.get("segments", [])),
                "source": data.get("source", "?")}

    video = wd / "source.mp4"
    info_path = wd / "info.json"
    video_id = wd.name
    if info_path.exists():
        try:
            video_id = json.loads(info_path.read_text()).get("id", wd.name)
        except Exception:
            pass

    segments: list[dict] = []
    source = "whisper"
    reasons: list[str] = []
    if use_yt_subs_first and len(str(video_id)) == 11:
        segments = _load_local_subs(wd) or []
        if segments:
            source = "yt-dlp-subs"
        if not segments:
            got, why = _try_youtube_captions(str(video_id))
            if got:
                segments, source = got, "youtube-captions"
            else:
                reasons.append(f"api {why}")
                got, why = _ytdlp_subs(str(video_id), wd)
                if got:
                    segments, source = got, "yt-dlp-subs"
                else:
                    reasons.append(f"yt-dlp {why}")
    elif use_yt_subs_first:
        reasons.append(f"video_id '{video_id}' no tiene 11 caracteres")

    if not segments:
        if not video.exists():
            return {"ok": False, "error": f"falta {video}"}
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            detail = "; ".join(reasons) if reasons else "sin intentos de subtítulos"
            return {"ok": False, "error": (
                f"sin subtítulos usables ({detail}) y faster-whisper no instalado "
                "(imagen slim): reintentá (los bloqueos de YouTube son transitorios), "
                "exportá YT_SHORTER_COOKIES si pide login, o usá el extra local "
                "(`pip install .[local]` / build con WITH_LOCAL=1)")}
        wav = wd / "audio16k.wav"
        _extract_audio(video, wav)
        model = WhisperModel(whisper_model, device="auto", compute_type="int8")
        transcribed, _ = model.transcribe(str(wav), word_timestamps=True, vad_filter=True)
        for s in transcribed:
            words = [{"start": w.start, "end": w.end, "word": w.word}
                     for w in (s.words or [])]
            segments.append({"start": float(s.start), "end": float(s.end),
                             "text": s.text.strip(), "words": words})

    out.write_text(json.dumps(
        {"video_id": video_id, "source": source, "segments": segments},
        ensure_ascii=False, indent=1,
    ))
    return {"ok": True, "cached": False, "transcript": str(out),
            "segments": len(segments), "source": source}
