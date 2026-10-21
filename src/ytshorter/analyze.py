"""analyze.py (F3) — Gemini Flash elige clips + packaging. Prompts versionados en prompts/<v>/."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Texto/timing (chunks, frases, límites) vive en sentences.py.
from .sentences import (  # noqa: F401 — re-export histórico (tests y compat)
    CHUNK_OVERLAP_S, CHUNK_SIZE_S, build_chunks, build_sentences, chunk_to_text,
    dedupe_clips, fallback_clips, merge_stream, overlap_ratio, snap_to_sentences)
from .providers import call_text

MIN_SCORE = 70
MAX_CLIPS = 20


def _volume_floor(segments: list[dict], cap: int) -> int:
    """Piso de volumen (BR-030): ~1 clip cada 4 min, base 8, tope `cap`.

    `YT_SHORTER_MIN_CLIPS` lo sobreescribe (0 = desactivado)."""
    env = os.getenv("YT_SHORTER_MIN_CLIPS")
    if env is not None and env.strip():
        try:
            return max(0, min(cap, int(env)))
        except ValueError:
            pass
    dur = float(segments[-1].get("end", 0) or 0) if segments else 0.0
    return min(cap, max(8, int(dur // 240)))

LLM_ATTEMPTS = 4  # 429/5xx de Gemini ("high demand") suelen ser transitorios
LLM_BACKOFF_S = (5, 15, 45)  # esperas entre intentos
_TRANSIENT_LLM = ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "RATE LIMIT", "RATE_LIMIT",
                  "TIMEOUT", "TIMED OUT", "DEADLINE_EXCEEDED", "OVERLOADED",
                  "HIGH DEMAND")


def _is_transient_llm_error(e: Exception) -> bool:
    """503/429/etc. → reintentar; 400/403/JSON inválido → fallar rápido."""
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    try:
        if int(code) in (429, 500, 502, 503, 504):
            return True
    except (TypeError, ValueError):
        pass
    msg = str(e).upper()
    return any(t in msg for t in _TRANSIENT_LLM)


def prompts_dir() -> Path:
    override = os.getenv("YT_SHORTER_PROMPTS_DIR", "")
    if override:
        return Path(override)
    meipass = getattr(sys, "_MEIPASS", "")  # PyInstaller (Windows exe)
    candidates = [
        Path(__file__).resolve().parents[2] / "prompts",
        Path(sys.executable).resolve().parent / "prompts",
        Path("/app/prompts"),
        Path.cwd() / "prompts",
    ]
    if meipass:
        candidates.insert(0, Path(meipass) / "prompts")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def load_prompts(version: str = "v3") -> dict:
    base = prompts_dir() / version
    out = {}
    for name in ("editor", "virality", "packaging", "reviewer"):
        p = base / f"{name}.md"
        if not p.exists():
            raise FileNotFoundError(f"falta prompt {p}")
        out[name] = p.read_text(encoding="utf-8")
    p = base / "vision.md"  # opcional: solo v3+ verifica con frames
    out["vision"] = p.read_text(encoding="utf-8") if p.exists() else ""
    return out


def system_prompt(p: dict) -> str:
    return f"{p['editor']}\n\n{p['virality']}\n\n{p['packaging']}"


def call_gemini(system: str, user: "str | list", model: str, api_key: str) -> dict:
    """Una sola forma de llamar al LLM (analyze + review + vision).
    `user` puede ser lista de contenidos (texto + Part de imágenes) para las
    llamadas multimodales. Reintenta errores transitorios."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = None
    for attempt in range(1, LLM_ATTEMPTS + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                ),
            )
            break
        except Exception as e:  # noqa: BLE001 — clasificamos transitorio vs definitivo
            if attempt == LLM_ATTEMPTS or not _is_transient_llm_error(e):
                raise
            wait = LLM_BACKOFF_S[min(attempt - 1, len(LLM_BACKOFF_S) - 1)]
            print(f"[analyze] gemini intento {attempt}/{LLM_ATTEMPTS} falló "
                  f"({str(e).splitlines()[0][:140]}); reintento en {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
    text = (resp.text or "").strip()
    if text.startswith("```") and "\n" in text:
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


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
        data, _ = call_text(prompts["reviewer"], user, model, api_key)
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


def analyze_workdir(workdir: str, prompts_version: str = "v3", min_score: int = MIN_SCORE,
                    max_clips: int = MAX_CLIPS, force: bool = False,
                    critique: str = "") -> dict:
    """Lee transcript.json → clips.json (idempotente salvo --force). Requiere GEMINI_API_KEY.

    `critique` (opcional): motivos de drops del revisor para la vuelta de
    Reflexion del loop Generator-Critic (pipeline la pasa al reciclar el plan)."""
    from .config import load_settings

    settings = load_settings()
    wd = Path(workdir)
    tpath = wd / "transcript.json"
    out = wd / "clips.json"
    if out.exists() and not force:
        data = json.loads(out.read_text(encoding="utf-8"))
        return {"ok": True, "cached": True, "clips": str(out), "n": len(data.get("clips", []))}

    if not settings.llm_configured():
        return {"ok": False, "error": "falta GEMINI_API_KEY (o proveedor LLM alternativo) en entorno"}
    if not tpath.exists():
        return {"ok": False, "error": f"falta {tpath} (corre transcribe primero)"}

    tdata = json.loads(tpath.read_text(encoding="utf-8"))
    segments = tdata.get("segments", [])
    if not segments:
        return {"ok": False, "error": "transcript vacío, nada que analizar"}

    prompts = load_prompts(prompts_version)
    system = system_prompt(prompts)
    video_title = ""
    from .download import find_info_json

    info_path = find_info_json(wd)
    if info_path is not None:
        try:
            video_title = json.loads(info_path.read_text(encoding="utf-8")).get("title", "")
        except Exception:
            pass

    all_clips: list[dict] = []
    used_models: list[str] = []
    critique_block = (
        f"\n\nErrores que un revisor independiente marcó al plan anterior "
        f"(no los repitas):\n{critique}" if critique else "")
    for i, chunk in enumerate(build_chunks(segments)):
        user = (f"Video: {video_title}\nChunk {i + 1} (tiempos en segundos, absolutos al video).\n"
                f"Devuelve los mejores momentos de ESTE chunk en el JSON pedido.\n\n{chunk_to_text(chunk)}"
                + critique_block)
        try:
            data, used = call_text(system, user, settings.gemini_model,
                                   settings.gemini_api_key)
            used_models.append(used)
        except Exception as e:
            return {"ok": False, "error": f"LLM chunk {i + 1}: {e}"}
        for c in data.get("clips", []):
            all_clips.append(c)

    all_clips = snap_to_sentences(all_clips, segments, settings.max_short_s)
    all_clips = dedupe_clips(all_clips)
    # filtro score + cotas (la duración la dicta la idea; solo piso/techo)
    kept = [c for c in all_clips
            if c.get("score", 0) >= min_score
            and settings.min_short_s <= (c["end"] - c["start"]) <= settings.max_short_s][:max_clips]
    # Piso de volumen (BR-030): si el LLM propuso de menos, completa el
    # respaldo local determinista. El volumen no depende del humor del modelo.
    floor_n = _volume_floor(segments, max_clips)
    fallback_n = 0
    if len(kept) < floor_n:
        extra = fallback_clips(segments, floor_n - len(kept), existing=kept,
                               min_s=settings.min_short_s, max_s=settings.max_short_s)
        if extra:
            fallback_n = len(extra)
            print(f"[analyze] piso de volumen: +{len(extra)} clips de respaldo "
                  f"local (LLM propuso {len(kept)}, piso {floor_n})", file=sys.stderr)
            kept = dedupe_clips(kept + extra)[:max_clips]
    for i, c in enumerate(kept, 1):
        c["id"] = f"short_{i:02d}"
        c["duration"] = round(c["end"] - c["start"], 1)

    # Verificación visual del plan propuesto (frames de cada rango): propone
    # mirando el video, no solo el texto. Asesor: si falla, vale el plan.
    vinfo: dict = {"status": "skipped", "why": "sin source.mp4"}
    vpath = wd / "source.mp4"
    if kept and vpath.exists():
        from .vision import apply_vision, vision_review

        vres = vision_review(str(vpath), kept, prompts, settings.gemini_model,
                             settings.gemini_api_key, video_title)
        if vres["ok"]:
            kept, vstats = apply_vision(kept, vres["verdicts"])
            for i, c in enumerate(kept, 1):
                c["id"] = f"short_{i:02d}"
            vinfo = {"status": "applied", **vstats}
        else:
            vinfo = {"status": "skipped",
                     "why": str(vres.get("skipped") or vres.get("error", ""))[:120]}
    # Plan sin revisar: la etapa explícita `review` audita antes de ffmpeg.
    out.write_text(json.dumps(
        {"video_id": tdata.get("video_id", wd.name), "prompts_version": prompts_version,
         "model": "+".join(dict.fromkeys(used_models)) or settings.gemini_model,
         "clips": kept, "vision": vinfo,
         "volume": {"floor": floor_n, "fallback_local": fallback_n},
         "review": {"status": "pending"}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "cached": False, "clips": str(out), "n": len(kept),
            "vision": vinfo["status"]}
