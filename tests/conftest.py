"""Shared fixtures. No test calls a real LLM: LLM.complete is replaced by a fake."""
from __future__ import annotations

import pytest

ENV_KEYS = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_TEMPERATURE", "LLM_MAX_TOKENS", "LLM_TIMEOUT_SECONDS",
            "LLM_RETRIES", "LLM_HTTP_REFERER", "LLM_APP_TITLE", "LLM_EXTRA_PARAMS", "SYSTEM_PROMPT_FILE",
            "CHUNK_CHARS", "CONTEXT_LINES", "WORKERS", "MIN_SIMILARITY", "PROTECTED_REGEX", "WORKSPACE_DIR",
            "PATH_PREFIXES", "FILE_EXTENSIONS", "OUTPUT_PLACEMENT", "BACKUP_SUBDIR", "NOTES_SUBDIR",
            "MCP_HOST", "MCP_PORT", "MCP_AUTH_TOKEN"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Every test starts from the code defaults, with a throw-away workspace."""
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    return tmp_path / "ws"


@pytest.fixture
def settings():
    from app.config import Settings
    return Settings.from_env()


@pytest.fixture
def fake_llm(monkeypatch):
    """fake_llm(fn): fn(user_prompt) -> model output; returns the list of prompts it received."""
    from app import proofread

    def install(fn):
        seen = []

        def complete(self, user):
            seen.append(user)
            return fn(user)

        monkeypatch.setattr(proofread.LLM, "complete", complete)
        return seen

    return install


def checked_lines(prompt: str) -> list[str]:
    """The lines a prompt asks the model to fix (between <<< and >>>)."""
    body = prompt.split("<<<\n", 1)[1]
    return body.rsplit("\n>>>", 1)[0].split("\n")
