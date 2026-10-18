"""pipeline.py — orquesta download→transcribe→analyze→review→clip→caption→package."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

STAGES = ("download", "transcribe", "analyze", "review", "clip", "caption",
          "judge", "package")

REVISION_DROP_FRAC = 0.4  # ≥40% de drops → una vuelta de reciclado (Reflexion)
REVISION_MIN_TOTAL = 4    # planes chicos no gatillan reciclado


def should_replan(review_data: dict, frac: float = REVISION_DROP_FRAC,
                  min_total: int = REVISION_MIN_TOTAL) -> bool:
    """Generator-Critic: ¿el revisor tiró tanto plan que conviene re-generarlo?

    Técnica (evaluator-optimizer acotado): una sola vuelta de revisión, para
    no entrar en bucles que convergen al borde del crítico."""
    try:
        kept = int(review_data.get("kept", 0) or 0)
        dropped = int(review_data.get("dropped", 0) or 0)
        adjusted = int(review_data.get("adjusted", 0) or 0)
    except (TypeError, ValueError):
        return False
    total = kept + dropped + adjusted
    return total >= min_total and dropped / total >= frac


def critique_from_review(review_data: dict, max_reasons: int = 6) -> str:
    """Reflexion: motivos de drop del revisor → correcciones para el editor."""
    reasons = []
    for v in review_data.get("verdicts", []) or []:
        if isinstance(v, dict) and v.get("action") == "drop" and v.get("reason"):
            reasons.append(str(v["reason"]).strip()[:200])
    return "\n".join(f"- {r}" for r in reasons[:max_reasons] if r)


def _log(msg: str) -> None:
    print(f"[pipeline] {msg}", file=sys.stderr)


def _progress_path(job_id: str, work_root: str) -> Path:
    return Path(work_root) / "jobs" / f"{job_id}.progress.json"


def _sub(job_id: str, work_root: str, label: str, sub_idx: int, sub_total: int,
         cached: bool = False, pct: float | None = None) -> None:
    """Actualiza solo los campos de sub-etapa en progress.json (merge). Best-effort."""
    if not job_id:
        return
    try:
        p = _progress_path(job_id, work_root)
        prog = json.loads(p.read_text()) if p.exists() else {}
        prog.update({
            "substage": label,
            "sub_idx": sub_idx,
            "sub_total": sub_total,
            "sub_cached": cached,
            "sub_updated": time.time(),
        })
        if pct is not None:
            prog["sub_pct"] = round(min(max(float(pct), 0.0), 1.0), 3)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(prog, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    except ValueError:
        pass


def _history_path(work_root: str) -> Path:
    return Path(work_root) / "jobs" / "stage_history.json"


def _record_history(work_root: str, stage_times: dict) -> None:
    """Guarda duraciones por etapa (últimas 50) para ETAs históricos. Best-effort."""
    try:
        p = _history_path(work_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        hist = json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        hist = {}
    for k, v in (stage_times or {}).items():
        try:
            hist.setdefault(k, []).append(round(float(v), 1))
            hist[k] = hist[k][-50:]
        except (TypeError, ValueError):
            continue
    try:
        _history_path(work_root).write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _mark(job_id: str, work_root: str, idx: int, started: float, stage_times: dict,
          stage_start: float, status: str = "running") -> None:
    """Escribe jobs/<jid>.progress.json (etapa x/6 + tiempos total/y por etapa). No falla el pipeline."""
    if not job_id:
        return
    try:
        now = time.time()
        total = len(STAGES)
        stage = STAGES[idx] if 0 <= idx < total else ("done" if status == "done" else STAGES[-1])
        payload = {
            "stage": stage,
            "stage_idx": (idx + 1) if status == "running" else total,
            "total_stages": total,
            "status": status,
            "started": started,
            "updated": now,
            "elapsed_s": round(now - started, 1),
            "stage_times": {k: round(float(v), 1) for k, v in stage_times.items()},
            "stage_start": stage_start or now,
            "stage_elapsed_s": round(now - (stage_start or now), 1),
        }
        p = _progress_path(job_id, work_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def run_pipeline(url: str, out_root: str = "dist", work_root: str = "work",
                 job_id: str = "", force: bool = False) -> dict:
    from .analyze import analyze_workdir
    from .caption import caption_all
    from .clip import cut_all
    from .download import download_url
    from .package import package_workdir
    from .review import review_workdir
    from .transcribe import transcribe_workdir
    from . import __version__
    from .config import load_settings

    settings = load_settings()
    started = time.time()
    stage_times: dict[str, float] = {}
    _log(f"v{__version__} url={url} stages={len(STAGES)}")

    def _run(idx: int, label: str, fn):
        total = len(STAGES)
        t0 = time.time()
        _mark(job_id, work_root, idx, started, stage_times, t0)
        _log(f"[{idx + 1}/{total}] {label} start")
        res = fn()
        dt = round(time.time() - t0, 1)
        stage_times[label] = dt
        _log(f"[{idx + 1}/{total}] {label} {'ok' if res.get('ok') else 'FAIL'} {dt}s")
        return res

    dl = _run(0, "download", lambda: download_url(url, out_root=work_root, force=force))
    if not dl.get("ok"):
        return _finish({"ok": False, "stage": "download", "detail": dl}, job_id, work_root,
                       started, stage_times)
    _log(f"download ok video_id={dl['video_id']} cached={dl.get('cached')}")
    wd = str(Path(work_root) / dl["video_id"])

    tr = _run(1, "transcribe",
              lambda: transcribe_workdir(wd, whisper_model=settings.whisper_model, force=force))
    if not tr.get("ok"):
        return _finish({"ok": False, "stage": "transcribe", "detail": tr}, job_id, work_root,
                       started, stage_times)
    _log(f"transcribe ok segments={tr.get('segments')} source={tr.get('source')}")

    an = _run(2, "analyze",
              lambda: analyze_workdir(wd, prompts_version=settings.prompts_version, force=force))
    if not an.get("ok"):
        return _finish({"ok": False, "stage": "analyze", "detail": an}, job_id, work_root,
                       started, stage_times)
    vinfo = (an.get("vision") or "skipped")
    _log(f"analyze ok n={an.get('n')} vision={vinfo}")
    if not an.get("n"):
        return _finish({"ok": False, "stage": "analyze", "detail": "0 clips (sube --min-score?)"},
                       job_id, work_root, started, stage_times)

    if os.getenv("YT_SHORTER_NO_REVIEW"):
        _log("review omitida (YT_SHORTER_NO_REVIEW)")
    else:
        rv = _run(3, "review", lambda: review_workdir(
            wd, prompts_version=settings.prompts_version, force=force))
        if not rv.get("ok"):
            return _finish({"ok": False, "stage": "review", "detail": rv}, job_id, work_root,
                           started, stage_times)
        _log(f"review ok n={rv.get('n')} {rv.get('review', '')}")

        # Loop Generator-Critic acotado (1 vuelta): si el revisor tiró ≥40% del
        # plan, el editor re-planifica con sus críticas (Reflexion) y se vuelve
        # a auditar. Si algo falla, vale el plan original ya revisado.
        cpath = Path(wd) / "clips.json"
        try:
            review_data = json.loads(cpath.read_text()).get("review", {})
        except (OSError, ValueError):
            review_data = {}
        if (not os.getenv("YT_SHORTER_NO_REVISION")
                and review_data.get("status") == "applied"
                and should_replan(review_data)):
            backup = cpath.read_text(encoding="utf-8")
            critique = critique_from_review(review_data)
            _log(f"review: drops altos ({review_data.get('dropped')}/"
                 f"{sum(int(review_data.get(k, 0) or 0) for k in ('kept', 'dropped', 'adjusted'))})"
                 f" → reciclo del plan con críticas (Generator-Critic 1/1)")
            an2 = analyze_workdir(wd, prompts_version=settings.prompts_version,
                                  force=True, critique=critique)
            ok2 = bool(an2.get("ok") and an2.get("n"))
            if ok2:
                rv2 = review_workdir(wd, prompts_version=settings.prompts_version, force=True)
                ok2 = bool(rv2.get("ok") and rv2.get("review") == "applied")
            if ok2:
                _log(f"review(2) ok n={rv2.get('n')} (plan reciclado)")
            else:
                cpath.write_text(backup, encoding="utf-8")
                _log("revisión 2 no aplicó; vale el plan original revisado")

    def _mk_callbacks(name: str):
        try:
            n_clips = len(json.loads((Path(wd) / "clips.json").read_text()).get("clips", []))
        except (OSError, ValueError):
            n_clips = 0
        _sub(job_id, work_root, "…", 0, n_clips)
        state = {"t": time.time(), "cur": "…", "done": 0, "total": n_clips}

        def _on_tick(frac):
            _sub(job_id, work_root, state["cur"], state["done"], state["total"], pct=frac)

        def _cb(done, total, label, cached):
            state["done"], state["total"], state["cur"] = done, total, label
            dt = round(time.time() - state["t"], 1)
            state["t"] = time.time()
            _log(f"{name} [{done}/{total}] {label} {'cached' if cached else f'{dt}s'}")
            _sub(job_id, work_root, label, done, total, cached,
                 pct=1.0 if cached else None)

        return _on_tick, _cb

    for i, name, fn in ((4, "clip", cut_all), (5, "caption", caption_all)):
        on_tick, cb = _mk_callbacks(name)
        r = _run(i, name, lambda fn=fn, cb=cb, on_tick=on_tick:
                 fn(wd, force=force, on_item=cb, on_tick=on_tick))
        if not r.get("ok"):
            return _finish({"ok": False, "stage": name, "detail": r}, job_id, work_root,
                           started, stage_times)
        if name == "clip":  # poda dirs de runs viejos antes de caption/judge
            from .clip import prune_short_dirs

            gone = prune_short_dirs(wd)
            if gone:
                _log(f"clip: podados {len(gone)} dirs viejos ({', '.join(gone[:4])}"
                     f"{', …' if len(gone) > 4 else ''})")

    # Judge independiente (asesor, nunca puerta): audita lo producido. Las
    # garantías duras son deterministas (bordes de frase, caption, encuadre);
    # el veredicto LLM es una señal más y jamás bloquea el pipeline.
    if os.getenv("YT_SHORTER_NO_JUDGE"):
        _log("judge omitido (YT_SHORTER_NO_JUDGE)")
    else:
        from .judge import judge_all

        on_tick, cb = _mk_callbacks("judge")
        rj = _run(6, "judge", lambda: judge_all(wd, force=force, on_item=cb))
        if not rj.get("ok"):
            _log(f"judge omitido: {str(rj.get('error'))[:160]} (no bloquea)")
        else:
            _log(f"judge ok n={rj.get('n')} ships={rj.get('ships')}")

    pk = _run(7, "package", lambda: package_workdir(wd, out_root=out_root, force=True))
    if not pk.get("ok"):
        return _finish({"ok": False, "stage": "package", "detail": pk}, job_id, work_root,
                       started, stage_times)
    _log(f"package ok out={pk['out']}")
    return _finish({"ok": True, "out": pk["out"], "n": pk["n"], "video_id": dl["video_id"]},
                   job_id, work_root, started, stage_times)


def _finish(result: dict, job_id: str, work_root: str, started: float = 0.0,
            stage_times: dict | None = None) -> dict:
    stage_times = dict(stage_times or {})
    if job_id:
        jobs = Path(work_root) / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / f"{job_id}.result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            total = len(STAGES)
            now = time.time()
            t0 = started or now
            base = {"total_stages": total, "started": t0, "updated": now,
                    "elapsed_s": round(now - t0, 1), "stage_times": stage_times,
                    "stage_start": 0.0, "stage_elapsed_s": 0.0}
            if result.get("ok"):
                payload = {"stage": "done", "stage_idx": total,
                           "status": "done", **base}
                _record_history(work_root, stage_times)
            else:
                stage = str(result.get("stage", STAGES[-1]))
                idx = STAGES.index(stage) + 1 if stage in STAGES else total
                payload = {"stage": stage, "stage_idx": idx,
                           "status": "error", **base}
            (jobs / f"{job_id}.progress.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return result
