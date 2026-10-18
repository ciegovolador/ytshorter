"""Config central (único lugar que lee env/flags). KISS + DRY."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    # El juez no comparte prompt ni MODELO con el editor (rúbrica propia +
    # umbral en código). Free tier no da pro (limit 0) y da 20 req/día por
    # modelo: juez 3.6-flash (bucket propio, generación distinta) con
    # respaldo 2.5-flash; editor/vision en 3.8-flash.
    judge_model: str = field(default_factory=lambda: os.getenv("GEMINI_JUDGE_MODEL", "gemini-3.6-flash"))
    judge_fallback_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_JUDGE_FALLBACK", "gemini-2.5-flash"))
    whisper_model: str = field(default_factory=lambda: os.getenv("YT_SHORTER_WHISPER_MODEL", "base"))
    work_dir: str = field(default_factory=lambda: os.getenv("YT_SHORTER_WORK", "work"))
    out_dir: str = field(default_factory=lambda: os.getenv("YT_SHORTER_OUT", "dist"))
    prompts_version: str = field(default_factory=lambda: os.getenv("YT_SHORTER_PROMPTS", "v3"))
    # La duración la dicta la idea, no al revés: piso editorial (una idea
    # completa no cabe en menos) y techo técnico (YouTube Shorts ≤180s).
    min_short_s: int = 10
    max_short_s: int = 170

    def llm_configured(self) -> bool:
        return bool(self.gemini_api_key)


def load_settings() -> Settings:
    return Settings()
