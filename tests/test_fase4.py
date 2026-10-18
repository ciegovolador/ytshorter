"""Tests F4: subtítulos puros + e2e sintético cut→caption con ffmpeg real."""

import json
import subprocess

from ytshorter.caption import clip_segments, fmt_srt, to_ass, to_srt
from ytshorter.caption import MAX_LINE_UNITS, chunk_words, split_lines, words_of
from ytshorter.caption import _line_units
from ytshorter.clip import cut_all
from ytshorter.caption import caption_all
from ytshorter.reframe import VERTICAL_VF


def test_fmt_srt():
    assert fmt_srt(61.234) == "00:01:01,234"


def test_srt_ass_no_vacios():
    segs = [{"start": 0.0, "end": 2.5, "text": "hola mundo"}]
    assert "hola mundo" in to_srt(segs) and "-->" in to_srt(segs)
    ass = to_ass(segs)
    assert "Dialogue: 0," in ass and "\\k" in ass  # karaoke palabra-por-palabra
    assert "&H0000EBFF" in ass and "&H00FFFFFF" in ass  # highlight + base


def test_ass_karaoke_suma_cuadra():
    import re
    segs = [{"start": 0.0, "end": 2.0, "text": "uno dos tres"}]
    ass = to_ass(segs)
    line = [l for l in ass.splitlines() if l.startswith("Dialogue: 0,")][0]
    m = re.match(r"Dialogue: 0,(\d+:\d\d:\d\d\.\d\d),(\d+:\d\d:\d\d\.\d\d),", line)
    def cs(t):
        h, mnt, rest = t.split(":")
        return (int(h) * 3600 + int(mnt) * 60 + float(rest)) * 100
    total = round(cs(m.group(2)) - cs(m.group(1)))
    assert sum(int(k) for k in re.findall(r"\\k(\d+)", line)) == total


def test_ass_chunking_max_2_lineas():
    segs = [{"start": 0.0, "end": 10.0,
             "text": "una dos tres cuatro cinco seis siete ocho nueve diez"}]
    ass = to_ass(segs)
    dialogues = [l for l in ass.splitlines() if l.startswith("Dialogue: 0,")]
    assert len(dialogues) == 2  # 10 palabras → 8 + 2
    assert all(l.count("\\N") <= 1 for l in dialogues)  # máx 2 líneas


def test_ass_sin_palabras_no_dialogue():
    assert "Dialogue: 0," not in to_ass([{"start": 0.0, "end": 1.0, "text": "   "}])
    assert "Dialogue: 0," not in to_ass([])


def test_words_of_usa_whisper_si_existen():
    segs = [{"start": 0.0, "end": 2.0, "text": "hola mundo",
             "words": [{"start": 0.1, "end": 0.5, "word": "hola"},
                       {"start": 0.6, "end": 1.0, "word": "mundo"}]}]
    assert [w["text"] for w in words_of(segs)] == ["hola", "mundo"]
    assert words_of(segs)[0]["start"] == 0.1


def test_words_of_estima_sin_timings():
    words = words_of([{"start": 0.0, "end": 2.0, "text": "aa bbbbb"}])
    assert len(words) == 2 and words[0]["start"] == 0.0 and words[-1]["end"] == 2.0
    assert words[1]["start"] == words[0]["end"]  # reparto encadenado
    assert words[0]["end"] - words[0]["start"] < words[1]["end"] - words[1]["start"]


def test_words_of_ventana_rolling_es_monotona():
    """Segmentos rolling de whisper: el `end` infla con solape; el audio real
    del segmento n cierra donde arranca el n+1. Nada de CPS basura ni dos
    palabras encendidas a la vez."""
    segs = [{"start": 0.0, "end": 8.0, "text": "hola mundo cruel"},
            {"start": 5.0, "end": 13.0, "text": "cruel adiós amigos"}]
    words = words_of(segs)
    assert " ".join(w["text"] for w in words) == "hola mundo cruel cruel adiós amigos"
    assert all(a["end"] <= b["start"] + 1e-9 for a, b in zip(words, words[1:]))
    assert words[-1]["end"] <= 13.0
    assert words[2]["end"] <= 5.0  # el solape no invade al segmento siguiente


