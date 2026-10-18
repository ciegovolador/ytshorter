"""Tests judge: LLM-as-judge con llamadas mockeadas (sin red ni API key)."""

import json

import pytest


def _short_dir(tmp_path, name="short_01"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "title.txt").write_text("Título gancho\n")
    (d / "description.txt").write_text("Descripción del short.\n")
    (d / "metadata.json").write_text(json.dumps({
        "duration": 30.0, "score": 90, "hook_text": "hook",
        "framing": {"reason": "rostro centrado", "x": 437}}))
    (d / "subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nhola mundo cruel\n\n")
    (d / "video.mp4").write_bytes(b"fake")  # sin ffprobe válido → 0 frames
    return d


def test_judge_guarda_veredicto(monkeypatch, tmp_path):
    from ytshorter import judge as J

    monkeypatch.setattr(J, "judge_call", lambda *a, **k: {
        "ship": True, "score": 85, "issues": [], "notes": "sólido"})
    d = _short_dir(tmp_path)
    res = J.judge_short(str(d), "m", "k", n_frames=0)
    assert res["ship"] and res["score"] == 85
    saved = json.loads((d / "judgment.json").read_text())
    assert saved["judge"] == "v2" and saved["ship"] is True


def test_judge_api_caida_no_bloquea(monkeypatch, tmp_path):
    from ytshorter import judge as J

    def boom(*a, **k):
        raise Exception("api down")

    monkeypatch.setattr(J, "judge_call", boom)
    d = _short_dir(tmp_path)
    res = J.judge_short(str(d), "m", "k", n_frames=0)
    assert res["ship"] is True and res["score"] == -1  # asesor, no puerta


def test_judge_video_resume(monkeypatch, tmp_path):
    from ytshorter import judge as J

    monkeypatch.setattr(J, "judge_call", lambda *a, **k: {
        "ship": False, "score": 40, "issues": ["cara cortada"], "notes": "re-encuadrar"})
    _short_dir(tmp_path, "short_01")
    _short_dir(tmp_path, "short_02")
    res = J.judge_video(str(tmp_path), "m", "k", n_frames=0)
    assert res["n"] == 2 and res["ships"] == 0
    assert (tmp_path / "short_01" / "judgment.json").exists()


