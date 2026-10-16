"""transcribe.py (F2) — subtítulos de YouTube primero, fallback faster-whisper local."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _try_youtube_captions(video_id: str) -> list[dict] | None:
    """Devuelve segmentos [{start,end,text}] o None si no hay subtítulos usables."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    try:
        api = YouTubeTranscriptApi()
        # API nueva (>=1.x): list() + fetch(); API vieja: get_transcript(). Soportar ambas.
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
                    [t.language_code for t in tracks]
                )
            fetched = transcript.fetch()
        except AttributeError:
            fetched = YouTubeTranscriptApi.get_transcript(video_id, languages=["es", "en"])
        segs = []
        for s in fetched:
            if isinstance(s, dict):
                segs.append({"start": float(s["start"]),
                             "end": float(s["start"] + s.get("duration", 2.0)),
                             "text": s["text"]})
            else:  # FetchedTranscriptSnippet
                segs.append({"start": float(s.start),
                             "end": float(s.start + s.duration),
                             "text": s.text})
        return segs or None
    except Exception:
        return None


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
    if use_yt_subs_first and len(str(video_id)) == 11:
        got = _try_youtube_captions(video_id)
        if got:
            segments = got
            source = "youtube-captions"

    if not segments:
        if not video.exists():
            return {"ok": False, "error": f"falta {video}"}
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return {"ok": False, "error": (
                "sin subtítulos de YouTube y faster-whisper no instalado "
                "(imagen slim): usa un video con subtítulos o instala el extra "
                "local (`pip install .[local]` / build con WITH_LOCAL=1)")}
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
