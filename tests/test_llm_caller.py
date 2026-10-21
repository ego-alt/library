"""Unit tests for the LLM wrapper. The Anthropic SDK is mocked end-to-end so
these tests never make a real network call."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

from library.llm_caller import LLMCaller, LLMError


def _fake_message(text: str):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def test_call_api_returns_text_from_response(monkeypatch):
    caller = LLMCaller()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_message("hi there")
    caller._client = fake_client  # bypass lazy init

    result = caller._call_api(system="sys", user_content="user")
    assert result == "hi there"
    assert fake_client.messages.create.called


def test_missing_api_key_raises_llm_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    caller = LLMCaller()
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        _ = caller.client


def test_anthropic_sdk_error_is_wrapped_as_llm_error():
    caller = LLMCaller()
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = anthropic.AnthropicError("boom")
    caller._client = fake_client

    with pytest.raises(LLMError, match="boom"):
        caller._call_api(system="s", user_content="u")


def test_explain_passes_text_and_context():
    caller = LLMCaller()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_message("a definition")
    caller._client = fake_client

    result = caller.explain("ephemeral", "lasting briefly")
    assert result == "a definition"
    sent = fake_client.messages.create.call_args.kwargs
    assert "ephemeral" in sent["messages"][0]["content"]
    assert "lasting briefly" in sent["messages"][0]["content"]


# --- routes turn LLMError into 502 ----------------------------------------------


def test_ask_question_returns_502_when_llm_fails(standard_client, monkeypatch):
    from library.routes import reader as reader_module

    def boom(*a, **kw):
        raise LLMError("provider down")

    monkeypatch.setattr(reader_module.llm_caller, "ask_question", boom)
    r = standard_client.post("/ask_question", json={"context": "foo", "question": "why?"})
    assert r.status_code == 502
    # Provider details go to the log, not to the reader.
    assert r.get_json()["error"] == "Couldn't get an answer just now. Try again."


def test_ai_reports_missing_api_key_plainly(standard_client, monkeypatch):
    from library.routes import reader as reader_module

    def no_key(*a, **kw):
        raise LLMError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(reader_module.llm_caller, "explain", no_key)
    r = standard_client.post("/explain", json={"text": "x", "context": "y"})
    assert r.status_code == 503
    assert r.get_json()["error"] == "AI help isn't set up on this library."


def test_explain_returns_502_when_llm_fails(standard_client, monkeypatch):
    from library.routes import reader as reader_module

    monkeypatch.setattr(
        reader_module.llm_caller,
        "explain",
        lambda *a, **kw: (_ for _ in ()).throw(LLMError("nope")),
    )
    r = standard_client.post("/explain", json={"text": "x", "context": "y"})
    assert r.status_code == 502


def test_ask_question_400_on_missing_fields(standard_client):
    r = standard_client.post("/ask_question", json={"context": "", "question": ""})
    assert r.status_code == 400


def test_ai_endpoints_require_sign_in(client):
    """Signed-out visitors can't spend the library's API credit."""
    for path, body in (
        ("/ask_question", {"context": "c", "question": "q"}),
        ("/explain", {"text": "t", "context": "c"}),
    ):
        r = client.post(path, json=body)
        assert r.status_code == 401
        assert r.get_json()["error"] == "Sign in to do that."


def test_explain_returns_explanation(standard_client, monkeypatch):
    from library.routes import reader as reader_module

    seen = {}

    def fake(text, context):
        seen.update(text=text, context=context)
        return "A boat."

    monkeypatch.setattr(reader_module.llm_caller, "explain", fake)
    r = standard_client.post("/explain", json={"text": " barque ", "context": "the barque sailed"})
    assert r.status_code == 200
    assert r.get_json() == {"explanation": "A boat."}
    assert seen == {"text": "barque", "context": "the barque sailed"}


def test_explain_requires_text(standard_client):
    assert standard_client.post("/explain", json={"text": " "}).status_code == 400


def test_explain_requires_sign_in(client):
    assert client.post("/explain", json={"text": "x"}).status_code == 401


def test_explain_prompt_covers_all_three_cases(monkeypatch):
    from library.llm_caller import LLMCaller

    captured = {}
    caller = LLMCaller()
    monkeypatch.setattr(caller, "_call_api", lambda **kw: captured.update(kw) or "ok")
    caller.explain("Weltschmerz", "a mood of Weltschmerz")
    for phrase in ("not in English", "single word", "longer English passage"):
        assert phrase in captured["system"]
