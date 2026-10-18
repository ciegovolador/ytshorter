"""Tests F6: pipeline orquesta en orden (etapas mockeadas), queue roundtrip, web POC."""

import json
from pathlib import Path

import ytshorter.download as D
import ytshorter.transcribe as T
import ytshorter.analyze as A
import ytshorter.clip as C
import ytshorter.caption as S
import ytshorter.judge as J
import ytshorter.package as P
import ytshorter.review as R
from ytshorter.pipeline import run_pipeline


def test_pipeline_orden_y_corta_en_fallo(monkeypatch):
    calls = []
    monkeypatch.setattr(D, "download_url", lambda url, out_root="work", force=False: (
        calls.append("download") or {"ok": True, "video_id": "v1"}))
    monkeypatch.setattr(T, "transcribe_workdir", lambda *a, **k: (
        calls.append("transcribe") or {"ok": True, "segments": 5, "source": "t"}))
    monkeypatch.setattr(A, "analyze_workdir", lambda *a, **k: (
        calls.append("analyze") or {"ok": False, "error": "boom"}))

    res = run_pipeline("https://youtu.be/dQw4w9WgXcQ", work_root="/tmp/yt-noexiste")
    assert res["ok"] is False and res["stage"] == "analyze"
    assert calls == ["download", "transcribe", "analyze"]  # clip/caption/package no corren


def test_pipeline_ok_end_to_end_mock(monkeypatch, tmp_path):
    calls = []
    monkeypatch.delenv("YT_SHORTER_NO_REVIEW", raising=False)
    monkeypatch.setattr(D, "download_url", lambda url, out_root="work", force=False: {
        "ok": True, "video_id": "v1"})
    monkeypatch.setattr(T, "transcribe_workdir", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(A, "analyze_workdir", lambda *a, **k: {"ok": True, "n": 2})
    monkeypatch.setattr(R, "review_workdir", lambda *a, **k: (
        calls.append("review") or {"ok": True, "n": 2}))
    monkeypatch.setattr(C, "cut_all", lambda *a, **k: (
        calls.append("clip") or {"ok": True}))
    monkeypatch.setattr(S, "caption_all", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(J, "judge_all", lambda *a, **k: (
        calls.append("judge") or {"ok": True, "n": 2, "ships": 2}))
    monkeypatch.setattr(P, "package_workdir", lambda *a, **k: {
        "ok": True, "out": "dist/v1", "n": 2})
    # pipeline importa las etapas dentro de la función: el parche a los módulos aplica.
    res = run_pipeline("https://youtu.be/dQw4w9WgXcQ", out_root=str(tmp_path / "d"),
                       work_root=str(tmp_path / "w"))
    assert res["ok"] and res["n"] == 2 and res["out"] == "dist/v1"
    assert calls == ["review", "clip", "judge"]  # review explícita antes de clip; judge audita


def test_stages_review_explicita_entre_analyze_y_clip():
    from ytshorter.pipeline import STAGES

    assert STAGES == ("download", "transcribe", "analyze", "review", "clip",
                      "caption", "judge", "package")


def test_should_replan_y_critique():
    from ytshorter.pipeline import critique_from_review, should_replan

    rv = {"kept": 8, "dropped": 6, "adjusted": 0, "verdicts": [
        {"id": "short_01", "action": "drop", "reason": "salta de tema"},
        {"id": "short_02", "action": "adjust", "reason": "borde"},
        {"id": "short_03", "action": "keep", "reason": "ok"}]}
    assert should_replan(rv) is True
    assert should_replan({"kept": 12, "dropped": 2, "adjusted": 0}) is False
    assert should_replan({"kept": 1, "dropped": 1, "adjusted": 0}) is False  # plan chico
    assert should_replan({}) is False
    crit = critique_from_review(rv)
    assert "salta de tema" in crit and "borde" not in crit


def test_pipeline_recicla_plan_con_criticas_si_drops_altos(monkeypatch, tmp_path):
    """Generator-Critic acotado: drops ≥40% → re-plan con críticas (Reflexion)."""
    monkeypatch.delenv("YT_SHORTER_NO_REVIEW", raising=False)
    monkeypatch.delenv("YT_SHORTER_NO_REVISION", raising=False)
    w = tmp_path / "w"
    (w / "v1").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(D, "download_url", lambda url, out_root="work", force=False:
                        {"ok": True, "video_id": "v1"})
    monkeypatch.setattr(T, "transcribe_workdir", lambda *a, **k: {"ok": True})
    review_applied = {"status": "applied", "kept": 4, "dropped": 6, "adjusted": 0,
                      "verdicts": [{"id": "short_05", "action": "drop",
                                    "reason": "salta de tema"}]}

    def fake_analyze(workdir, **kw):
        calls.append(("analyze", kw.get("critique", "")))
        clips = {"clips": [{"id": "short_01"}], "review": {"status": "pending"}}
        if not kw.get("force"):  # primera pasada: plan sin revisar todavía
            clips["review"] = review_applied
        (Path(workdir) / "clips.json").write_text(json.dumps(clips))
        return {"ok": True, "n": 1 if kw.get("force") else 10}

    monkeypatch.setattr(A, "analyze_workdir", fake_analyze)
    monkeypatch.setattr(R, "review_workdir", lambda *a, **k: (
        calls.append(("review", k.get("force", False)))
        or {"ok": True, "n": 1, "review": "applied"}))
    monkeypatch.setattr(C, "cut_all", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(S, "caption_all", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(J, "judge_all", lambda *a, **k: {"ok": True, "n": 1, "ships": 1})
    monkeypatch.setattr(P, "package_workdir", lambda *a, **k:
                        {"ok": True, "out": "d/v1", "n": 1})
    res = run_pipeline("https://youtu.be/x", out_root=str(tmp_path / "d"), work_root=str(w))
    assert res["ok"]
    analyzes = [c for c in calls if c[0] == "analyze"]
    assert len(analyzes) == 2 and analyzes[1][1] == "- salta de tema"  # Reflexion
    assert [c for c in calls if c[0] == "review"][-1][1] is True  # 2ª auditoría con force


def test_queue_roundtrip_y_refresh_done(tmp_path):
    from ytshorter.queue import _save, list_jobs

    w = str(tmp_path)
    from pathlib import Path as _P

    _P(w, "jobs").mkdir(exist_ok=True)
    (_P(w) / "jobs" / "job-1.result.json").write_text(
        json.dumps({"ok": True, "out": "dist/v1", "n": 1}))
    _save(w, [{"id": "job-1", "url": "u", "status": "running", "pid": 1,
               "log": f"{w}/jobs/job-1.log", "out": "", "created": "t"}])
    jobs = list_jobs(w)
    assert jobs[0]["status"] == "done" and jobs[0]["out"] == "dist/v1"


def test_web_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("YT_SHORTER_WORK", str(tmp_path / "w"))
    monkeypatch.setenv("YT_SHORTER_OUT", str(tmp_path / "d"))
    from fastapi.testclient import TestClient

    from ytshorter.web import app

    c = TestClient(app)
    assert c.get("/").status_code == 200
    assert c.get("/").headers["cache-control"] == "no-store"
    assert c.get("/api/jobs").status_code == 200
    r = c.get("/api/version")
    assert r.status_code == 200
    import ytshorter
    from ytshorter.pipeline import STAGES
    assert r.json() == {"version": ytshorter.__version__, "stages": len(STAGES)}
    r = c.post("/api/jobs", json={"url": "no-es-url"})
    assert r.status_code == 400