def test_words_of_descarta_segmento_en_ventana_vacia():
    """Segmento íntegro dentro de lo ya cubierto → se descarta, no se comprime
    a 10ms (era la fuente del pico de CPS y del karaoke roto)."""
    segs = [{"start": 5.0, "end": 10.0, "text": "hola mundo"},
            {"start": 5.0, "end": 10.0, "text": "mundo hola otra vez"}]
    words = words_of(segs)
    assert " ".join(w["text"] for w in words) == "hola mundo"


def test_chunk_words_respeta_maximo():
    words = [{"start": float(i), "end": float(i + 1), "text": f"w{i}"} for i in range(20)]
    chunks = chunk_words(words)
    assert len(chunks) == 3 and all(len(c) <= 8 for c in chunks)


def test_split_lines_sin_colgadas():
    import re

    words = [{"start": float(i), "end": float(i + 1), "text": t}
             for i, t in enumerate("llegó el río de repente y con fuerza".split())]
    rendered = [" ".join(w["text"] for w in ln) for ln in split_lines(words)]
    assert len(rendered) == 2  # 8 palabras → 4+4, con "de" corrida abajo
    for ln in rendered[:-1]:  # ninguna línea (salvo la última) cierra en colgada
        assert not re.search(r"\b(el|de|desde|y|que|en|la|los|las|un|una|con|por|se|del|al|lo|a)$", ln)


def test_ass_ninguna_linea_empieza_en_coma():
    import re

    segs = [{"start": 0.0, "end": 6.0, "text": ",río desde allá, desde el río Iguazú hasta el fin"}]
    for line in to_ass(segs).splitlines():
        if line.startswith("Dialogue"):
            text = line.split(",,0,0,0,,", 1)[1]
            for ln in text.split("\\N"):
                t = re.sub(r"\{\\k\d+\}", "", ln).strip()
                assert t[:1] not in ",;.:"


def test_ass_alineado_con_format_de_eventos():
    """El Format de [Events] debe declarar exactamente los campos que escriben
    los Dialogue: un campo de más corre el texto y libass quema la coma inicial
    que ve el usuario (bug del ",un frente cálido")."""
    segs = [{"start": 0.0, "end": 2.0, "text": "hola mundo"}]
    ass = to_ass(segs)
    fmt = next(l for l in ass.splitlines() if l.startswith("Format: Layer"))
    n = len(fmt.split(":", 1)[1].split(","))
    for line in ass.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(":", 1)[1].split(",", n - 1)
        assert len(fields) == n
        assert not fields[-1].startswith(",")  # texto real, sin coma fantasma


def test_chunk_words_ancho_de_linea():
    """Cada bloque renderiza ≤2 líneas y cada línea ≤ ancho de frame (nada de
    3ª fila por auto-wrap de libass)."""
    words = [{"start": float(i), "end": float(i + 1), "text": t} for i, t in
             enumerate("un frente cálido muy fuerte también. que ocasionó".split())]
    chunks = chunk_words(words)
    assert all(len(c) <= 8 for c in chunks)
    for ch in chunks:
        lines = split_lines(ch)
        assert len(lines) <= 2
        for ln in lines:
            assert len(ln) == 1 or _line_units(ln) <= MAX_LINE_UNITS


def test_burn_hash_requema_si_cambia_ass(tmp_path):
    import subprocess

    from ytshorter.caption import burn_and_thumb

    cdir = tmp_path / "short_01"
    cdir.mkdir()
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=size=640x480:rate=10:duration=2",
         "-pix_fmt", "yuv420p", str(cdir / "cut.mp4")], check=True)
    (cdir / "subtitles.ass").write_text("v1")
    r1 = burn_and_thumb(cdir, total_s=2.0)
    assert r1.get("cached") is False
    assert (cdir / "burn.hash").exists()
    r2 = burn_and_thumb(cdir, total_s=2.0)
    assert r2.get("cached") is True  # mismo ass → cache
    (cdir / "subtitles.ass").write_text("v2")
    r3 = burn_and_thumb(cdir, total_s=2.0)
    assert r3.get("cached") is not True  # ass cambió → re-quema


