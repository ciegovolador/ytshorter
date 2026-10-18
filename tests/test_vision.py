"""Tests vision: verificación multimodal de candidatos (sin red ni ffmpeg)."""

import json

import pytest


def test_load_prompts_v3_incluye_vision():
    from ytshorter.analyze import load_prompts

    p = load_prompts("v3")
    assert "visual_ok" in p["vision"] and p["editor"] and p["reviewer"]
    assert p["vision"] != load_prompts("v2").get("vision", "")  # v2 no trae vision
    assert load_prompts("v2")["editor"]  # v2 sigue cargando (sin vision.md)


def test_sample_frames_span_respeta_rango(monkeypatch):
    from ytshorter import frames as F

    seen = []
    monkeypatch.setattr(F.shutil, "which", lambda x: "/usr/bin/ffmpeg")

    def fake_run(cmd, **k):
        seen.append(float(cmd[cmd.index("-ss") + 1]))
        return type("R", (), {"stdout": b"jpg"})()

    monkeypatch.setattr(F.subprocess, "run", fake_run)
    imgs = F.sample_frames("v.mp4", n=4, span=(100.0, 140.0))
    assert len(imgs) == 4
    assert all(100.0 <= t <= 140.0 for t in seen)
    assert min(seen) < 105 and max(seen) > 135  # cubre el rango, no el video


def test_vision_veta_y_anota(monkeypatch, tmp_path):
    from ytshorter import analyze as A
    from ytshorter import vision as V

    monkeypatch.setattr(V, "sample_frames", lambda *a, **k: [])

    def fake_gemini(system, user, model, key):
        return {"verdicts": [
            {"id": "short_01", "visual_ok": False, "reason": "sujeto fuera de cuadro"},
            {"id": "short_02", "visual_ok": True, "reason": "ok"}]}

    monkeypatch.setattr(A, "call_gemini", fake_gemini)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    clips = [{"id": "short_01", "start": 0.0, "end": 30.0},
             {"id": "short_02", "start": 40.0, "end": 70.0}]
    res = V.vision_review(str(v), clips, {"vision": "x"}, "m", "k")
    assert res["ok"] and len(res["verdicts"]) == 2
    kept, stats = V.apply_vision(clips, res["verdicts"])
    assert [c["id"] for c in kept] == ["short_02"]
    assert stats == {"kept": 1, "dropped": 1}
    assert kept[0]["vision"]["ok"] is True


def test_vision_batch_por_lotes(monkeypatch, tmp_path):
    from ytshorter import analyze as A
    from ytshorter import vision as V

    monkeypatch.setattr(V, "sample_frames", lambda *a, **k: [])
    monkeypatch.setattr(V, "VISION_BATCH", 3)
    calls = []

    def fake(system, user, model, key):
        calls.append(user[0] if isinstance(user, list) else user)
        return {"verdicts": [{"id": f"c{len(calls)}", "visual_ok": True}]}

    monkeypatch.setattr(A, "call_gemini", fake)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    clips = [{"id": f"short_{i:02d}", "start": i * 10.0, "end": i * 10.0 + 30.0}
             for i in range(1, 8)]
    res = V.vision_review(str(v), clips, {"vision": "p"}, "m", "k")
    assert res["ok"] and len(calls) == 3 and len(res["verdicts"]) == 3


def test_vision_caida_no_rompe_plan(monkeypatch, tmp_path):
    from ytshorter import analyze as A
    from ytshorter import vision as V

    monkeypatch.setattr(V, "sample_frames", lambda *a, **k: [])
    monkeypatch.setattr(A, "call_gemini", lambda *a, **k: (_ for _ in ()).throw(
        Exception("api down")))
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    res = V.vision_review(str(v), [{"id": "s1", "start": 0.0, "end": 20.0}],
                          {"vision": "p"}, "m", "k")
    assert res["ok"] is False and "error" in res


def test_vision_flag_la_desactiva(monkeypatch):
    from ytshorter import vision as V

    monkeypatch.setenv("YT_SHORTER_NO_VISION", "1")
    res = V.vision_review("x.mp4", [{"id": "s1", "start": 0, "end": 10}],
                          {"vision": "p"}, "m", "k")
    assert res["ok"] is False and "NO_VISION" in res["skipped"]


