"""Config central (único lugar que lee env/flags). KISS + DRY."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Carga KEY=VALUE simple (.env junto al .exe). No pisa el entorno."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = val


def _load_frozen_env() -> None:
    """Exe de Windows: .env junto al ejecutable (o CWD), sin variables de shell."""
    if not getattr(sys, "frozen", False):
        return
    exe_dir = Path(sys.executable).resolve().parent
    for p in (exe_dir / ".env", Path.cwd() / ".env"):
        if p.exists():
            _load_env_file(p)


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
    # Proveedores alternativos (P5.1, API OpenAI-compatible). Opt-in: sin estas
    # claves todo sigue yendo a Gemini, que además cierra la cadena como respaldo.
    llm_order: str = field(default_factory=lambda: os.getenv("YT_SHORTER_LLM_ORDER", ""))
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_model: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
    groq_base_url: str = field(
        default_factory=lambda: os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
    groq_vision_model: str = field(default_factory=lambda: os.getenv("GROQ_VISION_MODEL", ""))
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    openrouter_model: str = field(default_factory=lambda: os.getenv(
        "OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"))
    openrouter_base_url: str = field(default_factory=lambda: os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    openrouter_vision_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_VISION_MODEL", ""))
    local_base_url: str = field(
        default_factory=lambda: os.getenv("YT_SHORTER_LOCAL_BASE_URL", ""))
    local_model: str = field(
        default_factory=lambda: os.getenv("YT_SHORTER_LOCAL_MODEL", "local-model"))
    local_api_key: str = field(
        default_factory=lambda: os.getenv("YT_SHORTER_LOCAL_API_KEY", ""))
    # La duración la dicta la idea, no al revés: piso editorial (una idea
    # completa no cabe en menos) y techo técnico (YouTube Shorts ≤180s).
    min_short_s: int = 10
    max_short_s: int = 170

    def llm_configured(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key
                    or self.openrouter_api_key or self.local_base_url)


def load_settings() -> Settings:
    return Settings()


_load_frozen_env()
