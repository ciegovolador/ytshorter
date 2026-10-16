"""analyze.py (F3) — Gemini Flash elige clips + packaging. Prompts versionados en prompts/<v>/."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CHUNK_SIZE_S = 1200  # 20 min por chunk (videos largos)
CHUNK_OVERLAP_S = 60
MIN_SCORE = 70
MAX_CLIPS = 20


def prompts_dir() -> Path:
    override = os.getenv("YT_SHORTER_PROMPTS_DIR", "")
    if override:
        return Path(override)
    candidates = [
        Path(__file__).resolve().parents[2] / "prompts",
        Path("/app/prompts"),
        Path.cwd() / "prompts",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def load_prompts(version: str = "v1") -> dict:
    base = prompts_dir() / version
    out = {}
    for name in ("editor", "virality", "packaging", "reviewer"):
        p = base / f"{name}.md"
        if not p.exists():
            raise FileNotFoundError(f"falta prompt {p}")
        out[name] = p.read_text()
    return out


def system_prompt(p: dict) -> str:
    return f"{p['editor']}\n\n{p['virality']}\n\n{p['packaging']}"


def build_chunks(segments: list[dict]) -> list[list[dict]]:
    """Parte el transcript en ventanas de CHUNK_SIZE_S con overlap. Videos cortos = 1 chunk."""
    if not segments:
        return []
    chunks, cur, start_t = [], [], segments[0]["start"]
    for s in segments:
        cur.append(s)
        if s["end"] - start_t >= CHUNK_SIZE_S:
            chunks.append(cur)
            # overlap: re-empieza 60s antes del fin
            tail = [x for x in cur if x["end"] >= s["end"] - CHUNK_OVERLAP_S]
            cur, start_t = tail, tail[0]["start"] if tail else s["end"]
    if cur:
        chunks.append(cur)
    return chunks


def chunk_to_text(segments: list[dict]) -> str:
    lines = []
    for s in segments:
        lines.append(f"[{s['start']:.1f}-{s['end']:.1f}] {s.get('text','').strip()}")
    return "\n".join(lines)


def call_gemini(system: str, user: str, model: str, api_key: str) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
        ),
    )
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def overlap_ratio(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    span = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / span if span > 0 else 0.0


def dedupe_clips(clips: list[dict]) -> list[dict]:
    """Ordena por score desc y elimina solapes >50% (se queda el mejor)."""
    kept = []
    for c in sorted(clips, key=lambda x: x.get("score", 0), reverse=True):
        if all(overlap_ratio(c, k) <= 0.5 for k in kept):
            kept.append(c)
    return sorted(kept, key=lambda x: x["start"])


def merge_stream(segments: list[dict]) -> list[dict]:
    """Une ventanas solapadas de auto-captions en un flujo sin duplicados.

    Cada ventana repite la cola de la anterior con tiempos levemente distintos;
    se empalma por coincidencia de texto (overlap join) en vez de sumar.
    """
    from .caption import _estimate_words

    emitted: list[dict] = []
    for s in sorted(segments, key=lambda x: (x["start"], x["end"])):
        if s.get("words"):
            cur = [{"start": float(w["start"]), "end": float(w["end"]),
                    "text": (w.get("word") or w.get("text") or "").strip()}
                   for w in s["words"]]
            cur = [w for w in cur if w["text"] and w["end"] > w["start"]]
        else:
            cur = _estimate_words(s.get("text", ""), s["start"], s["end"])
        tail = [w["text"].lower() for w in emitted]
        head = [w["text"].lower() for w in cur]
        k = min(len(tail), len(head))
        while k > 0 and tail[-k:] != head[:k]:
            k -= 1
        emitted.extend(cur[k:])
    return emitted


def build_sentences(segments: list[dict]) -> list[dict]:
    """Reconstruye frases {start,end,text} con tiempos (whisper-words o estimado).

    Los auto-subtítulos de YouTube llegan como ventanas rodantes que cortan a
    mitad de frase; partir por puntuación evita empezar/terminar en palabras
    sueltas (el `snap` anterior solo veía bordes de segmento).
    """
    words = merge_stream(segments)
    sentences, cur = [], []
    for w in words:
        cur.append(w)
        if w["text"] and w["text"][-1] in ".?!…":
            sentences.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                              "text": " ".join(x["text"] for x in cur)})
            cur = []
    if cur:
        sentences.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                          "text": " ".join(x["text"] for x in cur)})
    return sentences


def snap_to_sentences(clips: list[dict], segments: list[dict],
                      max_dur: float = 170.0) -> list[dict]:
    """Ajusta start/end a bordes de FRASE (no de segmento): el clip empieza donde
    empieza una idea y termina donde cierra. Nunca pasa el techo; el piso lo
    aplica el filtro (un fragmento no se rellena: se descarta)."""
    sentences = build_sentences(segments)
    if not sentences:
        return clips
    out = []
    for c in clips:
        c = dict(c)
        s0 = next((s for s in sentences if s["start"] - 1.0 <= c["start"] <= s["end"]), None)
        if s0 is not None:
            frac = (c["start"] - s0["start"]) / max(s0["end"] - s0["start"], 0.01)
            c["start"] = s0["start"] if frac <= 0.6 else (
                next((s["start"] for s in sentences if s["start"] > c["start"]), c["start"]))
        s1 = next((s for s in sentences if s["start"] <= c["end"] <= s["end"] + 1.0), None)
        if s1 is not None:
            frac = (c["end"] - s1["start"]) / max(s1["end"] - s1["start"], 0.01)
            c["end"] = s1["end"] if frac >= 0.4 else (
                next((s["end"] for s in reversed(sentences) if s["end"] < c["end"]), c["end"]))
        if c["end"] - c["start"] > max_dur:
            c["end"] = c["start"] + max_dur
        if c["end"] <= c["start"]:
            c["end"] = c["start"] + 25.0
        out.append(c)
    return out


def review_clips(clips: list[dict], sentences: list[dict], prompts: dict,
                 model: str, api_key: str) -> dict:
    """Segunda instancia: audita el plan de clips. Nunca revienta el pipeline."""
    plan = "\n".join(
        f"- {c.get('id', '?')}: [{c['start']:.1f}-{c['end']:.1f}] "
        f"score={c.get('score', '?')} | {c.get('title', '')} | hook: {c.get('hook_text', '')}"
        for c in clips)
    sents = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text'][:120]}" for s in sentences)
    user = (f"Plan a auditar ({len(clips)} clips):\n{plan}\n\n"
            f"Frases del transcript (verifica límites):\n{sents}\n\n"
            f"Devuelve los verdicts en el JSON pedido.")
    try:
        data = call_gemini(prompts["reviewer"], user, model, api_key)
        verdicts = data.get("verdicts", [])
        assert isinstance(verdicts, list)
        return {"ok": True, "verdicts": verdicts}
    except Exception as e:  # noqa: BLE001 — sin revisión, vale el plan original
        print(f"[analyze] review omitida ({e}), vale el plan", file=sys.stderr)
        return {"ok": False, "error": str(e)[:200], "verdicts": []}


def apply_verdicts(clips: list[dict], verdicts: list[dict],
                   min_dur: float = 10.0, max_dur: float = 170.0) -> "tuple[list[dict], dict]":
    """Aplica keep/drop/adjust. Desconocidos o inválidos → keep (seguro)."""
    by_id = {v.get("id"): v for v in verdicts if isinstance(v, dict)}
    kept, stats = [], {"kept": 0, "dropped": 0, "adjusted": 0}
    for c in clips:
        v = by_id.get(c.get("id"), {})
        action = v.get("action", "keep")
        if action == "drop":
            stats["dropped"] += 1
            continue
        c = dict(c)
        if action == "adjust":
            try:
                ns, ne = float(v["start"]), float(v["end"])
                if 0 <= ns < ne and min_dur <= ne - ns <= max_dur:
                    c["start"], c["end"] = ns, ne
                    c["duration"] = round(ne - ns, 1)
                    stats["adjusted"] += 1
                else:
                    stats["kept"] += 1
            except (KeyError, TypeError, ValueError):
                stats["kept"] += 1
        else:
            stats["kept"] += 1
        c["review"] = {"action": action if action in ("keep", "adjust") else "keep",
                       "reason": str(v.get("reason", ""))[:200]}
        kept.append(c)
    return kept, stats


def analyze_workdir(workdir: str, prompts_version: str = "v1", min_score: int = MIN_SCORE,
                    max_clips: int = MAX_CLIPS, force: bool = False) -> dict:
    """Lee transcript.json → clips.json (idempotente salvo --force). Requiere GEMINI_API_KEY."""
    from .config import load_settings

    settings = load_settings()
    wd = Path(workdir)
    tpath = wd / "transcript.json"
    out = wd / "clips.json"
    if out.exists() and not force:
        data = json.loads(out.read_text())
        return {"ok": True, "cached": True, "clips": str(out), "n": len(data.get("clips", []))}

    if not settings.llm_configured():
        return {"ok": False, "error": "falta GEMINI_API_KEY en entorno"}
    if not tpath.exists():
        return {"ok": False, "error": f"falta {tpath} (corre transcribe primero)"}

    tdata = json.loads(tpath.read_text())
    segments = tdata.get("segments", [])
    if not segments:
        return {"ok": False, "error": "transcript vacío, nada que analizar"}

    prompts = load_prompts(prompts_version)
    system = system_prompt(prompts)
    video_title = ""
    info_path = wd / "info.json"
    if info_path.exists():
        try:
            video_title = json.loads(info_path.read_text()).get("title", "")
        except Exception:
            pass

    all_clips: list[dict] = []
    for i, chunk in enumerate(build_chunks(segments)):
        user = (f"Video: {video_title}\nChunk {i + 1} (tiempos en segundos, absolutos al video).\n"
                f"Devuelve los mejores momentos de ESTE chunk en el JSON pedido.\n\n{chunk_to_text(chunk)}")
        try:
            data = call_gemini(system, user, settings.gemini_model, settings.gemini_api_key)
        except Exception as e:
            return {"ok": False, "error": f"gemini chunk {i + 1}: {e}"}
        for c in data.get("clips", []):
            all_clips.append(c)

    all_clips = snap_to_sentences(all_clips, segments, settings.max_short_s)
    all_clips = dedupe_clips(all_clips)
    # filtro score + cotas (la duración la dicta la idea; solo piso/techo)
    kept = [c for c in all_clips
            if c.get("score", 0) >= min_score
            and settings.min_short_s <= (c["end"] - c["start"]) <= settings.max_short_s][:max_clips]
    for i, c in enumerate(kept, 1):
        c["id"] = f"short_{i:02d}"
        c["duration"] = round(c["end"] - c["start"], 1)

    # Puerta plan→review→execute: 2ª instancia audita antes de ffmpeg.
    review_info: dict = {"status": "skipped"}
    if not os.getenv("YT_SHORTER_NO_REVIEW"):
        sentences = build_sentences(segments)
        rev = review_clips(kept, sentences, prompts, settings.gemini_model,
                           settings.gemini_api_key)
        if rev["ok"]:
            kept, stats = apply_verdicts(kept, rev["verdicts"],
                                         settings.min_short_s, settings.max_short_s)
            review_info = {"status": "applied", **stats,
                           "verdicts": rev["verdicts"]}
            print(f"[analyze] review: {stats}", file=sys.stderr)
        else:
            review_info = {"status": "skipped", "error": rev.get("error", "")}

    out.write_text(json.dumps(
        {"video_id": tdata.get("video_id", wd.name), "prompts_version": prompts_version,
         "model": settings.gemini_model, "clips": kept, "review": review_info},
        ensure_ascii=False, indent=1))
    return {"ok": True, "cached": False, "clips": str(out), "n": len(kept)}