def test_clip_segments_recorta_y_relativiza():
    t = [{"start": 0.0, "end": 5.0, "text": "a"}, {"start": 5.0, "end": 12.0, "text": "b"}]
    out = clip_segments(t, 3.0, 10.0)
    assert [(s["start"], s["end"]) for s in out] == [(0.0, 2.0), (2.0, 7.0)]


def test_vertical_vf_916():
    assert "1080:1920" in VERTICAL_VF and "crop" in VERTICAL_VF


def test_choose_crop_contain_si_contenido_distribuido(monkeypatch):
    """Saliencia repartida a lo ancho → contain: nada queda fuera de cuadro."""
    import numpy as np

    from ytshorter import reframe as R

    monkeypatch.setattr(R, "_probe_wh", lambda src: (1280, 720))
    monkeypatch.setattr(R, "_detect_faces", lambda frames: [])
    rng = np.random.default_rng(0)
    frames = [rng.integers(0, 255, (R.SAMPLE_H, R.SAMPLE_W, 3)).astype(float)
              for _ in range(6)]
    monkeypatch.setattr(R, "_sample_frames", lambda src, a, b: frames)
    vf, info = R.choose_crop("x.mp4", 0, 30)
    assert info["mode"] == "contain" and vf == R.CONTAIN_VF
    assert info["coverage"] < R.COVERAGE_MIN


def test_choose_crop_rostro_centrado_recorta(monkeypatch):
    import numpy as np

    from ytshorter import reframe as R

    monkeypatch.setattr(R, "_probe_wh", lambda src: (1280, 720))
    hits = [(0.5, 0.08)] * 6
    monkeypatch.setattr(R, "_detect_faces", lambda frames: hits)
    frames = [np.zeros((R.SAMPLE_H, R.SAMPLE_W, 3)) for _ in range(6)]
    monkeypatch.setattr(R, "_sample_frames", lambda src, a, b: frames)
    vf, info = R.choose_crop("x.mp4", 0, 30)
    assert info["mode"] == "smart" and "crop=" in vf


def _make_source(path: str, dur: int = 12):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=30:duration={dur}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
         "-pix_fmt", "yuv420p", "-shortest", path], check=True)


def _dims(path: str) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_words_of_confia_en_words_reales_con_solape():
    """json3: las ventanas de display se solapan pero las palabras ya vienen
    con tiempos reales — no se re-escalan ni se estiman."""
    segs = [
        {"start": 0.0, "end": 8.0, "text": "hola mundo",
         "words": [{"start": 0.0, "end": 0.4, "word": "hola"},
                   {"start": 0.5, "end": 0.9, "word": "mundo"}]},
        {"start": 3.0, "end": 11.0, "text": "cruel adiós",
         "words": [{"start": 3.1, "end": 3.5, "word": "cruel"},
                   {"start": 3.6, "end": 4.0, "word": "adiós"}]},
    ]
    words = words_of(segs)
    assert [w["text"] for w in words] == ["hola", "mundo", "cruel", "adiós"]
    assert [w["start"] for w in words] == [0.0, 0.5, 3.1, 3.6]


def test_words_of_descarta_words_ya_cubiertas():
    """Solape real (whisper rolling): palabras del segmento siguiente que ya
    fueron emitidas no se duplican."""
    segs = [
        {"start": 0.0, "end": 5.0, "text": "hola mundo",
         "words": [{"start": 0.0, "end": 0.4, "word": "hola"},
                   {"start": 0.5, "end": 0.9, "word": "mundo"}]},
        {"start": 2.0, "end": 7.0, "text": "mundo cruel",
         "words": [{"start": 0.5, "end": 0.9, "word": "mundo"},
                   {"start": 2.5, "end": 2.9, "word": "cruel"}]},
    ]
    words = words_of(segs)
    assert [w["text"] for w in words] == ["hola", "mundo", "cruel"]


