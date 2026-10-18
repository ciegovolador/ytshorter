"""vision.py — verificación multimodal de candidatos (analyze y review).

Un pase con frames por candidato (por lotes): veta clips cuyo sujeto no se ve,
cuyo gráfico referenciado queda fuera de cuadro o cuyo encuadre quedó roto.
Sin API/ffmpeg/video, o con `YT_SHORTER_NO_VISION`, vale el plan textual:
asesor, no puerta.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .frames import frame_count, sample_frames

VISION_VERSION = "v1"
VISION_BATCH = 6  # candidatos por llamada (acota tamaño del request)


def _image_part(img: bytes):
    from google.genai import types

    return types.Part.from_bytes(data=img, mime_type="image/jpeg")


def _batch_parts(video: str, clips: list[dict]) -> list:
    """Contenidos de una llamada: rótulo + frames de cada candidato del lote."""
    parts: list = []
    for c in clips:
        span = (float(c["start"]), float(c["end"]))
        n = frame_count(span[1] - span[0])
        imgs = sample_frames(video, n=n, span=span)
        parts.append(f"Candidato {c['id']} [{span[0]:.1f}-{span[1]:.1f}] "
                     f"({len(imgs)} frames de su clip): {c.get('title', '')}")
        for img in imgs:
            parts.append(_image_part(img))
    return parts


def vision_review(video: str, clips: list[dict], prompts: dict, model: str,
                  api_key: str, title: str = "") -> dict:
    """Verifica visualmente cada clip con frames de SU rango. Nunca revienta.

    Devuelve `{"ok": True, "verdicts": [...]}` o `{"ok": False, "skipped"|"error"}`;
    con `ok: False` el plan textual queda intacto (asesor)."""
    if os.getenv("YT_SHORTER_NO_VISION"):
        return {"ok": False, "skipped": "YT_SHORTER_NO_VISION"}
    if not (prompts.get("vision") or "").strip():
        return {"ok": False, "skipped": "sin prompts/vision.md (usar prompts v3)"}
    if not Path(video).exists():
        return {"ok": False, "skipped": f"falta {video}"}
    if not clips:
        return {"ok": True, "verdicts": [], "version": VISION_VERSION}

    from .analyze import call_gemini

    verdicts: list[dict] = []
    for i in range(0, len(clips), VISION_BATCH):
        batch = clips[i:i + VISION_BATCH]
        user = (f"Video: {title}\nVerificá visualmente cada candidato del lote "
                f"con los frames que siguen a su rótulo. Devuelve SOLO el JSON "
                f"pedido en la rúbrica.")
        try:
            data = call_gemini(prompts["vision"], [user, *_batch_parts(video, batch)],
                               model, api_key)
        except Exception as e:  # noqa: BLE001 — verificación caída ≠ plan roto
            print(f"[vision] verificación omitida ({str(e)[:140]}); vale el plan",
                  file=sys.stderr)
            return {"ok": False, "error": str(e)[:200], "verdicts": verdicts}
        for v in data.get("verdicts", []):
            if isinstance(v, dict) and v.get("id"):
                verdicts.append(v)
    return {"ok": True, "verdicts": verdicts, "version": VISION_VERSION}


def apply_vision(clips: list[dict], verdicts: list[dict]) -> "tuple[list[dict], dict]":
    """`visual_ok: false` → drop con motivo anotado; desconocido → keep (seguro).

    Todo clip queda con su anotación `vision` (trazabilidad), aprobado o no."""
    by_id = {v.get("id"): v for v in verdicts if isinstance(v, dict)}
    kept, dropped = [], 0
    for c in clips:
        v = by_id.get(c.get("id")) or {}
        ok = bool(v.get("visual_ok", True))
        c = dict(c)
        c["vision"] = {"ok": ok, "reason": str(v.get("reason", ""))[:200]}
        if ok:
            kept.append(c)
        else:
            dropped += 1
    return kept, {"kept": len(kept), "dropped": dropped}
