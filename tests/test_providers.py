"""Tests P5.1: proveedores OpenAI-compatible opt-in; Gemini sigue por defecto."""

import io
import json
import urllib.error

import pytest

from ytshorter import providers as P
from ytshorter.config import load_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "GROQ_MODEL", "GROQ_BASE_URL",
              "GROQ_VISION_MODEL", "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
              "OPENROUTER_BASE_URL", "OPENROUTER_VISION_MODEL",
              "YT_SHORTER_LOCAL_BASE_URL", "YT_SHORTER_LOCAL_MODEL",
              "YT_SHORTER_LOCAL_API_KEY", "YT_SHORTER_LLM_ORDER"):
        monkeypatch.delenv(k, raising=False)


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body


def test_sin_claves_no_hay_proveedores():
    assert P.provider_names() == []
    assert load_settings().llm_configured() is False


def test_default_sigue_siendo_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert P.provider_names() == ["gemini"]
    ps = P.providers_for(gemini_model="gemini-3.8-flash", gemini_api_key="k")
    assert [p.kind for p in ps] == ["gemini"]


def test_groq_entra_antes_que_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    assert P.provider_names() == ["groq", "gemini"]
    ps = P.providers_for(gemini_model="gm", gemini_api_key="gk")
    assert [p.name for p in ps] == ["groq", "gemini"]
    assert ps[0].base_url == P.GROQ_DEFAULT_URL
    assert ps[0].model == P.GROQ_DEFAULT_MODEL


def test_orden_explicito_con_gemini_de_respaldo(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("YT_SHORTER_LLM_ORDER", "groq")
    assert P.provider_names() == ["groq", "gemini"]
    monkeypatch.setenv("YT_SHORTER_LLM_ORDER", "gemini,groq")
    assert P.provider_names() == ["gemini", "groq"]


def test_local_solo_con_base_url(monkeypatch):
    monkeypatch.setenv("YT_SHORTER_LOCAL_BASE_URL", "http://127.0.0.1:8080/v1")
    assert P.provider_names() == ["local"]
    p = P.providers_for()[0]
    assert p.kind == "openai" and p.api_key == "local"
    assert p.model == "local-model"


def test_groq_vision_solo_con_modelo_y_tope_3(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    assert P.openai_vision_providers() == []
    assert P.vision_image_cap() == 0
    monkeypatch.setenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
    ps = P.openai_vision_providers()
    assert [p.model for p in ps] == ["qwen/qwen3.8-27b"]
    assert P.vision_image_cap() == 3


def test_openai_chat_payload_texto_y_fence(monkeypatch):
    seen = {}

    def fake(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        seen["auth"] = {k.lower(): v for k, v in req.header_items()}.get("authorization")
        return _Resp(b'{"choices":[{"message":{"content":"```json\\n{\\"ok\\": 1}\\n```"}}]}')

    monkeypatch.setattr("urllib.request.urlopen", fake)
    p = P.Provider("groq", "openai", P.GROQ_DEFAULT_URL, "g", "m")
    assert P.openai_chat(p, "sys", "user") == {"ok": 1}
    assert seen["url"] == P.GROQ_DEFAULT_URL + "/chat/completions"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["body"]["messages"][1]["content"] == "user"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["auth"] == "Bearer g"


def test_openai_chat_imagenes_como_data_url(monkeypatch):
    seen = {}

    def fake(req, timeout=None):
        seen["body"] = json.loads(req.data)
        return _Resp(b'{"choices":[{"message":{"content":"{\\"ok\\": true}"}}]}')

    monkeypatch.setattr("urllib.request.urlopen", fake)
    p = P.Provider("groq", "openai", "http://x", "k", "m")
    assert P.openai_chat(p, "s", "u", [b"\xff\xd8jpeg"]) == {"ok": True}
    content = seen["body"]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "u"}
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_openai_chat_reintenta_429(monkeypatch):
    calls = []

    def fake(req, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(
                req.full_url, 429, "rate limited", {}, io.BytesIO(b"slow down"))
        return _Resp(b'{"choices":[{"message":{"content":"{\\"ok\\": 2}"}}]}')

    monkeypatch.setattr("urllib.request.urlopen", fake)
    monkeypatch.setattr("time.sleep", lambda s: None)
    p = P.Provider("groq", "openai", "http://x", "k", "m")
    assert P.openai_chat(p, "s", "u") == {"ok": 2}
    assert len(calls) == 3


def test_call_text_prefiere_groq(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    import ytshorter.analyze as A

    monkeypatch.setattr(A, "call_gemini",
                        lambda *a, **k: pytest.fail("no debía llamar a Gemini"))
    monkeypatch.setattr(P, "openai_chat", lambda *a, **k: {"clips": [2]})
    data, used = P.call_text("s", "u", "gm", "gk")
    assert data == {"clips": [2]} and used.startswith("groq:")


def test_call_text_cae_a_gemini_si_groq_falla(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    import ytshorter.analyze as A

    def boom(*a, **k):
        raise P.ProviderError("HTTP 429", 429)

    monkeypatch.setattr(P, "openai_chat", boom)
    monkeypatch.setattr(A, "call_gemini", lambda system, user, model, key: {"clips": [1]})
    data, used = P.call_text("s", "u", "gm", "gk")
    assert data == {"clips": [1]} and used == "gm"


def test_judge_usa_vision_openai_y_capa_frames(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
    sent = {}

    def fake_chat(p, system, user, images=None, timeout=180.0):
        sent["n"] = len(images or [])
        return {"ship": True, "score": 80, "issues": [], "notes": ""}

    monkeypatch.setattr(P, "openai_chat", fake_chat)
    from ytshorter import judge as J

    monkeypatch.setattr(J, "judge_call",
                        lambda *a, **k: pytest.fail("no debía llamar a Gemini"))
    monkeypatch.setattr(J, "sample_frames", lambda *a, **k: [b"x"] * 10)
    d = tmp_path / "short_01"
    d.mkdir()
    (d / "video.mp4").write_bytes(b"x")
    res = J.judge_short(str(d), "gm", "gk")
    assert res["model"].startswith("groq:")
    assert sent["n"] == 3 and res["frames"] == 3


def test_config_llm_configured_con_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    s = load_settings()
    assert s.llm_configured() is True
    assert s.groq_model == "openai/gpt-oss-120b"
    assert s.local_model == "local-model"
