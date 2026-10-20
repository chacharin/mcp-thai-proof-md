"""Settings from environment (.env). Nothing here is ever returned to a caller except the model name."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from app.prompt import DEFAULT_SYSTEM_PROMPT

# citation codes such as [S1], [F12], [S3a] that a corrected line must keep unchanged
DEFAULT_PROTECTED_REGEX = r"\[[A-Z]{1,3}\d+[a-z]?\]"
# where backups/notes go: "file" = next to the file, "top" = in the first folder under the workspace
OUTPUT_PLACEMENTS = ("file", "top")
# request fields the tool always sets itself; LLM_EXTRA_PARAMS may not replace them
_RESERVED_LLM_PARAMS = {"model", "messages"}
# the dummy values shipped in .env.example (sk-or-v1-xxxx…, change-me) - never a real key
_PLACEHOLDER_KEY = re.compile(r"x{6,}|change-?me|your[-_ ]?(api[-_ ]?)?key", re.I)


def key_state(key: str) -> str:
    """"empty", "placeholder" (still the value copied from .env.example) or "set"."""
    if not key:
        return "empty"
    return "placeholder" if _PLACEHOLDER_KEY.search(key) else "set"


def _f(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in os.getenv(name, default).split(",") if p.strip()]


def _system_prompt() -> str:
    """SYSTEM_PROMPT_FILE replaces the built-in prompt; a missing or empty file is an error,
    so a typo in .env never silently falls back to a different prompt."""
    path = os.getenv("SYSTEM_PROMPT_FILE", "").strip()
    if not path:
        return DEFAULT_SYSTEM_PROMPT
    with open(path, encoding="utf-8-sig") as f:
        text = f.read().strip()
    if not text:
        raise ValueError(f"SYSTEM_PROMPT_FILE is empty: {path}")
    return text


def _protected() -> re.Pattern | None:
    raw = os.getenv("PROTECTED_REGEX", DEFAULT_PROTECTED_REGEX).strip()
    return re.compile(raw) if raw else None


def _extra_params() -> dict:
    """LLM_EXTRA_PARAMS: a JSON object merged into every /chat/completions request, for provider
    options this tool does not model itself (top_p, OpenRouter "provider"/"reasoning", vLLM extras...)."""
    raw = os.getenv("LLM_EXTRA_PARAMS", "").strip()
    if not raw:
        return {}
    extra = json.loads(raw)
    if not isinstance(extra, dict):
        raise ValueError("LLM_EXTRA_PARAMS must be a JSON object, e.g. {\"top_p\": 0.9}")
    clash = _RESERVED_LLM_PARAMS & extra.keys()
    if clash:
        raise ValueError(f"LLM_EXTRA_PARAMS may not set {sorted(clash)} - use LLM_MODEL / SYSTEM_PROMPT_FILE")
    return extra


def _placement() -> str:
    v = os.getenv("OUTPUT_PLACEMENT", "file").strip().lower() or "file"
    if v not in OUTPUT_PLACEMENTS:
        raise ValueError(f"OUTPUT_PLACEMENT must be one of {OUTPUT_PLACEMENTS}, got {v!r}")
    return v


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str = field(repr=False)
    llm_model: str
    llm_temperature: float
    llm_max_tokens: int
    llm_timeout: float
    llm_retries: int
    extra_headers: dict
    llm_extra_params: dict
    system_prompt: str
    chunk_chars: int
    context_lines: int
    workers: int
    min_similarity: float
    protected_regex: re.Pattern | None
    workspace_dir: str
    # no folder at WORKSPACE_DIR: reach the agent's workspace through the Hermes dashboard (see workspace.py)
    hermes_dashboard_url: str
    hermes_dashboard_user: str
    hermes_dashboard_password: str = field(repr=False)
    hermes_workspace: str
    path_prefixes: list[str]
    file_extensions: list[str]
    output_placement: str
    backup_subdir: str
    notes_subdir: str          # "" = do not write a notes log
    host: str
    port: int
    auth_token: str = field(repr=False)

    @staticmethod
    def from_env() -> "Settings":
        headers = {}
        if os.getenv("LLM_HTTP_REFERER"):
            headers["HTTP-Referer"] = os.getenv("LLM_HTTP_REFERER", "")
        if os.getenv("LLM_APP_TITLE"):
            headers["X-Title"] = os.getenv("LLM_APP_TITLE", "")
        return Settings(
            llm_base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "google/gemma-4-31b-it"),
            llm_temperature=_f("LLM_TEMPERATURE", "0"),
            llm_max_tokens=int(_f("LLM_MAX_TOKENS", "8000")),
            llm_timeout=_f("LLM_TIMEOUT_SECONDS", "180"),
            llm_retries=int(_f("LLM_RETRIES", "3")),
            extra_headers=headers,
            llm_extra_params=_extra_params(),
            system_prompt=_system_prompt(),
            chunk_chars=int(_f("CHUNK_CHARS", "3500")),
            context_lines=int(_f("CONTEXT_LINES", "3")),
            workers=max(1, int(_f("WORKERS", "4"))),
            min_similarity=_f("MIN_SIMILARITY", "0.5"),
            protected_regex=_protected(),
            workspace_dir=os.getenv("WORKSPACE_DIR", "/workspace").rstrip("/"),
            hermes_dashboard_url=os.getenv("HERMES_DASHBOARD_URL", "").strip().rstrip("/"),
            hermes_dashboard_user=os.getenv("HERMES_DASHBOARD_USER", "").strip(),
            hermes_dashboard_password=os.getenv("HERMES_DASHBOARD_PASSWORD", ""),
            hermes_workspace=os.getenv("HERMES_WORKSPACE", "/opt/data/workspace").strip().rstrip("/"),
            path_prefixes=[p.replace("\\", "/") for p in _list("PATH_PREFIXES", "")],
            file_extensions=[e.lower() if e.startswith(".") else "." + e.lower()
                             for e in _list("FILE_EXTENSIONS", ".md")],
            output_placement=_placement(),
            backup_subdir=os.getenv("BACKUP_SUBDIR", "backups").strip() or "backups",   # backups are never off
            notes_subdir=os.getenv("NOTES_SUBDIR", "notes").strip(),
            host=os.getenv("MCP_HOST", "0.0.0.0"),
            port=int(_f("MCP_PORT", "8800")),
            auth_token=os.getenv("MCP_AUTH_TOKEN", "").strip(),
        )
