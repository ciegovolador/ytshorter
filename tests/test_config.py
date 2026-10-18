"""Tests config: defaults y overrides de entorno (sin red)."""

from ytshorter.config import load_settings


def test_config_defaults(monkeypatch):
    for v in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_JUDGE_MODEL",
              "GEMINI_JUDGE_FALLBACK", "YT_SHORTER_PROMPTS",
              "YT_SHORTER_WORK", "YT_SHORTER_OUT"):
        monkeypatch.delenv(v, raising=False)
    s = load_settings()
    assert s.gemini_model == "gemini-3.8-flash"
    assert s.judge_model == "gemini-3.6-flash"  # modelo+prompt propios (pro no existe en free tier)
    assert s.judge_fallback_model == "gemini-2.5-flash"
    assert s.prompts_version == "v3"
    assert s.min_short_s == 10 and s.max_short_s == 170


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("GEMINI_JUDGE_MODEL", "gemini-3-pro")
    monkeypatch.setenv("GEMINI_JUDGE_FALLBACK", "gemini-3-flash")
    s = load_settings()
    assert s.judge_model == "gemini-3-pro"
    assert s.judge_fallback_model == "gemini-3-flash"


def test_config_llm_configured(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert load_settings().llm_configured() is False
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert load_settings().llm_configured() is True
