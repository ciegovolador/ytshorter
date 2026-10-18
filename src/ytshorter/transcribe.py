"""transcribe.py (F2) — subtítulos de YouTube primero (yt-dlp/json3 + fallback API), whisper local opcional.

Orden: subs ya bajados en el workdir → yt-dlp (json3/srt, reusa cookies) →
youtube-transcript-api (solo texto, reintentos en errores transitorios) →
faster-whisper. yt-dlp va primero porque el json3 de auto-captions es la
única vía con word-timings (`segs[].tOffsetMs`) y de ahí sale la sincronía
del karaoke. El error final incluye el motivo real de cada vía (nunca
"sin subtítulos" a ciegas).
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

# Parseo/descarga de subtítulos vive en subs.py (json3 con words, srt, yt-dlp).
from .subs import (  # noqa: F401 — re-export histórico (tests y compat)
    _dedupe_rolling, _load_local_subs, _parse_json3, _parse_srt, _ytdlp_subs)

_CAPTION_ATTEMPTS = 3  # reintentos ante bloqueos transitorios de YouTube

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


def _extract_audio(video: Path, audio_wav: Path) -> None:
    audio_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video),
         "-ac", "1", "-ar", "16000", str(audio_wav)],
        check=True,
    )


def _enrich_words(wd: Path, data: dict) -> "list[dict] | None":
    """Transcript cacheado sin word-timings: reintenta json3 (local o yt-dlp).

    Los workdirs viejos (API vieja, solo texto) se arreglan solos en el
    próximo run sin exigir --force."""
    segs0 = data.get("segments") or []
    vid = str(data.get("video_id") or wd.name)
    if (data.get("source") not in ("youtube-captions", "yt-dlp-subs")
            or not segs0 or any(s.get("words") for s in segs0)
            or len(vid) != 11):
        return None
    local = _load_local_subs(wd)
    if local and any(s.get("words") for s in local):
        return local
    got, _why = _ytdlp_subs(vid, wd)
    if got and any(s.get("words") for s in got):
        return got
    return None


def transcribe_workdir(workdir: str, whisper_model: str = "base",
                       use_yt_subs_first: bool = True, force: bool = False) -> dict:
    """Transcribe work/<id>/ → transcript.json. Idempotente salvo --force."""
    wd = Path(workdir)
    out = wd / "transcript.json"
    if out.exists() and not force:
        data = json.loads(out.read_text())
        got = _enrich_words(wd, data)
        if got:
            data["segments"], data["source"] = got, "yt-dlp-subs"
            out.write_text(json.dumps(data, ensure_ascii=False, indent=1))
            return {"ok": True, "cached": False, "enriched": True,
                    "transcript": str(out), "segments": len(got),
                    "source": "yt-dlp-subs"}
        return {"ok": True, "cached": True, "transcript": str(out),
                "segments": len(data.get("segments", [])),
                "source": data.get("source", "?")}

    video = wd / "source.mp4"
    from .download import find_info_json

    info_path = find_info_json(wd)
    video_id = wd.name
    if info_path is not None:
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
            got, why = _ytdlp_subs(str(video_id), wd)  # json3: palabra real
            if got:
                segments, source = got, "yt-dlp-subs"
            else:
                reasons.append(f"yt-dlp {why}")
                got, why = _try_youtube_captions(str(video_id))
                if got:
                    segments, source = got, "youtube-captions"
                else:
                    reasons.append(f"api {why}")
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
