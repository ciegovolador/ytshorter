"""review.py — etapa explícita plan→review→execute (entre analyze y clip).

analyze propone el plan (clips + review:pending); review lo audita con 2ª
instancia y reescribe clips.json (ids re-numerados, veredictos guardados).
CLI: `ytshorter review work/<id>/`. Idempotente salvo --force.
"""
from __future__ import annotations

import json
from pathlib import Path


def review_workdir(workdir: str, prompts_version: str = "v3",
                   force: bool = False) -> dict:
    """Audita clips.json con reviewer.md. Requiere GEMINI_API_KEY."""
    from .analyze import apply_verdicts, build_sentences, load_prompts, review_clips
    from .config import load_settings

    settings = load_settings()
    wd = Path(workdir)
    cpath = wd / "clips.json"
    tpath = wd / "transcript.json"
    if not cpath.exists():
        return {"ok": False, "error": f"falta {cpath} (corre analyze primero)"}
    try:
        data = json.loads(cpath.read_text())
    except ValueError:
        return {"ok": False, "error": f"{cpath} corrupto"}
    if data.get("review", {}).get("status") == "applied" and not force:
        clips = data.get("clips", [])
        return {"ok": True, "cached": True, "clips": str(cpath), "n": len(clips)}
    if not settings.llm_configured():
        return {"ok": False, "error": "falta GEMINI_API_KEY (o proveedor LLM alternativo) en entorno"}
    if not tpath.exists():
        return {"ok": False, "error": f"falta {tpath} (corre transcribe primero)"}

    clips = data.get("clips", [])
    if not clips:
        return {"ok": False, "error": "clips.json sin clips que revisar"}
    segments = json.loads(tpath.read_text()).get("segments", [])
    prompts = load_prompts(prompts_version)
    rev = review_clips(clips, build_sentences(segments), prompts,
                       settings.gemini_model, settings.gemini_api_key)
    if not rev["ok"]:
        data["review"] = {"status": "skipped", "error": rev.get("error", "")}
        cpath.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        return {"ok": True, "cached": False, "clips": str(cpath),
                "n": len(clips), "review": "skipped"}
    kept, stats = apply_verdicts(clips, rev["verdicts"],
                                 settings.min_short_s, settings.max_short_s)
    # Segunda instancia visual: frames reales de cada rango vetado por texto.
    vinfo: dict = {"status": "skipped", "why": "sin source.mp4"}
    vpath = wd / "source.mp4"
    if kept and vpath.exists():
        from .vision import apply_vision, vision_review

        vres = vision_review(str(vpath), kept, prompts, settings.gemini_model,
                             settings.gemini_api_key)
        if vres["ok"]:
            kept, vstats = apply_vision(kept, vres["verdicts"])
            vinfo = {"status": "applied", **vstats}
        else:
            vinfo = {"status": "skipped",
                     "why": str(vres.get("skipped") or vres.get("error", ""))[:120]}
    for i, c in enumerate(kept, 1):  # ids contiguos post-drop (aún no hay dirs)
        c["id"] = f"short_{i:02d}"
        c["duration"] = round(c["end"] - c["start"], 1)
    data["clips"] = kept
    data["review"] = {"status": "applied", **stats, "verdicts": rev["verdicts"],
                      "vision": vinfo}
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return {"ok": True, "cached": False, "clips": str(cpath),
            "n": len(kept), "review": "applied"}
