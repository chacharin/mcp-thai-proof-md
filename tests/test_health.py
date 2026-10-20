"""Telling a new user what is wrong: placeholder keys, /health, and the error of a refused LLM call."""
import importlib
import io
import urllib.error
import urllib.request

import pytest

from app.config import Settings, key_state


@pytest.mark.parametrize("key,state", [
    ("", "empty"),
    ("sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "placeholder"),   # the value in .env.example
    ("change-me", "placeholder"),
    ("YOUR_API_KEY", "placeholder"),
    ("test-key-not-real-0123456789", "set"),
])
def test_key_state(key, state):
    assert key_state(key) == state


def health_with(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app.server
    return importlib.reload(app.server).health_report()


def test_health_flags_the_example_key(monkeypatch):
    h = health_with(monkeypatch, LLM_API_KEY="sk-or-v1-xxxxxxxxxxxxxxxx")
    assert h["ok"] is False and h["key_configured"] is False
    assert any(".env.example" in p for p in h["problems"])


def test_health_with_a_real_key(monkeypatch):
    h = health_with(monkeypatch, LLM_API_KEY="test-key-not-real-0123")
    assert h["ok"] is True and h["key_configured"] is True and h["problems"] == []


def test_health_local_endpoint_needs_no_key(monkeypatch):
    h = health_with(monkeypatch, LLM_BASE_URL="http://localhost:11434/v1")
    assert h["ok"] is True and h["problems"] == []


def test_health_empty_key_on_a_remote_endpoint_is_explained(monkeypatch):
    h = health_with(monkeypatch)                       # default endpoint is OpenRouter
    assert h["ok"] is False and any("empty" in p for p in h["problems"])


def test_health_reports_a_missing_workspace(monkeypatch, tmp_path):
    h = health_with(monkeypatch, LLM_API_KEY="sk-real-1234567", WORKSPACE_DIR=str(tmp_path / "nope"))
    assert h["workspace"]["mode"] is None and any("no workspace" in p for p in h["problems"])


@pytest.mark.parametrize("code,expect", [(401, "check LLM_API_KEY"), (403, "budget exceeded")])
def test_refused_llm_call_explains_why(monkeypatch, code, expect):
    from app.proofread import LLM

    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, code, "refused", {},
                                     io.BytesIO(b'{"error": "Workspace daily budget exceeded"}'))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(RuntimeError, match=expect):
        LLM(Settings.from_env()).complete("u")
