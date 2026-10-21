"""providers.py (P5.1) — proveedores LLM intercambiables, Gemini por defecto.

Groq, OpenRouter y llama.cpp local comparten la API OpenAI (`/chat/completions`).
Son opt-in: sin claves nuevas, todo sigue yendo a Gemini como siempre. La cadena
cae al siguiente proveedor ante cuota/caída y Gemini cierra como respaldo. La
visión de analyze/review (lotes de frames) sigue en Gemini; el juez puede usar
un modelo visual propio (`GROQ_VISION_MODEL`, `OPENROUTER_VISION_MODEL` o el
modelo local servido).
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

GROQ_DEFAULT_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
OPENROUTER_DEFAULT_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENAI_ATTEMPTS = 3
OPENAI_BACKOFF_S = (5, 15)
_NAMES = ("groq", "openrouter", "local")


class ProviderError(Exception):
    """Error de un proveedor OpenAI-compatible (status HTTP si lo hubo)."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Provider:
    name: str
    kind: str  # "gemini" | "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    max_images: int = 0  # 0 = sin tope propio


def _is_transient(e: Exception) -> bool:
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    try:
        if int(code) in (429, 500, 502, 503, 504):
            return True
    except (TypeError, ValueError):
        pass
    msg = str(e).upper()
    return any(t in msg for t in ("RATE LIMIT", "RATE_LIMIT", "TIMEOUT", "TIMED OUT",
                                  "OVERLOADED", "HIGH DEMAND", "UNAVAILABLE"))


def _configured(name: str, s) -> bool:
    return {
        "groq": bool(s.groq_api_key),
        "openrouter": bool(s.openrouter_api_key),
        "local": bool(s.local_base_url),
    }[name]


def _order(s) -> list[str]:
    """Orden de la cadena. Sin override: proveedores configurados y Gemini al final."""
    raw = (s.llm_order or "").replace(" ", "")
    if raw:
        names = [n for n in raw.split(",") if n in _NAMES or n == "gemini"]
    else:
        names = [n for n in _NAMES if _configured(n, s)]
        names.append("gemini")
    if "gemini" not in names:  # Gemini sigue siendo la opción de respaldo
        names.append("gemini")
    return names


def _openai_provider(name: str, s, vision: bool) -> Provider | None:
    if name == "groq":
        if not s.groq_api_key:
            return None
        model = s.groq_vision_model if vision else s.groq_model
        if not model:
            return None
        return Provider("groq", "openai", s.groq_base_url, s.groq_api_key, model,
                        max_images=3)  # Groq acepta hasta 3 imágenes por request
    if name == "openrouter":
        if not s.openrouter_api_key:
            return None
        model = s.openrouter_vision_model if vision else s.openrouter_model
        if not model:
            return None
        return Provider("openrouter", "openai", s.openrouter_base_url,
                        s.openrouter_api_key, model)
    if name == "local":
        if not s.local_base_url:
            return None
        return Provider("local", "openai", s.local_base_url,
                        s.local_api_key or "local", s.local_model)
    return None


def providers_for(vision: bool = False, gemini_model: str = "",
                  gemini_api_key: str = "") -> list[Provider]:
    from .config import load_settings

    s = load_settings()
    out: list[Provider] = []
    for name in _order(s):
        if name == "gemini":
            if gemini_model and gemini_api_key:
                out.append(Provider("gemini", "gemini", model=gemini_model,
                                    api_key=gemini_api_key))
            continue
        p = _openai_provider(name, s, vision)
        if p is not None:
            out.append(p)
    return out


def provider_names() -> list[str]:
    """Nombres activos (para doctor); Gemini solo si hay clave."""
    from .config import load_settings

    s = load_settings()
    names = []
    for name in _order(s):
        if name == "gemini":
            if s.gemini_api_key:
                names.append("gemini")
        elif _configured(name, s):
            names.append(name)
    return names


def openai_vision_providers() -> list[Provider]:
    return [p for p in providers_for(vision=True) if p.kind == "openai"]


def vision_image_cap() -> int:
    """Tope de frames por request entre los proveedores visuales configurados."""
    caps = [p.max_images for p in openai_vision_providers() if p.max_images > 0]
    return min(caps) if caps else 0


def judge_configured(gemini_api_key: str) -> bool:
    """El juez necesita visión: Gemini o un modelo visual OpenAI-compatible."""
    return bool(gemini_api_key or openai_vision_providers())


def _post_json(url: str, payload: dict, api_key: str, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "ytshorter"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise ProviderError(f"HTTP {e.code}: {detail}", e.code) from e
    except urllib.error.URLError as e:
        raise ProviderError(f"red: {e.reason}") from e


def _json_from_response(data: dict) -> dict:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"respuesta sin choices: {str(data)[:200]}") from e
    if isinstance(content, list):
        content = "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    text = (content or "").strip()
    if text.startswith("```") and "\n" in text:
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ProviderError(f"JSON inválido: {e}") from e


def _payload(provider: Provider, system: str, user: str,
             images: list[bytes]) -> dict:
    content: object = user
    if images:
        content = [{"type": "text", "text": user}]
        for img in images:
            b64 = base64.b64encode(img).decode("ascii")
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return {
        "model": provider.model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": content}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }


def openai_chat(provider: Provider, system: str, user: str,
                images: list[bytes] | None = None,
                timeout: float = 180.0) -> dict:
    """POST /chat/completions con reintentos transitorios (429/5xx/timeout)."""
    imgs = list(images or [])
    if provider.max_images:
        imgs = imgs[:provider.max_images]
    payload = _payload(provider, system, user, imgs)
    url = f"{provider.base_url.rstrip('/')}/chat/completions"
    for attempt in range(1, OPENAI_ATTEMPTS + 1):
        try:
            return _json_from_response(_post_json(url, payload, provider.api_key, timeout))
        except Exception as e:  # noqa: BLE001 — clasificamos transitorio vs definitivo
            if attempt == OPENAI_ATTEMPTS or not _is_transient(e):
                raise
            wait = OPENAI_BACKOFF_S[min(attempt - 1, len(OPENAI_BACKOFF_S) - 1)]
            print(f"[llm] {provider.name} intento {attempt}/{OPENAI_ATTEMPTS} falló "
                  f"({str(e).splitlines()[0][:120]}); reintento en {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def call_text(system: str, user: str, gemini_model: str,
              gemini_api_key: str) -> "tuple[dict, str]":
    """Primer proveedor que responde gana; Gemini cierra la cadena.

    Devuelve `(json, modelo_usado)` para dejar trazabilidad en clips.json."""
    last: Exception | None = None
    for p in providers_for(gemini_model=gemini_model, gemini_api_key=gemini_api_key):
        try:
            if p.kind == "gemini":
                from .analyze import call_gemini

                return call_gemini(system, user, p.model, p.api_key), p.model
            return openai_chat(p, system, user), f"{p.name}:{p.model}"
        except Exception as e:  # noqa: BLE001 — cuota/caída → siguiente proveedor
            last = e
            print(f"[llm] {p.name} falló ({str(e).splitlines()[0][:140]}); "
                  f"pruebo el siguiente", file=sys.stderr)
    raise last if last is not None else RuntimeError("sin proveedores LLM configurados")
