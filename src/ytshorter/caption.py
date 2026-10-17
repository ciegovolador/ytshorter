"""caption.py (F4) — .srt/.ass por clip + quemado en video.mp4 + thumbnail.jpg.

Estilo marketing 2026 (Hormozi/Submagic): karaoke palabra-por-palabra (`\\k`,
amarillo sobre blanco), 2-4 palabras por línea, máx 2 líneas, bold pesada a
~8% del frame, tercio medio-bajo. 15-20 CPS, mín 0.5s por bloque.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# --- estilo marketing (canon short-form 2026) ---
FONT_SIZE = 84          # ~8% del frame en 1080x1920
OUTLINE = 6             # ~7% del fontsize: legible sobre cualquier fondo
SHADOW = 2
MARGIN_V = 480          # baseline ~75% de altura: libre del UI de TikTok/Reels
MAX_WORDS_LINE = 4
MAX_LINES = 2           # nunca 3 líneas
MAX_LINE_UNITS = 20.0   # ancho máximo renderizado por línea (~20 chars promedio)
MIN_WORD_S = 0.12       # palabra más corta visible
LEAD_S = 0.04           # la palabra aparece un pelo antes de sonar
HOLD_S = 0.20           # última palabra aguanta +200ms (anti-parpadeo)
MIN_EVENT_S = 0.5
YELLOW = "&H0000EBFF"   # #FFEB00 en ABGR: palabra ya dicha (highlight)
WHITE = "&H00FFFFFF"    # palabra por decir
BLACK = "&H00000000"
SHADOW_C = "&H99000000"


def pick_font() -> str:
    """Familia pesada disponible: Montserrat > Inter > Poppins > DejaVu."""
    override = os.getenv("YT_SHORTER_FONT", "")
    if override:
        return override
    roots = [Path("/usr/share/fonts"), Path.home() / ".fonts"]
    files = set()
    for r in roots:
        if r.exists():
            files.update(p.name.lower() for p in r.rglob("*.ttf"))
            files.update(p.name.lower() for p in r.rglob("*.otf"))
    for family, needles in (
        ("Montserrat", ("montserrat-extrabold", "montserrat-black", "montserrat-bold")),
        ("Inter", ("inter-bold", "inter-black")),
        ("Poppins", ("poppins-bold", "poppins-black")),
    ):
        if any(any(n in f for n in needles) for f in files):
            return family
    return "DejaVu Sans"


def fmt_srt(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_ass(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


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


def _estimate_words(text: str, start: float, end: float) -> list[dict]:
    """Reparte la duración por palabra ponderando por caracteres (sin word-timings)."""
    toks = [t for t in text.split() if t]
    if not toks:
        return []
    weights = [max(len(t), 1) for t in toks]
    total = sum(weights)
    span = max(end - start, 0.01)
    out, t = [], start
    for i, tok in enumerate(toks):
        d = span * weights[i] / total
        w_end = end if i == len(toks) - 1 else t + d
        out.append({"start": t, "end": w_end, "text": tok})
        t = w_end
    return out


def words_of(segments: list[dict]) -> list[dict]:
    """Palabras {start,end,text} con timeline global monótono y texto en orden.

    Whisper emite segmentos rolling: cada uno arranca ~2.5s antes de que cierre
    el anterior, así que el audio real del segmento n es [start_n, start_{n+1}]
    (su `end` infla con solape). Acá cada segmento se recorta a esa ventana
    efectiva; words de whisper dentro de la ventana se conservan, y si el
    segmento venía solapado se re-reparten proporcionalmente (mismo texto,
    mismo orden). Ventanas vacías (segmento dentro de lo ya cubierto) se
    descartan: era la fuente de CPS basura y karaoke con 2 palabras encendidas."""
    segs = [s for s in segments if float(s["end"]) > float(s["start"])]
    out: list[dict] = []
    prev_end = 0.0
    for i, s in enumerate(segs):
        s0, s1 = float(s["start"]), float(s["end"])
        if i + 1 < len(segs):
            nxt = float(segs[i + 1]["start"])
            if s0 < nxt < s1:
                s1 = nxt  # el `end` rolling no es audio propio: es solape
        w0 = max(s0, prev_end)
        overlapped = s0 < prev_end
        prev_end = max(prev_end, s1)
        if s1 <= w0:
            continue  # ventana vacía: el segmento cae dentro de lo ya cubierto
        ws = [w for w in (s.get("words") or [])
              if (w.get("word") or w.get("text") or "").strip()
              and float(w["end"]) > float(w["start"])]
        if not ws:
            out.extend(_estimate_words(s["text"], w0, s1))
        elif not overlapped:
            for w in ws:
                out.append({"start": float(w["start"]), "end": float(w["end"]),
                            "text": (w.get("word") or w.get("text")).strip()})
        else:
            span = s1 - w0
            weights = [max(len((w.get("word") or w.get("text")).strip()), 1)
                       for w in ws]
            total = sum(weights)
            t = w0
            for w, wt in zip(ws, weights):
                d = span * wt / total
                out.append({"start": t, "end": t + d,
                            "text": (w.get("word") or w.get("text")).strip()})
                t += d
    t = 0.0
    for w in out:
        if w["start"] < t:
            w["start"] = t
        if w["end"] <= w["start"]:
            w["end"] = w["start"] + MIN_WORD_S
        t = w["end"]
    return out


def chunk_words(words: list[dict], max_words: int = MAX_WORDS_LINE * MAX_LINES) -> list[list[dict]]:
    """Bloques de ≤8 palabras = ≤2 líneas renderizadas (≤4 palabras y ≤ ancho
    por línea). Se achica el bloque si una línea quedaría fuera de ancho o si
    pediría una 3ª fila: así libass nunca re-envuelve el texto."""
    chunks: list[list[dict]] = []
    i = 0
    while i < len(words):
        chunk = words[i:i + max_words]
        while len(chunk) > 1:
            lines = _render_lines(chunk)
            if len(lines) <= MAX_LINES and _line_units(lines[-1]) <= MAX_LINE_UNITS:
                break
            chunk = chunk[:-1]
        chunks.append(chunk)
        i += len(chunk)
    return chunks


def _clean(t: str) -> str:
    return " ".join(t.replace("{", "(").replace("}", ")").split())


def _unit_width(text: str) -> float:
    """Ancho relativo en 'unidades de carácter' para Montserrat bold 84px.

    Caracteres angostos pesan la mitad; anchos (m,w,M,W) 1.4×. Sirve para
    garantizar que una línea no supere el ancho del frame y se auto-envuelva
    a una 3ª fila (libass no debe re-wrappear lo que ya partimos)."""
    total = 0.0
    for ch in text:
        if ch in "mwMW":
            total += 1.4
        elif ch in "iljI.,;:!'|¿?()[]{}":
            total += 0.5
        else:
            total += 1.0
    return total


def _line_units(line: list[dict]) -> float:
    if not line:
        return 0.0
    return sum(_unit_width(_clean(w["text"])) for w in line) + (len(line) - 1)


DANGLERS = frozenset(  # nunca cerrar línea con estas (se cuelgan a la siguiente)
    "el la los las un una de del en y e ni que con por para se su sus al lo "
    "a mi tu the a an to of in on and or".split())


def _render_lines(chunk: list[dict]) -> list[list[dict]]:
    """Líneas de ≤4 palabras y ≤ MAX_LINE_UNITS de ancho, sin colgadas al cierre.

    El fill es codicioso y determinista (prefijo), así que llamar `_render_lines`
    sobre un chunk reproducen exactamente las líneas con que `chunk_words` armó
    ese chunk."""
    lines: list[list[dict]] = []
    cur: list[dict] = []
    for w in chunk:
        trial = cur + [w]
        if len(trial) > MAX_WORDS_LINE or (cur and _line_units(trial) > MAX_LINE_UNITS):
            lines.append(cur)
            cur = [w]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    out, carry = [], None
    for i, ln in enumerate(lines):
        if carry is not None:
            ln = [carry] + ln
            carry = None
        if i + 1 < len(lines) and ln:
            last = _clean(ln[-1]["text"]).rstrip(",;:.!?…").lower()
            if last in DANGLERS:
                carry = ln.pop()
        if ln:
            out.append(ln)
    return out


def split_lines(chunk: list[dict]) -> list[list[dict]]:
    """Grupos de ≤4 palabras sin colgadas, con ancho acotado. Además la primera
    palabra de cada línea pierde puntuación inicial (,;:) — en pantalla una
    línea jamás empieza con coma."""
    return _render_lines(chunk)


def _first_text(w: dict, first: bool) -> str:
    t = _clean(w["text"])
    return t.lstrip(",;:. ") if first else t


def to_srt(segments: list[dict]) -> str:
    chunks = chunk_words(words_of(segments))
    lines = []
    for n, ch in enumerate(chunks, 1):
        start = max(ch[0]["start"] - LEAD_S, 0.0)
        end = ch[-1]["end"] + HOLD_S
        if n < len(chunks):
            end = min(end, chunks[n][0]["start"] - LEAD_S)
        end = max(end, start + MIN_EVENT_S)
        body = [" ".join(_first_text(w, i == 0) for i, w in enumerate(ln))
                for ln in split_lines(ch)]
        lines += [str(n), f"{fmt_srt(start)} --> {fmt_srt(end)}", *body, ""]
    return "\n".join(lines)


def _karaoke(ch: list[dict], start: float, end: float) -> str:
    """Texto con `\\k` por palabra; cada sweep llega al inicio de la siguiente
    (absorbe silencios, el amarillo nunca retrocede a mitad de línea)."""
    parts = []
    for i, w in enumerate(ch):
        nxt = ch[i + 1]["start"] if i + 1 < len(ch) else end
        cs = max(1, round((max(nxt, w["start"] + MIN_WORD_S) - w["start"]) * 100))
        parts.append(f"{{\\k{cs}}}{_first_text(w, i == 0)}")
    return " ".join(parts)


def to_ass(segments: list[dict], font: str | None = None) -> str:
    font = font or pick_font()
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Short,{font},{FONT_SIZE},{YELLOW},{WHITE},{BLACK},{SHADOW_C},"
        f"-1,0,0,0,100,100,0,0,1,{OUTLINE},{SHADOW},2,80,80,{MARGIN_V},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    chunks = chunk_words(words_of(segments))
    body = []
    prev_end = 0.0
    for n, ch in enumerate(chunks):
        start = max(ch[0]["start"] - LEAD_S, prev_end)
        end = ch[-1]["end"] + HOLD_S
        if n + 1 < len(chunks):
            end = min(end, chunks[n + 1][0]["start"] - LEAD_S)
        end = max(end, start + MIN_EVENT_S)
        if end <= start:
            continue
        lines = [_karaoke(ln, start, end) for ln in split_lines(ch)]
        body.append(f"Dialogue: 0,{fmt_ass(start)},{fmt_ass(end)},Short,,0,0,0,,"
                    + r"\N".join(lines))
        prev_end = end
    return head + "\n".join(body) + "\n"


def _ass_vf(ass_path: Path) -> str:
    # filtro ass= necesita ':' y "'" escapados en el path
    esc = str(ass_path).replace(":", "\\:").replace("'", "\\'\"'\\''")
    return f"ass='{esc}'"


def burn_and_thumb(cdir: Path, force: bool = False, total_s: float = 0.0,
                   on_tick=None) -> dict:
    from .ffmpeg import is_valid_video, run_with_progress

    cut = cdir / "cut.mp4"
    final = cdir / "video.mp4"
    ass_path = cdir / "subtitles.ass"
    burn_hash = cdir / "burn.hash"
    ass_bytes = ass_path.read_bytes() if ass_path.exists() else b""
    import hashlib

    digest = hashlib.sha256(ass_bytes).hexdigest()
    if final.exists() and not force:
        # El .ass se regenera siempre: el quemado solo vale si se hizo con
        # ESTE ass (hash) y el video abre. Si no, re-quemar (no basta mtime:
        # el ass recién escrito siempre sería "más nuevo").
        if (burn_hash.exists() and burn_hash.read_text().strip() == digest
                and is_valid_video(str(final), total_s)):
            return {"id": cdir.name, "video": str(final), "cached": True}
        final.unlink()  # quemado rancio o inválido: no envenenar el cache
    if final.exists() and not force:
        final.unlink()  # parcial de un kill anterior: no envenenar el cache
    if not is_valid_video(str(cut), total_s):
        return {"id": cdir.name, "video": "", "cached": False,
                "error": f"cut inválido {cut} (re-corre clip)"}
    ass_path = cdir / "subtitles.ass"
    has_subs = ass_path.exists() and "Dialogue: 0," in ass_path.read_text()
    if has_subs:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(cut),
               "-vf", _ass_vf(ass_path),
               "-c:v", "libx264", "-preset", "fast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-c:a", "copy",
               "-movflags", "+faststart", str(final)]
    else:  # sin subtítulos: no re-encodear, solo renombrar vía copia
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(cut),
               "-c", "copy", "-movflags", "+faststart", str(final)]
    run_with_progress(cmd, total_s, on_tick=on_tick)
    # thumbnail en la mitad del clip final
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(final)], capture_output=True, text=True, check=True)
    mid = max(0.5, float(probe.stdout.strip()) / 2)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}",
                    "-i", str(final), "-frames:v", "1",
                    str(cdir / "thumbnail.jpg")], check=True)
    burn_hash.write_text(digest, encoding="utf-8")
    return {"id": cdir.name, "video": str(final), "cached": False}


def caption_all(workdir: str, force: bool = False, on_item=None, on_tick=None) -> dict:
    wd = Path(workdir)
    clips_path = wd / "clips.json"
    tpath = wd / "transcript.json"
    if not clips_path.exists():
        return {"ok": False, "error": f"falta {clips_path} (corre analyze primero)"}
    transcript = []
    if tpath.exists():
        transcript = json.loads(tpath.read_text()).get("segments", [])

    clips = json.loads(clips_path.read_text()).get("clips", [])
    total = len(clips)
    done = []
    for i, c in enumerate(clips):
        cid = c.get("id") or f"short_{len(done) + 1:02d}"
        cdir = wd / cid
        if not (cdir / "cut.mp4").exists():
            return {"ok": False, "error": f"falta {cdir / 'cut.mp4'} (corre clip primero)"}
        segs = clip_segments(transcript, float(c["start"]), float(c["end"]))
        (cdir / "subtitles.srt").write_text(to_srt(segs), encoding="utf-8")
        (cdir / "subtitles.ass").write_text(to_ass(segs), encoding="utf-8")
        try:
            dur = max(float(c["end"]) - float(c["start"]), 0.0)
            r = burn_and_thumb(cdir, force=force, total_s=dur, on_tick=on_tick)
            if r.get("error"):
                return {"ok": False, "error": f"caption {cid}: {r['error']}"}
            done.append(r)
        except subprocess.CalledProcessError as e:
            (cdir / "video.mp4").unlink(missing_ok=True)  # no dejar parcial
            return {"ok": False, "error": f"ffmpeg caption {cid}: {e}"}
        if on_item:
            on_item(i + 1, total, cid, bool(r.get("cached")))
    return {"ok": True, "videos": done}
