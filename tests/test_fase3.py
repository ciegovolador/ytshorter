"""Tests F3: prompts versionados + lógica pura de analyze (sin red ni API key)."""

import json

import pytest

from ytshorter import analyze as A


def test_prompts_v1_cargan():
    p = A.load_prompts("v1")
    assert "editor" in p and "virality" in p and "packaging" in p
    assert "autocontenido" in p["editor"].lower() or "autocontenidos" in p["editor"].lower()
    assert "70" in p["virality"]


def test_build_chunks_video_corto_un_chunk():
    segs = [{"start": float(i * 10), "end": float(i * 10 + 9), "text": f"frase {i}"} for i in range(30)]
    assert len(A.build_chunks(segs)) == 1


def test_dedupe_queda_mejor_score():
    clips = [
        {"start": 0.0, "end": 40.0, "score": 75, "title": "peor"},
        {"start": 5.0, "end": 45.0, "score": 90, "title": "mejor"},
    ]
    kept = A.dedupe_clips(clips)
    assert len(kept) == 1 and kept[0]["title"] == "mejor"


def test_snap_alinea_a_frase():
    segs = [{"start": 0.0, "end": 5.0, "text": "a"}, {"start": 5.0, "end": 12.0, "text": "b"}]
    out = A.snap_to_sentences([{"start": 1.2, "end": 11.1, "score": 80}], segs)
    assert out[0]["start"] == 0.0 and out[0]["end"] == 12.0