def test_call_gemini_acepta_lista_multimodal(monkeypatch):
    import google.genai as genai_mod

    captured = {}

    class FakeModels:
        @staticmethod
        def generate_content(**kw):
            captured.update(kw)
            return type("R", (), {"text": '{"verdicts": []}'})()

    monkeypatch.setattr(genai_mod, "Client",
                        lambda api_key: type("C", (), {"models": FakeModels})())
    from ytshorter.analyze import call_gemini

    out = call_gemini("sys", ["rótulo short_01", b"jpg"], "m", "k")
    assert captured["contents"] == ["rótulo short_01", b"jpg"]
    assert out == {"verdicts": []}


def test_analyze_vision_veta_antes_de_review(monkeypatch, tmp_path):
    """Con frames reales del rango, un candidato inviable visualmente se cae
    ya en analyze (no llega a review ni a ffmpeg)."""
    from ytshorter import analyze as A
    from ytshorter import vision as V

    monkeypatch.setattr(V, "sample_frames", lambda *a, **k: [])
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    def fake(system, user, model, key):
        if "verificador visual" in system.lower():
            return {"verdicts": [
                {"id": "short_01", "visual_ok": False, "reason": "no está en cuadro"},
                {"id": "short_02", "visual_ok": True, "reason": "ok"}]}
        return {"clips": [
            {"start": 0.0, "end": 40.0, "score": 90, "title": "t1", "hook_text": "h1"},
            {"start": 50.0, "end": 90.0, "score": 85, "title": "t2", "hook_text": "h2"}]}

    monkeypatch.setattr(A, "call_gemini", fake)
    wd = tmp_path / "vid"
    wd.mkdir()
    (wd / "transcript.json").write_text(json.dumps({"video_id": "vid", "segments": [
        {"start": 0, "end": 45, "text": "Hola mundo. Esto sigue."},
        {"start": 50, "end": 95, "text": "Otra idea completa aquí."}]}))
    (wd / "source.mp4").write_bytes(b"x")
    res = A.analyze_workdir(str(wd), force=True)
    data = json.loads((wd / "clips.json").read_text())
    assert res["ok"] and res["n"] == 1
    assert data["clips"][0]["title"] == "t2"
    assert data["clips"][0]["id"] == "short_01"  # renumerado tras la poda
    assert data["vision"]["status"] == "applied" and data["vision"]["dropped"] == 1
    assert data["clips"][0]["vision"]["ok"] is True


def test_review_vision_veta_tras_verdicts(monkeypatch, tmp_path):
    from ytshorter import analyze as A
    from ytshorter import vision as V
    from ytshorter.review import review_workdir

    monkeypatch.setattr(V, "sample_frames", lambda *a, **k: [])
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    def fake(system, user, model, key):
        if "verificador visual" in system.lower():
            return {"verdicts": [
                {"id": "short_02", "visual_ok": False,
                 "reason": "habla de un gráfico que no se ve"}]}
        return {"verdicts": [
            {"id": "short_01", "action": "keep", "reason": "ok"},
            {"id": "short_02", "action": "keep", "reason": "ok"}]}

    monkeypatch.setattr(A, "call_gemini", fake)
    wd = tmp_path / "vid"
    wd.mkdir()
    (wd / "transcript.json").write_text(
        '{"video_id":"vid","segments":[{"start":0,"end":60,"text":"a. b. c."}]}')
    (wd / "source.mp4").write_bytes(b"x")
    (wd / "clips.json").write_text(json.dumps({"video_id": "vid", "clips": [
        {"id": "short_01", "start": 0.0, "end": 30.0},
        {"id": "short_02", "start": 35.0, "end": 60.0}]}))
    res = review_workdir(str(wd))
    data = json.loads((wd / "clips.json").read_text())
    assert res["ok"] and res["n"] == 1
    assert data["review"]["vision"]["dropped"] == 1
    assert [c["id"] for c in data["clips"]] == ["short_01"]
    assert data["clips"][0]["vision"]["ok"] is True
