"""Tests F2: download.parse + transcribe idempotente (sin red)."""

import json

import ytshorter.download as DL
from ytshorter import transcribe as TR
from ytshorter.download import extract_video_id
from ytshorter.transcribe import transcribe_workdir


def test_extract_video_id():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_transcribe_cached(tmp_path):
    wd = tmp_path / "vid12345678"
    wd.mkdir()
    (wd / "transcript.json").write_text(
        json.dumps({"video_id": "x", "source": "test", "segments": [{"start": 0, "end": 1, "text": "hola"}]})
    )
    res = transcribe_workdir(str(wd))
    assert res["ok"] and res["cached"] and res["segments"] == 1


def test_transcribe_sin_whisper_error_claro(tmp_path, monkeypatch):
    import sys

    wd = tmp_path / "noid"  # ≠11 chars: no intenta captions (sin red)
    wd.mkdir()
    (wd / "source.mp4").write_bytes(b"fake")
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    res = transcribe_workdir(str(wd), force=True)
    assert res["ok"] is False and "faster-whisper" in res["error"]


def test_parse_json3_chunks_y_relleno():
    data = {"events": [
        {"tStartMs": 0, "dDurationMs": 100000},  # cabecera sin segs
        {"tStartMs": 66560, "dDurationMs": 3525, "segs": [{"utf8": "Muy buenas"}, {"utf8": " tardes"}]},
        {"tStartMs": 68310, "dDurationMs": 1775, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 68320, "dDurationMs": 2040, "segs": [{"utf8": "¿cómo están?"}]},
        {"tStartMs": 68320, "dDurationMs": 2040, "segs": [{"utf8": "¿cómo están?"}]},  # dup
    ]}
    segs = TR._parse_json3(json.dumps(data))
    assert [s["text"] for s in segs] == ["Muy buenas tardes", "¿cómo están?"]
    assert segs[0]["start"] == 66.56 and round(segs[0]["end"], 3) == 70.085


def test_parse_srt_tags_y_tiempos():
    srt = ("1\n00:00:01,500 --> 00:00:04,000\n<font color=\"#fff\">Hola</font>\n\n"
           "2\n00:00:04,000 --> 00:00:07,250\nmundo entero\n")
    segs = TR._parse_srt(srt)
    assert [s["text"] for s in segs] == ["Hola", "mundo entero"]
    assert segs[0]["start"] == 1.5 and segs[1]["end"] == 7.25


def test_captions_reintenta_solo_transitorio(monkeypatch):
    calls = []

    class RequestBlocked(Exception):
        pass

    def fake_once(api, video_id):
        calls.append(1)
        if len(calls) < 3:
            raise RequestBlocked("429 Too Many Requests")
        return [{"start": 0.0, "end": 2.0, "text": "hola"}]

    monkeypatch.setattr(TR, "_fetch_captions_once", fake_once)
    monkeypatch.setattr("time.sleep", lambda s: None)
    segs, why = TR._try_youtube_captions("dQw4w9WgXcQ")
    assert segs and len(calls) == 3 and why == ""

    calls.clear()

    class NoTranscriptFound(Exception):
        pass

    monkeypatch.setattr(TR, "_fetch_captions_once",
                        lambda api, vid: (calls.append(1), (_ for _ in ()).throw(
                            NoTranscriptFound("sin transcript")))[1])
    segs, why = TR._try_youtube_captions("dQw4w9WgXcQ")
    assert segs is None and len(calls) == 1  # no transitorio: sin reintentos
    assert "NoTranscriptFound" in why


def test_transcribe_fallback_ytdlp_subs(monkeypatch, tmp_path):
    wd = tmp_path / "dQw4w9WgXcQ"
    wd.mkdir()
    monkeypatch.setattr(TR, "_try_youtube_captions",
                        lambda vid: (None, "RequestBlocked: 429"))
    monkeypatch.setattr(TR, "_ytdlp_subs", lambda vid, w: (
        [{"start": 0.0, "end": 2.0, "text": "hola mundo"}], ""))
    res = transcribe_workdir(str(wd), force=True)
    data = json.loads((wd / "transcript.json").read_text())
    assert res["ok"] and res["source"] == "yt-dlp-subs" and res["segments"] == 1
    assert data["segments"][0]["text"] == "hola mundo"


def test_transcribe_error_incluye_motivos(monkeypatch, tmp_path):
    import sys

    wd = tmp_path / "dQw4w9WgXcQ"
    wd.mkdir()
    (wd / "source.mp4").write_bytes(b"fake")
    monkeypatch.setattr(TR, "_try_youtube_captions",
                        lambda vid: (None, "RequestBlocked: 429 Too Many Requests"))
    monkeypatch.setattr(TR, "_ytdlp_subs", lambda vid, w: (None, "sin subtítulos es/en"))
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    res = transcribe_workdir(str(wd), force=True)
    assert res["ok"] is False
    assert "RequestBlocked" in res["error"]  # el motivo real, no "sin subtítulos"
    assert "yt-dlp" in res["error"] and "faster-whisper" in res["error"]


