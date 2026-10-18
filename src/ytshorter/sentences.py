"""sentences.py — texto/timing del transcript: chunks, frases y límites.

Puro y sin estado: parte el transcript en ventanas, reconstruye frases con
tiempos (words reales o estimados) y alinea bordes de clip a frases. Viven acá
para que analyze.py quede de orquestación (LLM + plan)."""
from __future__ import annotations

CHUNK_SIZE_S = 1200  # 20 min por chunk (videos largos)
CHUNK_OVERLAP_S = 60


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
    from .subtitles import _estimate_words

    emitted: list[dict] = []
    texts: list[str] = []  # espejo incremental de emitted (evita O(n²))
    for s in sorted(segments, key=lambda x: (x["start"], x["end"])):
        if s.get("words"):
            cur = [{"start": float(w["start"]), "end": float(w["end"]),
                    "text": (w.get("word") or w.get("text") or "").strip()}
                   for w in s["words"]]
            cur = [w for w in cur if w["text"] and w["end"] > w["start"]]
        else:
            cur = _estimate_words(s.get("text", ""), s["start"], s["end"])
        head = [w["text"].lower() for w in cur]
        k = min(len(texts), len(head))
        while k > 0 and texts[-k:] != head[:k]:
            k -= 1
        emitted.extend(cur[k:])
        texts.extend(w["text"].lower() for w in cur[k:])
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


