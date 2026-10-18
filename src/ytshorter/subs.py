"""subs.py — parseo y descarga de subtítulos (json3 con words, srt, yt-dlp).

Extraído de transcribe.py: la única vía con word-timings reales es el json3
de auto-captions (`segs[].tOffsetMs` → `words`); de ahí sale la sincronía
del karaoke. Las ventanas rodantes se colapsan sin perder timings.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_YTDLP_LANGS = ("es", "es-orig", "en", "en-orig")


def _dedupe_rolling(segs: list[dict]) -> list[dict]:
    """Colapsa repeticiones consecutivas (ventanas rodantes) y normaliza espacios.

    Al fusionar ventanas crecientes, las `words` del evento nuevo (superset)
    reemplazan a las viejas: los timings reales nunca se pierden."""
    out: list[dict] = []
    for s in segs:
        text = " ".join(s.get("text", "").split())
        if not text:
            continue
        if out and (text == out[-1]["text"] or text.startswith(out[-1]["text"])):
            out[-1]["text"] = text
            out[-1]["end"] = max(out[-1]["end"], float(s["end"]))
            if s.get("words"):
                out[-1]["words"] = s["words"]
            continue
        seg = {"start": float(s["start"]), "end": float(s["end"]), "text": text}
        if s.get("words"):
            seg["words"] = s["words"]
        out.append(seg)
    return out


_LABEL = re.compile(r"\[[^\]]*\]")
_MUSIC = re.compile(r"[♪♫]")


def _speakable(text: str) -> str:
    """Texto sin etiquetas ([canto], ♪): lo que queda es lo realmente dicho."""
    return _MUSIC.sub(" ", _LABEL.sub(" ", text)).strip()


def _tokens_with_offsets(parts: list[dict]) -> list[tuple]:
    """(token, offset_ms|None) por palabra; las etiquetas no generan tokens."""
    out = []
    for p in parts:
        off = p.get("tOffsetMs")
        for tok in _speakable(p.get("utf8", "")).split():
            out.append((tok, off))
            off = None  # el offset aplica solo al inicio del fragmento
    return out


def _event_words(parts: list[dict], t0: float, t1: float) -> list[dict]:
    """Words con inicios reales (`tOffsetMs`); [] si el evento no los trae.

    El primer fragmento suele venir sin offset (= arranca en t0). Los finales
    encadenan al inicio de la palabra siguiente; el último queda en t1 y un
    pase posterior lo ajusta al inicio del próximo evento."""
    toks = _tokens_with_offsets(parts)
    if not toks or not any(off is not None for _, off in toks):
        return []
    words: list[dict] = []
    prev = t0
    for tok, off in toks:
        st = t0 + off / 1000.0 if off is not None else prev
        words.append({"start": st, "end": st, "word": tok})
        prev = st
    for i, w in enumerate(words):
        w["end"] = words[i + 1]["start"] if i + 1 < len(words) else t1
    return words


def _chain_words(segs: list[dict]) -> list[dict]:
    """Nada de karaoke 'encendido de más': cada palabra cierra donde arranca
    la siguiente, incluso cruzando eventos."""
    prev_last = None
    for s in segs:
        ws = s.get("words")
        if not ws:
            continue
        for i in range(len(ws) - 1):
            ws[i]["end"] = ws[i + 1]["start"]
        if prev_last is not None and ws[0]["start"] <= prev_last["end"]:
            prev_last["end"] = min(prev_last["end"], ws[0]["start"])
        prev_last = ws[-1]
    return segs


def _parse_json3(text: str) -> list[dict]:
    """json3 de YouTube: `tStartMs`/`dDurationMs` + `segs[].utf8`.

    Auto-captions traen `segs[].tOffsetMs` (inicio real por palabra): acá se
    materializan como `words`, la única fuente fiable de sincronía del karaoke.
    Eventos 100% etiqueta ([canto]) se descartan; etiquetas inline quedan en
    el texto pero no en las words."""
    events = json.loads(text).get("events", [])
    segs = []
    for ev in events:
        parts = [p for p in ev.get("segs", []) if p.get("utf8")]
        body = "".join(p.get("utf8", "") for p in parts)
        if not _speakable(body):  # relleno (\n) o pura etiqueta
            continue
        start = float(ev.get("tStartMs", 0)) / 1000.0
        dur = float(ev.get("dDurationMs") or 2000) / 1000.0
        seg = {"start": start, "end": start + dur, "text": " ".join(body.split())}
        words = _event_words(parts, start, start + dur)
        if words:
            seg["words"] = words
        segs.append(seg)
    return _chain_words(_dedupe_rolling(segs))


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