def test_download_id_invalido_no_intenta_red(tmp_path):
    # v= de 10 chars (link truncado): se rechaza antes de cualquier red
    res = DL.download_url("https://www.youtube.com/watch?v=i--5e4JfHM",
                          out_root=str(tmp_path))
    assert res["ok"] is False and "11 caracteres" in res["error"]
    assert list(tmp_path.iterdir()) == []


def test_download_reintenta_y_retoma(monkeypatch, tmp_path):
    import yt_dlp

    calls = []

    class FakeYDL:
        def __init__(self, opts):
            assert opts["retries"] >= 10 and opts["socket_timeout"] >= 30
            assert opts.get("noprogress") is True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            calls.append(1)
            if len(calls) == 1:
                raise Exception("Read timed out")
            d = tmp_path / "dQw4w9WgXcQ"
            d.mkdir(exist_ok=True)
            (d / "source.mp4").write_bytes(b"vid")
            (d / "info.json").write_text('{"title": "t", "duration": 10}')

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr("time.sleep", lambda s: None)
    res = DL.download_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                          out_root=str(tmp_path))
    assert res["ok"] and len(calls) == 2 and res["cached"] is False


def test_download_info_corrupto_redescarga(monkeypatch, tmp_path):
    import yt_dlp

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            (tmp_path / "dQw4w9WgXcQ" / "info.json").write_text('{"title": "t"}')

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    d = tmp_path / "dQw4w9WgXcQ"
    d.mkdir()
    (d / "source.mp4").write_bytes(b"vid")
    (d / "info.json").write_text("{{{corrupto")
    res = DL.download_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                          out_root=str(tmp_path))
    assert res["ok"] and res["cached"] is False


def test_download_prefiere_video_sobre_infojson(monkeypatch, tmp_path):
    """yt-dlp real escribe source.info.json (el glob source.* lo ordena ANTES
    que source.webm): el rename a source.mp4 debe elegir el video, no el JSON."""
    import yt_dlp

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            d = tmp_path / "dQw4w9WgXcQ"
            d.mkdir(exist_ok=True)
            (d / "source.info.json").write_text(
                '{"id": "dQw4w9WgXcQ", "title": "t", "duration": 10}')
            (d / "source.webm").write_bytes(b"webm-bytes")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    res = DL.download_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                          out_root=str(tmp_path))
    d = tmp_path / "dQw4w9WgXcQ"
    assert res["ok"] and (d / "source.mp4").read_bytes() == b"webm-bytes"
    assert (d / "source.info.json").exists()  # el sidecar no se renombra
    assert res["title"] == "t"


def test_download_cache_usa_source_info_json(monkeypatch, tmp_path):
    """El cache idempotente reconoce el nombre real del sidecar (source.info.json)."""
    d = tmp_path / "dQw4w9WgXcQ"
    d.mkdir()
    (d / "source.mp4").write_bytes(b"v")
    (d / "source.info.json").write_text('{"title": "t2", "duration": 20}')
    res = DL.download_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                          out_root=str(tmp_path))
    assert res["ok"] and res["cached"] is True and res["title"] == "t2"


def test_parse_json3_conserva_offsets_por_palabra():
    """json3 de auto-captions trae `segs[].tOffsetMs` (inicio real de cada
    palabra): es la fuente de sincronía del karaoke y no se puede perder."""
    data = {"events": [
        {"tStartMs": 66560, "dDurationMs": 3525, "segs": [
            {"utf8": "Muy"},
            {"utf8": " buenas", "tOffsetMs": 400},
            {"utf8": " tardes,", "tOffsetMs": 800}]},
        {"tStartMs": 68320, "dDurationMs": 2040,
         "segs": [{"utf8": "todos,", "tOffsetMs": 0}]},
    ]}
    segs = TR._parse_json3(json.dumps(data))
    assert [s["text"] for s in segs] == ["Muy buenas tardes,", "todos,"]
    ws = segs[0]["words"]
    assert [w["word"] for w in ws] == ["Muy", "buenas", "tardes,"]
    assert [round(w["start"], 3) for w in ws] == [66.56, 66.96, 67.36]
    assert round(ws[0]["end"], 3) == 66.96  # encadenadas dentro del evento
    assert round(ws[2]["end"], 3) == 68.32  # cierra donde arranca la próxima palabra
    ws2 = segs[1]["words"]
    assert round(ws2[0]["start"], 3) == 68.32
    assert round(ws2[0]["end"], 3) == 70.36  # última palabra del corpus: t0+dur