def test_analyze_sin_key_falla_claro(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    wd = tmp_path / "vid"
    wd.mkdir()
    (wd / "transcript.json").write_text('{"video_id":"vid","segments":[{"start":0,"end":30,"text":"hola mundo"}]}')
    res = A.analyze_workdir(str(wd), force=True)
    assert res["ok"] is False and "GEMINI_API_KEY" in res["error"]


def test_analyze_cache(tmp_path):
    wd = tmp_path / "vid"
    wd.mkdir()
    (wd / "clips.json").write_text('{"clips":[]}')
    res = A.analyze_workdir(str(wd))
    assert res["ok"] and res["cached"] and res["n"] == 0


def test_review_aplica_keep_drop_adjust():
    from ytshorter.analyze import apply_verdicts

    clips = [
        {"id": "short_01", "start": 0.0, "end": 30.0},
        {"id": "short_02", "start": 40.0, "end": 70.0},
        {"id": "short_03", "start": 80.0, "end": 110.0},
    ]
    verdicts = [
        {"id": "short_01", "action": "keep", "reason": "ok"},
        {"id": "short_02", "action": "drop", "reason": "relleno"},
        {"id": "short_03", "action": "adjust", "start": 82.0, "end": 105.0, "reason": "cierre"},
    ]
    kept, stats = apply_verdicts(clips, verdicts)
    assert [c["id"] for c in kept] == ["short_01", "short_03"]
    assert stats == {"kept": 1, "dropped": 1, "adjusted": 1}
    assert kept[1]["start"] == 82.0 and kept[1]["duration"] == 23.0


def test_review_ignora_veredicto_invalido():
    from ytshorter.analyze import apply_verdicts

    clips = [{"id": "short_01", "start": 0.0, "end": 30.0}]
    kept, stats = apply_verdicts(clips, [
        {"id": "short_01", "action": "adjust", "start": 50.0, "end": 10.0}])
    assert kept[0]["start"] == 0.0 and stats["kept"] == 1  # seguro: keep
    kept, _ = apply_verdicts(clips, [{"id": "otro", "action": "drop"}])
    assert len(kept) == 1  # ids desconocidos no tocan nada


def test_review_llm_roto_no_mata_plan(monkeypatch):
    from ytshorter import analyze as _A

    monkeypatch.setattr(_A, "call_gemini", lambda *a, **k: (_ for _ in ()).throw(Exception("api down")))
    res = _A.review_clips([{"id": "short_01", "start": 0.0, "end": 30.0}],
                          [], {"reviewer": "x"}, "m", "k")
    assert res["ok"] is False and res["verdicts"] == []


def test_gemini_reintenta_transitorio(monkeypatch):
    """503 UNAVAILABLE ('high demand') se reintenta con backoff y termina OK."""
    import google.genai as genai_mod

    calls = []

    class ServerError(Exception):
        code = 503

    class FakeModels:
        @staticmethod
        def generate_content(**kw):
            calls.append(1)
            if len(calls) < 3:
                raise ServerError(
                    "503 UNAVAILABLE. This model is currently experiencing high demand.")
            return type("Resp", (), {"text": '{"clips": [{"start": 0}]}'})()

    monkeypatch.setattr(genai_mod, "Client",
                        lambda api_key: type("C", (), {"models": FakeModels})())
    monkeypatch.setattr("time.sleep", lambda s: None)
    out = A.call_gemini("sys", "user", "gemini-2.5-flash", "k")
    assert out == {"clips": [{"start": 0}]} and len(calls) == 3


def test_gemini_fence_sin_newline_no_indexerror(monkeypatch):
    """Un ``` pelado no puede tirar IndexError: JSON inválido claro, no crash."""
    import google.genai as genai_mod

    class FakeModels:
        @staticmethod
        def generate_content(**kw):
            return type("R", (), {"text": "```"})()

    monkeypatch.setattr(genai_mod, "Client",
                        lambda api_key: type("C", (), {"models": FakeModels})())
    with pytest.raises(ValueError):  # JSONDecodeError, no IndexError de fence
        A.call_gemini("sys", "user", "m", "k")


def test_analyze_usa_titulo_de_source_info_json(monkeypatch, tmp_path):
    """El título del prompt sale del sidecar real (source.info.json), no de info.json."""
    from ytshorter import analyze as _A

    captured = []

    def fake(system, user, model, key):
        captured.append(user if isinstance(user, str) else str(user))
        return {"clips": []}

    monkeypatch.setattr(_A, "call_gemini", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    wd = tmp_path / "vid"
    wd.mkdir()
    (wd / "transcript.json").write_text(
        '{"video_id":"vid","segments":[{"start":0,"end":30,"text":"hola"}]}')
    (wd / "source.info.json").write_text('{"title": "Título real", "duration": 30}')
    res = _A.analyze_workdir(str(wd), force=True)
    assert res["ok"] and any("Título real" in u for u in captured)


def test_cli_review_respeta_prompts_version(monkeypatch, tmp_path):
    import ytshorter.cli as cli
    import ytshorter.review as R

    captured = {}

    def fake_review(workdir, prompts_version="v3", force=False):
        captured["pv"] = prompts_version
        return {"ok": True, "n": 0, "clips": ""}

    monkeypatch.setattr(R, "review_workdir", fake_review)
    monkeypatch.setenv("YT_SHORTER_PROMPTS", "v9")
    assert cli.main(["review", str(tmp_path)]) == 0
    assert captured["pv"] == "v9"


def test_gemini_no_transitorio_falla_rapido(monkeypatch):
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
    with pytest.raises(BadRequest):
        A.call_gemini("sys", "user", "m", "k")
    assert len(calls) == 1  # sin reintentos


def test_gemini_transitorio_agota_intentos(monkeypatch):
    import google.genai as genai_mod

    calls = []

    class ServerError(Exception):
        code = 503

    class FakeModels:
        @staticmethod
        def generate_content(**kw):
            calls.append(1)
            raise ServerError("503 UNAVAILABLE high demand")

    monkeypatch.setattr(genai_mod, "Client",
                        lambda api_key: type("C", (), {"models": FakeModels})())
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(ServerError):
        A.call_gemini("sys", "user", "m", "k")
    assert len(calls) == A.LLM_ATTEMPTS


def test_analyze_propone_y_review_explicita_aplica(monkeypatch, tmp_path):
    """analyze deja el plan `pending`; la etapa review (4/7) audita y aplica (drop)."""
    from ytshorter import analyze as _A
    from ytshorter.review import review_workdir

    calls = []

    def fake_gemini(system, user, model, key):
        calls.append(system[:20])
        if "revisor independiente" in system:
            return {"verdicts": [
                {"id": "short_01", "action": "keep", "reason": "hook fuerte"},
                {"id": "short_02", "action": "drop", "reason": "duplicado"}]}
        return {"clips": [
            {"start": 0.0, "end": 40.0, "score": 90, "title": "t1", "hook_text": "h1"},
            {"start": 50.0, "end": 90.0, "score": 85, "title": "t2", "hook_text": "h2"}]}

    monkeypatch.setattr(_A, "call_gemini", fake_gemini)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    wd = tmp_path / "vid"
    wd.mkdir()
    (wd / "transcript.json").write_text(
        '{"video_id":"vid","segments":[{"start":0,"end":45,"text":"Hola mundo. Esto sigue."},'
        '{"start":50,"end":95,"text":"Otra idea completa aquí."}]}')
    res = _A.analyze_workdir(str(wd), force=True)
    import json as _j

    data = _j.loads((wd / "clips.json").read_text())
    assert res["ok"] and res["n"] == 2
    assert data["review"]["status"] == "pending"  # analyze no revisa: la etapa review decide

    res2 = review_workdir(str(wd))
    data = _j.loads((wd / "clips.json").read_text())
    assert res2["ok"] and res2["n"] == 1 and res2["review"] == "applied"  # el drop aplicó
    assert data["review"]["status"] == "applied"
    assert data["clips"][0]["review"]["action"] == "keep"
    assert len(calls) == 2  # 1 plan + 1 revisión


def _wd_transcript(tmp_path, name="vid"):
    import json as _j

    wd = tmp_path / name
    wd.mkdir(exist_ok=True)
    segs = []
    t = 0.0
    for i in range(40):
        segs.append({"start": t, "end": t + 4.0, "text": f"Frase número {i} completa."})
        t += 5.0
    (wd / "transcript.json").write_text(
        '{"video_id":"vid","segments":' + _j.dumps(segs) + "}")
    return wd


def test_duracion_la_dicta_la_idea(monkeypatch, tmp_path):
    """Ni 25s ni 120s se podan por duración: piso 10s, techo 170s."""
    import json as _j

    from ytshorter import analyze as _A

    monkeypatch.setattr(_A, "call_gemini", lambda *a, **k: {"clips": [
        {"start": 0.0, "end": 25.0, "score": 90, "title": "corto",
         "hook_text": "h"},
        {"start": 50.0, "end": 170.0, "score": 90, "title": "largo",
         "hook_text": "h"},
        {"start": 184.5, "end": 187.5, "score": 90, "title": "mini",
         "hook_text": "h"},
        {"start": 190.5, "end": 194.5, "score": 90, "title": "casi",
         "hook_text": "h"},
    ]})
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("YT_SHORTER_MIN_CLIPS", "0")  # sin piso: mide solo duración
    wd = _wd_transcript(tmp_path)
    res = _A.analyze_workdir(str(wd), force=True)
    data = _j.loads((wd / "clips.json").read_text())
    durs = sorted(c["end"] - c["start"] for c in data["clips"])
    assert res["ok"] and res["n"] == 2  # 25s y 120s viven; 5s y 6s mueren
    assert durs[0] >= 10 and durs[1] <= 170


def test_review_adjust_largo_valido():
    from ytshorter.analyze import apply_verdicts

    clips = [{"id": "short_01", "start": 0.0, "end": 40.0}]
    kept, stats = apply_verdicts(
        clips, [{"id": "short_01", "action": "adjust",
                 "start": 0.0, "end": 100.0, "reason": "cierre"}])
    assert kept[0]["end"] == 100.0 and stats["adjusted"] == 1


def _synth_transcript(minutes=25):
    """Transcript sintético con frases de ~10s hasta `minutes` de duración."""
    segs, t = [], 0.0
    i = 0
    while t < minutes * 60:
        i += 1
        segs.append({"start": round(t, 2), "end": round(t + 10, 2),
                     "text": f"Frase numero {i} del transcript sintetico de prueba."})
        t += 10
    return segs


def test_fallback_clips_determinista_sin_solape():
    """Respaldo local (BR-030): ventanas alineadas a frases, deterministas,
    sin solapar >50% entre sí, y puntuadas por debajo del editor (≤62)."""
    from ytshorter.sentences import fallback_clips

    segs = _synth_transcript(25)
    a = fallback_clips(segs, 6)
    b = fallback_clips(segs, 6)
    assert a == b and len(a) == 6
    for c in a:
        assert 15.0 <= c["end"] - c["start"] <= 170.0
        assert c["score"] <= 62 and c["source"] == "fallback-local"
    for i, c in enumerate(a):
        for k in a[i + 1:]:
            inter = max(0.0, min(c["end"], k["end"]) - max(c["start"], k["start"]))
            span = max(c["end"], k["end"]) - min(c["start"], k["start"])
            assert inter / span <= 0.5


def test_analyze_piso_volumen_llm_tacaño(tmp_path, monkeypatch):
    """Si el LLM propone muy pocos clips, el fallback local completa hasta el
    piso (~1 cada 4 min, base 8): el volumen no depende del humor del modelo."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("YT_SHORTER_NO_VISION", "1")
    monkeypatch.setattr(A, "call_gemini", lambda *a, **k: {"clips": [
        {"start": 0.0, "end": 30.0, "score": 95, "title": "único"}]})
    wd = tmp_path / "vid"
    wd.mkdir()
    (wd / "transcript.json").write_text(json.dumps(
        {"video_id": "vid", "segments": _synth_transcript(25)}))
    res = A.analyze_workdir(str(wd), force=True)
    assert res["ok"]
    clips = json.loads((wd / "clips.json").read_text())["clips"]
    assert len(clips) >= 8
    assert any(c.get("source") == "fallback-local" for c in clips)
    assert clips[0]["score"] == 95  # el mejor del LLM no se desplaza


def test_prompts_v4_volumen():
    """v4 (BR-030): editor con objetivo de cobertura explícito y reviewer que
    solo descarta por causa dura; vision.md sigue presente."""
    p = A.load_prompts("v4")
    assert "Cobertura (v4)" in p["editor"]
    assert "causa dura" in p["reviewer"]
    assert p.get("vision")
