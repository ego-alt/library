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


def test_define_word_passes_word_and_context():
    caller = LLMCaller()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_message("a definition")
    caller._client = fake_client

    result = caller.define_word("ephemeral", "lasting briefly")
    assert result == "a definition"
    sent = fake_client.messages.create.call_args.kwargs
    assert "ephemeral" in sent["messages"][0]["content"]
    assert "lasting briefly" in sent["messages"][0]["content"]


# --- routes turn LLMError into 502 ----------------------------------------------


def test_ask_question_returns_502_when_llm_fails(client, monkeypatch):
    from library.routes import reader as reader_module

    def boom(*a, **kw):
        raise LLMError("provider down")

    monkeypatch.setattr(reader_module.llm_caller, "ask_question", boom)
    r = client.post("/ask_question", json={"context": "foo", "question": "why?"})
    assert r.status_code == 502
    assert "provider down" in r.get_json()["error"]


def test_define_word_returns_502_when_llm_fails(client, monkeypatch):
    from library.routes import reader as reader_module

    monkeypatch.setattr(
        reader_module.llm_caller,
        "define_word",
        lambda *a, **kw: (_ for _ in ()).throw(LLMError("nope")),
    )
    r = client.post("/define_word", json={"word": "x", "context": "y"})
    assert r.status_code == 502


def test_ask_question_400_on_missing_fields(client):
    r = client.post("/ask_question", json={"context": "", "question": ""})
    assert r.status_code == 400