def test_parse_json3_sin_offsets_no_inventa_palabras():
    data = {"events": [
        {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Hola mundo"}]},
        {"tStartMs": 3000, "dDurationMs": 2000, "segs": [{"utf8": "chau"}]},
    ]}
    segs = TR._parse_json3(json.dumps(data))
    assert [s["text"] for s in segs] == ["Hola mundo", "chau"]
    assert not segs[0].get("words")
    assert not segs[1].get("words")


def test_parse_json3_filtra_etiquetas_entre_corchetes():
    """Eventos 100% etiqueta ([canto]) se descartan; etiquetas inline no
    entran al karaoke pero se conservan en el texto del transcript."""
    data = {"events": [
        {"tStartMs": 10000, "dDurationMs": 2000, "segs": [{"utf8": "[canto]"}]},
        {"tStartMs": 12000, "dDurationMs": 4000, "segs": [
            {"utf8": "Ah,"},
            {"utf8": " [suspiro]", "tOffsetMs": 500},
            {"utf8": " acá", "tOffsetMs": 900}]},
    ]}
    segs = TR._parse_json3(json.dumps(data))
    assert [s["text"] for s in segs] == ["Ah, [suspiro] acá"]
    assert [w["word"] for w in segs[0]["words"]] == ["Ah,", "acá"]
    assert [round(w["start"], 3) for w in segs[0]["words"]] == [12.0, 12.9]


def test_dedupe_rolling_fusiona_words():
    """Al colapsar ventanas rodantes crecientes, las words del evento nuevo
    (superset) reemplazan a las del viejo — no se pierden timings."""
    def w(a, b, t):
        return {"start": a, "end": b, "word": t}

    segs = [
        {"start": 0.0, "end": 5.0, "text": "hola que",
         "words": [w(0.0, 0.3, "hola"), w(0.4, 0.7, "que")]},
        {"start": 2.0, "end": 7.0, "text": "hola que tal",
         "words": [w(0.0, 0.3, "hola"), w(0.4, 0.7, "que"), w(1.0, 1.3, "tal")]},
    ]
    out = TR._dedupe_rolling(segs)
    assert len(out) == 1 and out[0]["text"] == "hola que tal"
    assert out[0]["end"] == 7.0
    assert [x["word"] for x in out[0]["words"]] == ["hola", "que", "tal"]


def test_transcribe_prefiere_ytdlp_para_words(monkeypatch, tmp_path):
    """yt-dlp/json3 es la única vía con word-timings: va antes que la API
    (que solo da texto) para que el karaoke tenga tiempos reales."""
    wd = tmp_path / "dQw4w9WgXcQ"
    wd.mkdir()
    api_calls = []
    monkeypatch.setattr(TR, "_try_youtube_captions", lambda vid: (
        api_calls.append(1),
        ([{"start": 0.0, "end": 2.0, "text": "hola"}], ""))[1])
    monkeypatch.setattr(TR, "_ytdlp_subs", lambda vid, w: (
        [{"start": 0.0, "end": 2.0, "text": "hola",
          "words": [{"start": 0.1, "end": 0.5, "word": "hola"}]}], ""))
    res = transcribe_workdir(str(wd), force=True)
    assert res["source"] == "yt-dlp-subs" and res["segments"] == 1
    assert not api_calls


def test_transcribe_cache_sin_words_se_enriquece(monkeypatch, tmp_path):
    """Transcript cacheado de la API (sin words): reintenta json3 una vez y
    reescribe con timings reales — los workdirs viejos se arreglan solos."""
    wd = tmp_path / "dQw4w9WgXcQ"
    wd.mkdir()
    (wd / "transcript.json").write_text(json.dumps(
        {"video_id": "dQw4w9WgXcQ", "source": "youtube-captions",
         "segments": [{"start": 0.0, "end": 2.0, "text": "hola mundo"}]}))
    monkeypatch.setattr(TR, "_ytdlp_subs", lambda vid, w: (
        [{"start": 0.0, "end": 2.0, "text": "hola mundo",
          "words": [{"start": 0.1, "end": 0.6, "word": "hola"},
                    {"start": 0.7, "end": 1.2, "word": "mundo"}]}], ""))
    res = transcribe_workdir(str(wd))
    data = json.loads((wd / "transcript.json").read_text())
    assert data["segments"][0]["words"]
    assert res["ok"] and res["segments"] == 1


def test_transcribe_cache_sin_words_falla_sin_romper(monkeypatch, tmp_path):
    wd = tmp_path / "dQw4w9WgXcQ"
    wd.mkdir()
    (wd / "transcript.json").write_text(json.dumps(
        {"video_id": "dQw4w9WgXcQ", "source": "youtube-captions",
         "segments": [{"start": 0.0, "end": 2.0, "text": "hola mundo"}]}))
    monkeypatch.setattr(TR, "_ytdlp_subs", lambda vid, w: (None, "sin red"))
    res = transcribe_workdir(str(wd))
    data = json.loads((wd / "transcript.json").read_text())
    assert res["ok"] and res["cached"]
    assert not data["segments"][0].get("words")
