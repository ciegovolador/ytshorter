"""judge.py — LLM-as-judge independiente sobre shorts terminados.

Segunda opinión multimodal (frames + título + captions + framing): no decide
qué producir (eso es analyze+review), audita lo producido. Asesor, no puerta:
escribe `judgment.json` por short, jamás borra nada.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

JUDGE_VERSION = "v2"
JUDGE_ATTEMPTS = 3  # 429/5xx de Gemini: misma política que analyze/review (BR-025)
SHIP_MIN_SCORE = 70  # umbral duro: se aplica en código, no se delega al modelo

JUDGE_SYSTEM = """Rol: juez independiente de shorts verticales (segunda instancia).
No editaste ni elegiste estos clips: los auditas con ojos frescos y duros.

Responde SOLO JSON válido: {"score": 0-100, "ship": true|false,
"issues": ["..."], "notes": "..."}.

Rúbrica con anclas (resta por cada fallo; los topes son obligatorios):
- Hook (30): ¿los primeros 3s atrapan SIN contexto externo? Si necesita saber
  quién habla o de qué video sale para entenderse → tope 55.
- Encuadre (25): rostro completo y centrado en su tercio; si se menciona algo
  en pantalla (mapa, tabla, flecha), DEBE verse. Cara cortada, cara diminuta
  o gráfico referenciado invisible → tope 60 y `ship: false`.
- Captions (20): legibles, sincronizados, bloques de 1-2 líneas, sin comas
  que inicien línea ni palabras colgadas. Desincronizados o ilegibles → tope 65.
- Cierre (15): idea cerrada; cortar en muletilla, respiración o frase colgada
  → tope 75.
- Audio/visual (10): frames y contexto coherentes con el título; cortes
  abruptos o resolución rota → tope 70.

Reglas de decisión (duras):
- `ship: true` SOLO si score >= 70 Y ningún issue bloqueante.
- Bloqueantes: cara cortada, gráfico referenciado invisible, hook
  incomprensible sin contexto, captions desincronizados.
