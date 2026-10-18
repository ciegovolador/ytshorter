"""Evals: reglas de negocio verificadas contra datos reales de sesión.

Diferencia con tests unitarios: los evals usan fixtures extraídos de corridas
reales (`tests/fixtures/`) y bloquean comportamientos observados en producción
(short_20, short_13, short_10). Si un eval falla, algo que funcionó en un video
real se rompió. Ver `docs/evals.md`.
"""

import json
import re
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "short20_transcript.json"


@pytest.fixture()
def fx_segments():
    return json.loads(FIX.read_text())["segments"]


def test_eval_short20_empieza_en_frase(fx_segments):
    """EVAL-01 (sesión: palabras sueltas al inicio). El inicio cae en borde de frase."""
    from ytshorter.analyze import build_sentences, snap_to_sentences

    sents = build_sentences(fx_segments)
    got = snap_to_sentences([{"id": "short_20", "start": 2966.68, "end": 3004.04}],
                            fx_segments)[0]
    assert any(abs(got["start"] - s["start"]) < 0.05 for s in sents), got["start"]
    assert got["start"] <= 2966.68  # nunca recorta habla por empezar tarde
    assert got["start"] == pytest.approx(2963.04, abs=0.1)


def test_eval_short20_termina_en_frase(fx_segments):
    """EVAL-02 (sesión: 'todas estas | flechitas con rojo' cortado)."""
    from ytshorter.analyze import build_sentences, snap_to_sentences

    sents = build_sentences(fx_segments)
    got = snap_to_sentences([{"id": "short_20", "start": 2966.68, "end": 3004.04}],
                            fx_segments)[0]
    assert any(abs(got["end"] - s["end"]) < 0.6 for s in sents), got["end"]
    assert 15 <= got["end"] - got["start"] <= 90


def test_eval_merge_no_duplica(fx_segments):
    """EVAL-03: el flujo fusionado nunca infla palabras; y las ventanas rodantes
    duplicadas (típico auto-caption) colapsan en una sola secuencia."""
    from ytshorter.analyze import merge_stream

    words = merge_stream(fx_segments)
    raw_toks = sum(len(s["text"].split()) for s in fx_segments)
    assert len(words) <= raw_toks
    dup = [
        {"start": 0.0, "end": 5.0, "text": "hola mundo cruel"},
        {"start": 3.0, "end": 8.0, "text": "mundo cruel adiós"},
        {"start": 6.0, "end": 10.0, "text": "adiós amigos"},
    ]
    assert [w["text"] for w in merge_stream(dup)] == [
        "hola", "mundo", "cruel", "adiós", "amigos"]


def test_eval_caption_marketing_rules(fx_segments):
    """EVAL-04 (sesión: captions listos para marketing)."""
    from ytshorter.caption import chunk_words, clip_segments, to_ass, words_of

    segs = clip_segments(fx_segments, 2963.04, 3008.75)
    chunks = chunk_words(words_of(segs))
    assert chunks and all(len(c) <= 8 for c in chunks)  # máx 2 líneas x 4
    cps = [sum(len(w["text"]) for w in c) / max(c[-1]["end"] - c[0]["start"], 0.01)
           for c in chunks]
    assert max(cps) <= 20.0  # techo broadcast (Netflix: 20 CPS adultos)
    ass = to_ass(segs)
    dialogues = [l for l in ass.splitlines() if l.startswith("Dialogue: 0,")]
    assert dialogues and all(d.count("\\N") <= 1 for d in dialogues)
    assert "&H0000EBFF" in ass  # highlight amarillo presente


def test_eval_crop_sigue_grafico_lateral(tmp_path):
    """EVAL-05 (sesión: short_20, flechas fuera de cuadro). Contenido rojo
    concentrado a la derecha → ventana a la derecha del centro."""
    import subprocess

    from ytshorter.reframe import choose_crop

    src = str(tmp_path / "src.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=white:size=1280x720:rate=10:duration=4",
         "-vf", "drawbox=x=900:y=100:w=120:h=500:color=red:t=fill",
         "-pix_fmt", "yuv420p", src], check=True)
    vf, info = choose_crop(src, 0.0, 4.0)
    m = re.search(r"x=(\d+)", vf)
    assert m and int(m.group(1)) > 437  # centro de 1280/405
    assert info["mode"] == "smart"


def test_eval_crop_no_mata_sin_caras(tmp_path):
    """EVAL-06: sin rostros ni gráficos, fallback a ventana válida (nunca vacío)."""
    import subprocess

    from ytshorter.reframe import choose_crop, _probe_wh

    src = str(tmp_path / "src.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=size=1280x720:rate=10:duration=3",
         "-pix_fmt", "yuv420p", src], check=True)
    vf, info = choose_crop(src, 0.0, 3.0)
    iw, _ = _probe_wh(src)
    m = re.search(r"w=(\d+).*x=(\d+)", vf)
    assert m and 0 <= int(m.group(2)) <= iw - int(m.group(1))


def test_eval_cache_corrupto_se_regenera(tmp_path):
    """EVAL-07 (sesión: short_10 moov atom not found). Parcial trunco → re-encode."""
    import subprocess

    from ytshorter.clip import cut_all

    wd = tmp_path / "w"
    wd.mkdir()
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=size=1280x720:rate=30:duration=12",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
         "-pix_fmt", "yuv420p", "-shortest", str(wd / "source.mp4")], check=True)
    (wd / "clips.json").write_text(json.dumps(
        {"clips": [{"id": "short_01", "start": 0.0, "end": 8.0, "score": 80}]}))
    cdir = wd / "short_01"
    cdir.mkdir()
    (cdir / "cut.mp4").write_bytes(b"parcial trunco sin moov")
    r = cut_all(str(wd))
    assert r["ok"] and r["cached_n"] == 0
    from ytshorter.ffmpeg import is_valid_video

    assert is_valid_video(str(cdir / "cut.mp4"), 8.0)