def test_judge_all_cachea_por_mtime(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    from ytshorter import judge as J

    calls = {"n": 0}

    def fake(system, user, images, model, key):
        calls["n"] += 1
        return {"ship": True, "score": 80, "issues": [], "notes": ""}

    monkeypatch.setattr(J, "judge_call", fake)
    _short_dir(tmp_path, "short_01")
    _short_dir(tmp_path, "short_02")
    r1 = J.judge_all(str(tmp_path))
    assert r1["ok"] and r1["n"] == 2 and r1["ships"] == 2 and calls["n"] == 2
    r2 = J.judge_all(str(tmp_path))
    assert calls["n"] == 2  # cacheado: sin llamadas nuevas
    assert r2["n"] == 2 and all(s.get("cached") for s in r2["shorts"])
    r3 = J.judge_all(str(tmp_path), force=True)
    assert calls["n"] == 4 and r3["ok"]


def test_judge_all_sin_llm_o_workdir_no_bloquea(monkeypatch, tmp_path):
    from ytshorter import judge as J

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert J.judge_all(str(tmp_path))["ok"] is False  # sin API key: aviso, no gate
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert J.judge_all(str(tmp_path / "noexiste"))["ok"] is False


def test_judge_call_reintenta_transitorio(monkeypatch):
    """429/503 se reintentan con backoff: el juez no muere al primer hipo."""
    import google.genai as genai_mod

    calls = []

    class ServerError(Exception):
        code = 503

    class FakeModels:
        @staticmethod
        def generate_content(**kw):
            calls.append(1)
            if len(calls) < 3:
                raise ServerError("503 UNAVAILABLE high demand")
            return type("Resp", (), {"text": '{"ship": true, "score": 77}'})()

    monkeypatch.setattr(genai_mod, "Client",
                        lambda api_key: type("C", (), {"models": FakeModels})())
    monkeypatch.setattr("time.sleep", lambda s: None)
    from ytshorter import judge as J

    assert J.judge_call("s", "u", [], "m", "k")["score"] == 77
    assert len(calls) == 3


def test_judge_call_definitivo_sin_reintentos(monkeypatch):
    import google.genai as genai_mod

    calls = []

    class BadRequest(Exception):
        code = 400

    class FakeModels:
        @staticmethod
        def generate_content(**kw):
            calls.append(1)
            raise BadRequest("400 INVALID_ARGUMENT: bad request")

    monkeypatch.setattr(genai_mod, "Client",
                        lambda api_key: type("C", (), {"models": FakeModels})())
    monkeypatch.setattr("time.sleep", lambda s: None)
    from ytshorter import judge as J

    with pytest.raises(BadRequest):
        J.judge_call("s", "u", [], "m", "k")
    assert len(calls) == 1


def test_judge_short_usa_clip_de_clips_json(monkeypatch, tmp_path):
    """La etapa judge corre antes que package: sin title.txt/metadata.json el
    contexto (título/hook/duración/score) sale de clips.json, no auditando ciego."""
    from ytshorter import judge as J

    captured = {}

    def fake(system, user, images, model, key):
        captured["user"] = user
        return {"ship": True, "score": 80, "issues": [], "notes": ""}

    monkeypatch.setattr(J, "judge_call", fake)
    d = tmp_path / "short_09"
    d.mkdir()
    (d / "video.mp4").write_bytes(b"x")  # sin metadata.json/title.txt
    J.judge_short(str(d), "m", "k", n_frames=0,
                  clip={"id": "short_09", "title": "Título gancho", "description": "Desc",
                        "hook_text": "arranca fuerte", "score": 88, "start": 1.0, "end": 31.0})
    assert "Título: Título gancho" in captured["user"]
    assert "Duración: 30.0s" in captured["user"]
    assert "Hook: arranca fuerte" in captured["user"]


def test_judge_short_cadena_con_fallback(monkeypatch, tmp_path):
    """Modelo juez principal caído (p.ej. 429 diario): cae al de respaldo en
    vez de degradar a asesor — independencia sin perder el veredicto."""
    from ytshorter import judge as J

    used = []

    def fake(system, user, images, model, key):
        used.append(model)
        if model == "gemini-2.5-pro":
            raise Exception("429 RESOURCE_EXHAUSTED")
        return {"ship": True, "score": 82, "issues": [], "notes": "ok"}

    monkeypatch.setattr(J, "judge_call", fake)
    d = _short_dir(tmp_path)
    res = J.judge_short(str(d), ["gemini-2.5-pro", "gemini-2.5-flash"], "k",
                        n_frames=0)
    assert used == ["gemini-2.5-pro", "gemini-2.5-flash"]
    assert res["score"] == 82 and res["model"] == "gemini-2.5-flash"
    saved = json.loads((d / "judgment.json").read_text())
    assert saved["model"] == "gemini-2.5-flash"


def test_judge_umbral_70_se_aplica_en_codigo(monkeypatch, tmp_path):
    """Aunque el modelo diga ship=true, <70 no viaja: el umbral queda en código."""
    from ytshorter import judge as J

    monkeypatch.setattr(J, "judge_call", lambda *a, **k: {
        "ship": True, "score": 65, "issues": [], "notes": "flojo pero ok"})
    d = _short_dir(tmp_path)
    res = J.judge_short(str(d), "m", "k", n_frames=0)
    assert res["ship"] is False and res["score"] == 65
    assert "70" in res["notes"]  # trazabilidad del umbral aplicado


def test_judge_umbral_no_baja_ships_altos(monkeypatch, tmp_path):
    from ytshorter import judge as J

    monkeypatch.setattr(J, "judge_call", lambda *a, **k: {
        "ship": True, "score": 75, "issues": [], "notes": ""})
    d = _short_dir(tmp_path)
    res = J.judge_short(str(d), "m", "k", n_frames=0)
    assert res["ship"] is True and res["score"] == 75
    assert "70" not in res["notes"]


def test_judge_frames_variable_por_duracion():
    from ytshorter.frames import frame_count

    assert frame_count(10) == 4    # piso: clips cortos igual tienen evidencia
    assert frame_count(60) == 5    # ~1 cada 12s
    assert frame_count(170) == 10  # techo de costo
    assert frame_count(0) == 4


def test_judge_short_auto_frames(monkeypatch, tmp_path):
    """Sin n_frames explícito el muestreo es variable (decide frames.py)."""
    from ytshorter import judge as J

    captured = {}

    def fake_sample(video, n=None, **k):
        captured["n"] = n
        return []

    monkeypatch.setattr(J, "sample_frames", fake_sample)
    monkeypatch.setattr(J, "judge_call", lambda *a, **k: {
        "ship": True, "score": 80, "issues": [], "notes": ""})
    d = _short_dir(tmp_path)
    J.judge_short(str(d), "m", "k")
    assert captured.get("n") is None


def test_caption_stats_bloques_y_cps(tmp_path):
    from ytshorter.judge import caption_stats

    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nabcdefghij\n\n"
                   "2\n00:00:01,000 --> 00:00:02,000\n"
                   "una línea larguísima que supera cuarenta y dos caracteres\n\n")
    st = caption_stats(str(srt))
    assert st["blocks"] == 2 and st["max_cps"] == 57.0 and st["long_lines"] == 1


def test_judge_all_ignora_shorts_fuera_de_clips_json(monkeypatch, tmp_path):
    """Solo se audita el set vigente de clips.json: los dirs viejos de un run
    anterior (menos clips) no deben consumir API ni reaparecer en el resumen."""
    from ytshorter import judge as J

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(J, "judge_call", lambda *a, **k: {
        "ship": True, "score": 80, "issues": [], "notes": "ok"})
    _short_dir(tmp_path, "short_01")
    _short_dir(tmp_path, "short_09")  # viejo: ya no está en clips.json
    (tmp_path / "clips.json").write_text(
        json.dumps({"clips": [{"id": "short_01"}]}), encoding="utf-8")
    res = J.judge_all(str(tmp_path), n_frames=0)
    assert res["ok"] and res["n"] == 1
    assert [r["id"] for r in res["shorts"]] == ["short_01"]


def test_judge_all_sin_clips_json_audita_todos(monkeypatch, tmp_path):
    """Sin clips.json (uso legacy) no se filtra nada: se audita lo que hay."""
    from ytshorter import judge as J

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(J, "judge_call", lambda *a, **k: {
        "ship": True, "score": 80, "issues": [], "notes": "ok"})
    _short_dir(tmp_path, "short_01")
    _short_dir(tmp_path, "short_02")
    res = J.judge_all(str(tmp_path), n_frames=0)
    assert res["n"] == 2
