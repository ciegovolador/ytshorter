"""Tests F5: package arma dist/<id>/short_XX/ con los 8 artefactos (sin ffmpeg)."""

import json

from ytshorter.package import package_workdir


def _fake_workdir(base):
    wd = base / "work" / "vid9"
    (wd / "short_01").mkdir(parents=True)
    (wd / "clips.json").write_text(json.dumps({
        "video_id": "vid9", "prompts_version": "v1", "model": "test",
        "clips": [{"id": "short_01", "start": 0, "end": 30, "score": 85,
                   "title": "Título gancho", "description": "Desc #Shorts",
                   "tags": ["a", "b"], "reason": "x", "duration": 30.0}]}))
    for f in ("video.mp4", "subtitles.srt", "subtitles.ass", "thumbnail.jpg", "ffmpeg_cmd.sh"):
        (wd / "short_01" / f).write_text("dummy")
    return wd


def test_package_artefactos(tmp_path):
    wd = _fake_workdir(tmp_path)
    res = package_workdir(str(wd), out_root=str(tmp_path / "dist"))
    assert res["ok"] and res["n"] == 1
    d = tmp_path / "dist" / "vid9" / "short_01"
    for f in ("video.mp4", "title.txt", "description.txt", "tags.txt",
              "subtitles.srt", "subtitles.ass", "thumbnail.jpg",
              "metadata.json", "ffmpeg_cmd.sh"):
        assert (d / f).exists(), f"falta {f}"
    assert (d / "title.txt").read_text().strip() == "Título gancho"
    assert (tmp_path / "dist" / "vid9" / "manifest.json").exists()


def test_package_cache(tmp_path):
    wd = _fake_workdir(tmp_path)
    out = str(tmp_path / "dist")
    assert package_workdir(str(wd), out_root=out)["ok"]
    res2 = package_workdir(str(wd), out_root=out)
    assert res2["ok"] and res2["cached"]


def test_package_limpia_shorts_viejos(tmp_path):
    """Re-paquete con menos clips: los short_XX viejos del dist no sobreviven."""
    wd = _fake_workdir(tmp_path)
    out = str(tmp_path / "dist")
    stale = tmp_path / "dist" / "vid9" / "short_09"
    stale.mkdir(parents=True)
    (stale / "video.mp4").write_text("viejo")
    res = package_workdir(str(wd), out_root=out)
    assert res["ok"] and not stale.exists()
    assert (tmp_path / "dist" / "vid9" / "short_01").exists()


def test_manifest_funnel(tmp_path):
    """BR-031: el manifest incluye el embudo por etapa con los drops de cada
    una (visión de analyze, review, visión de review) y el respaldo local del
    piso de volumen. Invariante: propuestos = final + drops."""
    wd = tmp_path / "work" / "vid9"
    clips = [{"id": f"short_{i:02d}", "start": float(i * 40),
              "end": float(i * 40 + 30), "score": 80, "title": "t",
              "description": "d", "tags": [], "duration": 30.0}
             for i in range(1, 7)]
    for c in clips:
        (wd / c["id"]).mkdir(parents=True)
    (wd / "clips.json").write_text(json.dumps({
        "video_id": "vid9", "prompts_version": "v4", "model": "test",
        "volume": {"floor": 8, "fallback_local": 2},
        "vision": {"status": "applied", "kept": 10, "dropped": 2},
        "review": {"status": "applied", "kept": 3, "dropped": 3, "adjusted": 2,
                   "vision": {"status": "applied", "kept": 3, "dropped": 1}},
        "clips": clips}))
    for c in clips:
        for f in ("video.mp4", "subtitles.srt", "subtitles.ass",
                  "thumbnail.jpg", "ffmpeg_cmd.sh"):
            (wd / c["id"] / f).write_text("x")
    res = package_workdir(str(wd), out_root=str(tmp_path / "dist"))
    m = json.loads((tmp_path / "dist" / "vid9" / "manifest.json").read_text())
    f = m["funnel"]
    assert res["ok"]
    assert f["analyze_vision_dropped"] == 2
    assert f["review_dropped"] == 3 and f["review_adjusted"] == 2
    assert f["review_vision_dropped"] == 1
    assert f["final"] == 6
    assert f["proposed"] == 12 == f["final"] + 2 + 3 + 1
    assert f["fallback_local"] == 2 and f["floor"] == 8