- Ante duda razonable: `ship: false` y score a la baja. Aprobar basura es el
  peor error del juez. `issues` corto (máx 3, concretos), `notes` 1-2 líneas."""


from .frames import sample_frames  # noqa: E402 — reexport histórico de tests


def _judge_chain(system: str, user: str, images: list[bytes],
                 models: list[str], api_key: str) -> "tuple[dict, str]":
    """Primer modelo que responda gana; agotado el último, propaga el error.

    La cadena (3.6-flash → 2.5-flash por default) mantiene el veredicto sin
    degradar a asesor cuando el modelo principal está caído o sin cuota."""
    last: Exception | None = None
    for i, m in enumerate(models):
        try:
            return judge_call(system, user, images, m, api_key), m
        except Exception as e:  # noqa: BLE001 — probamos el siguiente modelo
            last = e
            if i + 1 < len(models):
                print(f"[judge] {m} falló ({type(e).__name__}); pruebo {models[i + 1]}",
                      file=sys.stderr, flush=True)
    raise last if last is not None else RuntimeError("cadena de jueces vacía")


def caption_stats(srt_path: str) -> dict:
    """Bloques, CPS pico y líneas largas del .srt (lo que el juez 'lee')."""
    try:
        text = Path(srt_path).read_text(encoding="utf-8")
    except OSError:
        return {"blocks": 0, "max_cps": 0.0, "long_lines": 0}
    blocks, max_cps, long_lines = 0, 0.0, 0
    for block in text.strip().split("\n\n"):
        parts = block.splitlines()
        if len(parts) < 3 or "-->" not in parts[1]:
            continue
        times, body = parts[1], [l for l in parts[2:] if l.strip()]
        if not body:
            continue
        try:
            a, b = times.split(" --> ")
            def ts(t):
                h, m, s = t.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))
            dur = max(ts(b) - ts(a), 0.01)
            chars = sum(len(l) for l in body)
            max_cps = max(max_cps, chars / dur)
            blocks += 1
            long_lines += sum(1 for l in body if len(l) > 42)
        except (ValueError, IndexError):
            continue
    return {"blocks": blocks, "max_cps": round(max_cps, 1), "long_lines": long_lines}


def judge_call(system: str, user: str, images: list[bytes],
               model: str, api_key: str, attempts: int = JUDGE_ATTEMPTS) -> dict:
    """Gemini con imágenes (bytes JPEG). Sin imágenes → solo texto.

    Reintenta errores transitorios (429/5xx/UNAVAILABLE/timeouts) con backoff
    5/15s; errores definitivos (400/403/JSON inválido) fallan al toque. El
    fallback asesor de `judge_short` cubre el caso agotado."""
    from google import genai
    from google.genai import types

    from .analyze import _is_transient_llm_error

    client = genai.Client(api_key=api_key)
    parts: list = [user]
    for img in images:
        try:
            parts.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))
        except Exception:
            continue
    for attempt in range(1, attempts + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=system, response_mime_type="application/json"),
            )
            text = (resp.text or "").strip()
            if text.startswith("```") and "\n" in text:
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except Exception as e:  # noqa: BLE001 — se decide reintentar o propagar
            if attempt == attempts or not _is_transient_llm_error(e):
                raise
            wait = 5 * 3 ** (attempt - 1)
            print(f"[judge] gemini intento {attempt}/{attempts} falló "
                  f"({type(e).__name__}); reintento en {wait}s", file=sys.stderr, flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def judge_short(sdir: str, model: "str | list[str]", api_key: str,
                n_frames: "int | None" = None,
                force: bool = False, clip: dict | None = None) -> dict:
    """Audita un short_XX/ terminado. Escribe judgment.json. Nunca borra.

    `model` acepta uno o varios modelos (cadena de independencia: principal →
    respaldo). El umbral `score >= 70` se aplica acá, no se delega al modelo.
    `n_frames=None` → muestreo variable por duración (frames.py).

    `clip` (entrada de clips.json) aporta título/descripción/hook/score/framing
    cuando el paquete todavía no existe: la etapa `judge` corre antes que
    `package`, así que sin esto el juez auditaría a ciegas el contexto."""
    d = Path(sdir)
    jpath = d / "judgment.json"
    if jpath.exists() and not force:
        try:
            prev = json.loads(jpath.read_text(encoding="utf-8"))
            vid = d / "video.mp4"
            if (prev.get("judge") == JUDGE_VERSION and vid.exists()
                    and jpath.stat().st_mtime >= vid.stat().st_mtime):
                return {"id": d.name, **prev, "cached": True}
        except (OSError, ValueError):
            pass
    meta = {}
    try:
        meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    clip = clip or {}
    title = ((d / "title.txt").read_text(encoding="utf-8").strip()
             if (d / "title.txt").exists() else "") or clip.get("title") or meta.get("title", "")
    desc = ((d / "description.txt").read_text(encoding="utf-8").strip()[:500]
            if (d / "description.txt").exists() else "") or (clip.get("description") or "")[:500]
    dur = meta.get("duration") or (round(float(clip["end"]) - float(clip["start"]), 1)
                                   if clip.get("start") is not None else "?")
    score = meta.get("score", clip.get("score", "?"))
    stats = caption_stats(str(d / "subtitles.srt"))
    framing = meta.get("framing") or clip.get("framing") or {}
    models = list(dict.fromkeys([model] if isinstance(model, str) else model))
    images = sample_frames(str(d / "video.mp4"), n=n_frames)
    user = (f"Título: {title}\nDescripción: {desc}\n"
            f"Duración: {dur}s | score editor: {score}\n"
            f"Encuadre elegido: {framing.get('reason', '?')} (x={framing.get('x', '?')})\n"
            f"Captions: {stats['blocks']} bloques, CPS pico {stats['max_cps']}, "
            f"líneas >42 chars: {stats['long_lines']}\n"
            f"Hook: {meta.get('hook_text') or clip.get('hook_text', '')}\n"
            f"Juzga con la rúbrica. Adjunto {len(images)} frames (muestreo "
            f"uniforme; el primero es el gancho).")
    try:
        raw, used = _judge_chain(JUDGE_SYSTEM, user, images, models, api_key)
        sc = int(raw.get("score", 0))
        ship = bool(raw.get("ship", False))
        notes = str(raw.get("notes", ""))[:300]
        if ship and sc < SHIP_MIN_SCORE:
            ship = False
            notes = (f"{notes} [umbral 70: score {sc} < 70 → no ship]").strip()
        verdict = {"ship": ship, "score": sc,
                   "issues": list(raw.get("issues", []))[:3],
                   "notes": notes[:300],
                   "judge": JUDGE_VERSION, "model": used,
                   "frames": len(images)}
    except Exception as e:  # noqa: BLE001 — el juez nunca rompe nada
        verdict = {"ship": True, "score": -1, "issues": [],
                   "notes": f"juez no disponible: {str(e)[:150]}",
                   "judge": JUDGE_VERSION, "model": "→".join(models),
                   "frames": len(images)}
    jpath.write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return {"id": d.name, **verdict}


def judge_all(workdir: str, force: bool = False, on_item=None,
              n_frames: "int | None" = None) -> dict:
    """Etapa `judge` del pipeline: audita TODOS los shorts con video.mp4.

    Asesor, no puerta: nunca borra ni bloquea; escribe judgment.json por short
    (cacheado por mtime del video) y devuelve el resumen ships/total."""
    from .config import load_settings

    settings = load_settings()
    if not settings.llm_configured():
        return {"ok": False, "error": "falta GEMINI_API_KEY (juez omitido)"}
    wd = Path(workdir)
    if not wd.is_dir():
        return {"ok": False, "error": f"falta {wd}"}
    clips = {}
    try:
        for c in json.loads((wd / "clips.json").read_text(encoding="utf-8")).get("clips", []):
            if c.get("id"):
                clips[c["id"]] = c
    except (OSError, ValueError):
        pass
    shorts = sorted(p for p in wd.iterdir()
                    if p.is_dir() and (p / "video.mp4").exists())
    if clips:  # solo el set vigente: dirs viejos de otro run no se auditan
        shorts = [s for s in shorts if s.name in clips]
    models = list(dict.fromkeys([settings.judge_model, settings.judge_fallback_model]))
    results = []
    for i, s in enumerate(shorts):
        r = judge_short(str(s), models, settings.gemini_api_key,
                        n_frames=n_frames, force=force, clip=clips.get(s.name))
        results.append(r)
        if on_item:
            on_item(i + 1, len(shorts), s.name, bool(r.get("cached")))
    ships = sum(1 for r in results if r["ship"] and r["score"] >= 0)
    return {"ok": True, "n": len(results), "ships": ships, "shorts": results}


def judge_video(vdir: str, model: "str | list[str]", api_key: str,
                n_frames: "int | None" = None) -> dict:
    """Audita dist/<video_id>/ entero. Devuelve resumen."""
    shorts = sorted(p for p in Path(vdir).iterdir()
                    if p.is_dir() and (p / "video.mp4").exists())
    results = [judge_short(str(s), model, api_key, n_frames) for s in shorts]
    ships = sum(1 for r in results if r["ship"] and r["score"] >= 0)
    return {"video": Path(vdir).name, "n": len(results), "ships": ships,
            "shorts": results}