def test_karaoke_usa_deltas_reales():
    """\\k por palabra refleja los inicios reales, no un reparto proporcional."""
    segs = [{"start": 0.0, "end": 3.0, "text": "una dos tres",
             "words": [{"start": 0.2, "end": 0.7, "word": "una"},
                       {"start": 1.2, "end": 1.5, "word": "dos"},
                       {"start": 2.0, "end": 2.4, "word": "tres"}]}]
    ass = to_ass(segs)
    dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue: 0,")][0]
    assert "{\\k100}una" in dialogue
    assert "{\\k80}dos" in dialogue


def test_ass_karaoke_multilinea_reloj_continuo():
    """El \\k es un reloj continuo entre líneas: si no, la última palabra de
    la línea 1 queda resaltada hasta el final del bloque y la línea 2 enciende
    sus palabras ~1s tarde (bug real de sincronía en bloques multi-línea)."""
    import re

    segs = [{"start": 0.0, "end": 3.5, "text": "una dos tres cuatro cinco",
             "words": [{"start": 0.0, "end": 0.4, "word": "una"},
                       {"start": 0.5, "end": 0.9, "word": "dos"},
                       {"start": 1.0, "end": 1.4, "word": "tres"},
                       {"start": 1.5, "end": 1.9, "word": "cuatro"},
                       {"start": 3.0, "end": 3.3, "word": "cinco"}]}]
    ass = to_ass(segs)
    line = [l for l in ass.splitlines() if l.startswith("Dialogue: 0,")][0]
    assert "{\\k50}una {\\k50}dos {\\k50}tres {\\k150}cuatro\\N{\\k50}cinco" in line
    assert sum(int(k) for k in re.findall(r"\\k(\d+)", line)) == 350


def test_e2e_cut_caption(tmp_path):
    wd = tmp_path / "w"
    wd.mkdir()
    _make_source(str(wd / "source.mp4"))
    (wd / "transcript.json").write_text(json.dumps({"video_id": "t", "segments": [
        {"start": 0.0, "end": 6.0, "text": "primera frase del test"},
        {"start": 6.0, "end": 12.0, "text": "segunda frase del test"}]}))
    (wd / "clips.json").write_text(json.dumps({"clips": [
        {"id": "short_01", "start": 0.0, "end": 8.0, "score": 80}]}))

    r1 = cut_all(str(wd))
    assert r1["ok"] and (wd / "short_01" / "cut.mp4").exists()
    assert (wd / "short_01" / "ffmpeg_cmd.sh").exists()
    assert _dims(str(wd / "short_01" / "cut.mp4")) == "1080,1920"

    r2 = caption_all(str(wd))
    assert r2["ok"]
    assert _dims(str(wd / "short_01" / "video.mp4")) == "1080,1920"
    assert "primera frase" in (wd / "short_01" / "subtitles.srt").read_text()
    assert (wd / "short_01" / "thumbnail.jpg").exists()


def test_prune_short_dirs_borra_fuera_de_clips(tmp_path):
    """Los short_XX del workdir que ya no están en clips.json se podan ANTES
    de caption/judge (el juez auditaba restos de runs anteriores)."""
    from ytshorter.clip import prune_short_dirs

    for n in ("short_01", "short_09"):
        (tmp_path / n).mkdir()
        (tmp_path / n / "cut.mp4").write_bytes(b"x")
    (tmp_path / "clips.json").write_text(
        json.dumps({"clips": [{"id": "short_01"}]}), encoding="utf-8")
    removed = prune_short_dirs(str(tmp_path))
    assert removed == ["short_09"]
    assert (tmp_path / "short_01").exists()
    assert not (tmp_path / "short_09").exists()


def test_prune_short_dirs_sin_clips_json_no_borra(tmp_path):
    from ytshorter.clip import prune_short_dirs

    (tmp_path / "short_01").mkdir()
    assert prune_short_dirs(str(tmp_path)) == []
    assert (tmp_path / "short_01").exists()


def test_contain_vf_v2_barato_y_sin_stretch():
    """contain v2: blur sobre miniatura (barato) y fondo cover (sin estirar);
    nada de boxblur a 1080x1920 (el encode tardaba 5-8 min/clip)."""
    from ytshorter.reframe import CONTAIN_VF

    assert "boxblur=30" not in CONTAIN_VF
    assert "gblur" in CONTAIN_VF
    assert "force_original_aspect_ratio=increase" in CONTAIN_VF  # fondo cover
    assert CONTAIN_VF.index("270:480") < CONTAIN_VF.index("gblur")
    assert "eq=brightness" in CONTAIN_VF  # fondo oscurecido (menos ruido)


