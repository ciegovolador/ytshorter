"""Tests de portabilidad Windows (se corren en Linux también)."""

import sys
from pathlib import Path


def test_ass_vf_escapa_path_windows():
    from ytshorter import burn

    vf = burn._ass_vf(Path("C:/Users/me/work/short_01/subtitles.ass"))
    assert vf == "ass='C\\:/Users/me/work/short_01/subtitles.ass'"
    assert "\\Users" not in vf


def test_pipeline_cmd_frozen_no_usa_dash_m(monkeypatch):
    from ytshorter import queue

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = queue._pipeline_cmd("URL", "dist", "work", "job-1")
    assert cmd[0] == sys.executable and cmd[1] == "pipeline" and "-m" not in cmd
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert queue._pipeline_cmd("URL", "dist", "work", "job-1")[1:3] == ["-m", "ytshorter"]


def test_pick_font_windows_cae_en_arial(monkeypatch):
    from ytshorter import subtitles

    class FakeOS:
        name = "nt"
        environ = {"WINDIR": "C:/Windows"}

        @staticmethod
        def getenv(key, default=""):
            return ""

    monkeypatch.setattr(subtitles, "os", FakeOS)
    assert subtitles.pick_font() == "Arial"


def test_prompts_dir_meipass(monkeypatch, tmp_path):
    from ytshorter import analyze

    root = tmp_path / "_MEIPASS"
    (root / "prompts" / "v3").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    assert analyze.prompts_dir() == root / "prompts"


def test_web_static_meipass(monkeypatch, tmp_path):
    from ytshorter import web

    root = tmp_path / "_MEIPASS"
    static = root / "web" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    assert web._static_dir() == static


def test_prepend_exe_dir_incluye_meipass(monkeypatch, tmp_path):
    import os

    from ytshorter import cli

    exe = tmp_path / "ytshorter.exe"
    exe.write_bytes(b"")
    meipass = tmp_path / "_MEI"
    meipass.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setenv("PATH", "")
    cli._prepend_exe_dir()
    parts = os.environ["PATH"].split(os.pathsep)
    assert str(meipass) in parts and str(tmp_path.resolve()) in parts


def test_env_file_simple(monkeypatch, tmp_path):
    import os

    from ytshorter import config

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_MODEL", "")
    p = tmp_path / ".env"
    p.write_text('GEMINI_API_KEY="abc"\n# comentario\nGROQ_MODEL=openai/gpt-oss-120b\n',
                 encoding="utf-8")
    config._load_env_file(p)
    assert os.environ["GEMINI_API_KEY"] == "abc"
    assert os.environ["GROQ_MODEL"] == "openai/gpt-oss-120b"


def test_env_file_no_pisa_entorno(monkeypatch, tmp_path):
    import os

    from ytshorter import config

    monkeypatch.setenv("GEMINI_API_KEY", "keep")
    p = tmp_path / ".env"
    p.write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")
    config._load_env_file(p)
    assert os.environ["GEMINI_API_KEY"] == "keep"
