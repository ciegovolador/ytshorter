"""caption.py (F4) — orquestación: .srt/.ass por clip + quemado + thumbnail.

El estilo/karaoke vive en subtitles.py; el quemado ffmpeg en burn.py. Acá:
recorte de segmentos al clip, armado de words y recorrido de work/short_XX/.
"""
from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .burn import _ass_vf, burn_and_thumb  # noqa: F401 — re-export histórico
from .clip import encode_workers
from .subtitles import (  # noqa: F401 — API histórica (tests/CLI): no usar en código nuevo
    BLACK, FONT_SIZE, HOLD_S, LEAD_S, MARGIN_V, MAX_LINES, MAX_LINE_UNITS,
    MAX_WORDS_LINE, MIN_EVENT_S, MIN_WORD_S, OUTLINE, SHADOW, SHADOW_C, WHITE,
    YELLOW, _clean, _estimate_words, _first_text, _karaoke_lines, _line_units,
    _render_lines, _unit_width, chunk_words, fmt_ass, fmt_srt, pick_font,
    split_lines, to_ass, to_srt, words_of)


def clip_segments(transcript: list[dict], start: float, end: float) -> list[dict]:
    """Segmentos solapados con [start,end], recortados y relativos a 0 (con words)."""
    out = []
    for s in transcript:
        if s["end"] <= start or s["start"] >= end:
            continue
        words = []
        dur = end - start
        for w in s.get("words") or []:
            ws, we = float(w["start"]) - start, float(w["end"]) - start
            # recorta palabras a medio decir en el borde (si no, el caption
            # muestra texto cuyo audio quedó fuera del corte)
            if we < 0.3 or ws > dur - 0.3 or not w.get("word", "").strip():
                continue
            words.append({"start": max(0.0, ws), "end": min(dur, we),
                          "text": w["word"].strip()})
        text = s.get("text", "").strip()
        if text and (min(end, s["end"]) - start) > max(0.0, s["start"] - start):
            out.append({"start": max(0.0, s["start"] - start),
                        "end": min(end, s["end"]) - start,
                        "text": text, "words": words})
    return [s for s in out if s["text"] and s["end"] > s["start"]]


def caption_all(workdir: str, force: bool = False, on_item=None, on_tick=None) -> dict:
    wd = Path(workdir)
    clips_path = wd / "clips.json"
    tpath = wd / "transcript.json"
    if not clips_path.exists():
        return {"ok": False, "error": f"falta {clips_path} (corre analyze primero)"}
    transcript = []
    if tpath.exists():
        transcript = json.loads(tpath.read_text(encoding="utf-8")).get("segments", [])

    clips = json.loads(clips_path.read_text(encoding="utf-8")).get("clips", [])
    total = len(clips)
    workers = encode_workers()
    tick = on_tick if workers == 1 else None

    def process(i: int, c: dict) -> dict:
        cid = c.get("id") or f"short_{i + 1:02d}"
        cdir = wd / cid
        if not (cdir / "cut.mp4").exists():
            raise RuntimeError(f"falta {cdir / 'cut.mp4'} (corre clip primero)")
        segs = clip_segments(transcript, float(c["start"]), float(c["end"]))
        (cdir / "subtitles.srt").write_text(to_srt(segs), encoding="utf-8")
        (cdir / "subtitles.ass").write_text(to_ass(segs), encoding="utf-8")
        try:
            dur = max(float(c["end"]) - float(c["start"]), 0.0)
            r = burn_and_thumb(cdir, force=force, total_s=dur, on_tick=tick)
        except subprocess.CalledProcessError as e:
            (cdir / "video.mp4").unlink(missing_ok=True)  # no dejar parcial
            raise RuntimeError(f"ffmpeg caption {cid}: {e}") from e
        if r.get("error"):
            raise RuntimeError(f"caption {cid}: {r['error']}")
        return r

    done_by_idx: dict[int, dict] = {}
    error: str | None = None
    if workers > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(process, i, c): i for i, c in enumerate(clips)}
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    done_by_idx[i] = fut.result()
                except Exception as e:  # noqa: BLE001 — primer error gana
                    error = str(e)
                    for f2 in futs:
                        f2.cancel()
                    break
                if on_item:
                    r = done_by_idx[i]
                    on_item(i + 1, total, r.get("id") or clips[i].get("id"),
                            bool(r.get("cached")))
    else:
        for i, c in enumerate(clips):
            try:
                done_by_idx[i] = process(i, c)
            except Exception as e:  # noqa: BLE001
                error = str(e)
                break
            if on_item:
                r = done_by_idx[i]
                on_item(i + 1, total, r.get("id") or clips[i].get("id"),
                        bool(r.get("cached")))
    if error:
        return {"ok": False, "error": error}
    return {"ok": True, "videos": [done_by_idx[i] for i in sorted(done_by_idx)]}