def test_contain_vf_v2_ffmpeg_valido(tmp_path):
    """El filtro v2 compila en ffmpeg real (1s de fuente sintética)."""
    import subprocess

    from ytshorter.reframe import CONTAIN_VF

    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc=size=1280x720:rate=24:duration=1", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(src)], check=True)
    out = tmp_path / "out.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", CONTAIN_VF,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", str(out)], check=True)
    assert out.exists() and out.stat().st_size > 0


def test_cut_all_paralelo(monkeypatch, tmp_path):
    """Con YT_SHORTER_JOBS>1 los cortes corren en PARALELO (solapan en el
    tiempo): resultado en el orden de clips.json y callbacks desde el hilo
    principal. Con ejecución secuencial no hay solape → el test falla."""
    import threading
    import time as _t

    from ytshorter import clip as C

    monkeypatch.setenv("YT_SHORTER_JOBS", "3")
    import ytshorter.reframe as R
    monkeypatch.setattr(R, "choose_crop",
                        lambda *a, **k: (C.VERTICAL_VF, {"mode": "test"}))

    spans = []
    lock = threading.Lock()

    def fake_run(cmd, dur, on_tick=None):
        t0 = _t.time()
        _t.sleep(0.3)
        with lock:
            spans.append((t0, _t.time()))

    monkeypatch.setattr(C, "run_with_progress", fake_run)

    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "source.mp4").write_bytes(b"x")
    clips = [{"id": f"short_{i:02d}", "start": 0.0, "end": 3.0}
             for i in range(1, 4)]
    (wd / "clips.json").write_text(json.dumps({"clips": clips}))
    seen = []
    r = C.cut_all(str(wd), on_item=lambda d, t, cid, cached: seen.append(cid))
    assert r["ok"] and [c["id"] for c in r["cuts"]] == [c["id"] for c in clips]
    assert sorted(seen) == ["short_01", "short_02", "short_03"]
    overlaps = sum(1 for i, (a0, a1) in enumerate(spans)
                   for b0, b1 in spans[i + 1:] if a0 < b1 and b0 < a1)
    assert overlaps >= 1, f"sin paralelismo: spans={spans}"


def test_caption_all_paralelo(monkeypatch, tmp_path):
    """El quemado también solapa en el tiempo con YT_SHORTER_JOBS>1 (los
    ffmpeg de burn son independientes por short), manteniendo el orden."""
    import threading
    import time as _t

    from ytshorter import caption as C

    monkeypatch.setenv("YT_SHORTER_JOBS", "3")
    spans = []
    lock = threading.Lock()

    def fake_burn(cdir, force=False, total_s=0.0, on_tick=None):
        t0 = _t.time()
        _t.sleep(0.25)
        with lock:
            spans.append((t0, _t.time()))
        return {"id": cdir.name, "cached": False}

    monkeypatch.setattr(C, "burn_and_thumb", fake_burn)

    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "transcript.json").write_text(json.dumps({"segments": [
        {"start": 0.0, "end": 3.0, "text": "hola mundo"}]}))
    clips = [{"id": f"short_{i:02d}", "start": 0.0, "end": 3.0}
             for i in range(1, 4)]
    for c in clips:
        (wd / c["id"]).mkdir()
        (wd / c["id"] / "cut.mp4").write_bytes(b"x")
    (wd / "clips.json").write_text(json.dumps({"clips": clips}))
    seen = []
    r = C.caption_all(str(wd), on_item=lambda d, t, cid, cached: seen.append(cid))
    assert r["ok"] and [v["id"] for v in r["videos"]] == [c["id"] for c in clips]
    assert sorted(seen) == ["short_01", "short_02", "short_03"]
    overlaps = sum(1 for i, (a0, a1) in enumerate(spans)
                   for b0, b1 in spans[i + 1:] if a0 < b1 and b0 < a1)
    assert overlaps >= 1, f"sin paralelismo: spans={spans}"
