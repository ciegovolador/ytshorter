"""queue.py (F6) — jobs.json + subprocess en background. La web solo encola y lee estado."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def jobs_dir(work_root: str = "work") -> Path:
    d = Path(work_root) / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _jobs_file(work_root: str) -> Path:
    return jobs_dir(work_root) / "jobs.json"


def _load(work_root: str) -> list[dict]:
    f = _jobs_file(work_root)
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text()).get("jobs", [])
    except Exception:
        return []


def _save(work_root: str, jobs: list[dict]) -> None:
    _jobs_file(work_root).write_text(json.dumps({"jobs": jobs}, ensure_ascii=False, indent=1))


def create_job(url: str, out_root: str = "dist", work_root: str = "work") -> dict:
    jid = f"job-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    log = str(jobs_dir(work_root) / f"{jid}.log")
    cmd = [sys.executable, "-m", "ytshorter", "pipeline", url,
           "-o", out_root, "-w", work_root, "--job-id", jid]
    with open(log, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True)
    job = {"id": jid, "url": url, "status": "running", "pid": proc.pid,
           "log": log, "out": "", "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    jobs = _load(work_root)
    jobs.insert(0, job)
    _save(work_root, jobs)
    return job


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def refresh(job: dict, work_root: str = "work") -> dict:
    job = dict(job)
    if job.get("status") in ("done", "error"):
        _attach_progress(job, work_root)
        return job
    res_file = jobs_dir(work_root) / f"{job['id']}.result.json"
    if res_file.exists():
        try:
            res = json.loads(res_file.read_text())
            job["status"] = "done" if res.get("ok") else "error"
            job["out"] = res.get("out", "")
            job["result"] = res
        except Exception as e:
            job["status"] = "error"
            job["result"] = {"ok": False, "error": f"result corrupto: {e}"}
    elif not _alive(job.get("pid", -1)):
        job["status"] = "error"
        job["result"] = {"ok": False, "error": "proceso terminó sin result (ver log)"}
    _attach_progress(job, work_root)
    return job


def _attach_progress(job: dict, work_root: str) -> None:
    """Lee jobs/<jid>.progress.json y añade breakdown por etapa + ETA total/por etapa.

    ETA: si hay historial (stage_history.json) usa medianas por etapa;
    si no, fallback lineal. `eta_by_stage` + `eta_source` lo hacen explícito.
    """
    import statistics

    from .pipeline import STAGES

    p = jobs_dir(work_root) / f"{job.get('id')}.progress.json"
    try:
        prog = json.loads(p.read_text())
    except (OSError, ValueError):
        return
    try:
        total = int(prog.get("total_stages", len(STAGES)))
        idx = int(prog.get("stage_idx", 0))
        t0 = float(prog.get("started", 0.0))
    except (TypeError, ValueError):
        return
    try:
        hist = json.loads((jobs_dir(work_root) / "stage_history.json").read_text())
    except (OSError, ValueError):
        hist = {}
    medians = {}
    for s in STAGES:
        vals = (hist or {}).get(s) or []
        try:
            medians[s] = round(float(statistics.median(vals)), 1) if vals else None
        except statistics.StatisticsError:
            medians[s] = None

    now = time.time()
    finished = job.get("status") in ("done", "error") or prog.get("status") in ("done", "error")
    elapsed = float(prog.get("elapsed_s", 0.0))
    if not finished and t0:
        elapsed = round(now - t0, 1)
    stage_times = prog.get("stage_times") or {}
    t_stage0 = float(prog.get("stage_start", 0.0) or 0.0)
    stage_elapsed = round(now - t_stage0, 1) if (not finished and t_stage0) else float(
        prog.get("stage_elapsed_s", 0.0))

    # Breakdown por etapa: done / current / failed / pending.
    cur = prog.get("stage", "")
    pstatus = prog.get("status", "running")
    breakdown = []
    for i, s in enumerate(STAGES):
        if pstatus == "done":
            state = "done"
        elif pstatus == "error" or job.get("status") == "error":
            state = "done" if i < idx - 1 else ("failed" if s == cur else "pending")
        elif not finished:
            state = "done" if i < idx - 1 else ("current" if s == cur else "pending")
        else:
            state = "pending"
        breakdown.append({
            "name": s, "state": state,
            "elapsed_s": float(stage_times.get(s, 0.0)),
            "median_s": medians.get(s),
        })

    if finished:
        eta, eta_by, source = 0.0, {}, "done"
    elif any(v is not None for v in medians.values()):
        eta_by = {}
        cur_rem = None
        if cur in STAGES and medians.get(cur) is not None:
            cur_rem = max(round(medians[cur] - stage_elapsed, 1), 0.0)
            eta_by[cur] = cur_rem
        for s in STAGES[STAGES.index(cur) + 1:] if cur in STAGES else []:
            if medians.get(s) is not None:
                eta_by[s] = medians[s]
        eta = round(sum(eta_by.values()), 1)
        source = "history"
    elif idx > 0 and elapsed > 0:
        eta, eta_by, source = round(elapsed / idx * (total - idx), 1), {}, "linear"
    else:
        eta, eta_by, source = None, {}, "none"

    prog["elapsed_s"] = elapsed
    prog["stage_elapsed_s"] = stage_elapsed
    try:
        t_sub = float(prog.get("sub_updated", 0.0) or 0.0)
        prog["sub_elapsed_s"] = round(now - t_sub, 1) if (not finished and t_sub) else 0.0
    except (TypeError, ValueError):
        prog["sub_elapsed_s"] = 0.0
    prog["eta_s"] = eta
    prog["eta_by_stage"] = eta_by
    prog["eta_source"] = source
    prog["stages"] = breakdown
    job["progress"] = prog


def list_jobs(work_root: str = "work") -> list[dict]:
    jobs = [refresh(j, work_root) for j in _load(work_root)]
    _save(work_root, jobs)
    return jobs


def get_job(jid: str, work_root: str = "work", tail: int = 50) -> dict | None:
    for j in list_jobs(work_root):
        if j["id"] == jid:
            j = dict(j)
            try:
                lines = Path(j["log"]).read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            j["log_tail"] = lines[-tail:]
            return j
    return None
