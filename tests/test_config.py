"""Settings read from .env, including the values that used to be hard-coded."""
from pathlib import Path

import pytest

from app.config import DEFAULT_PROTECTED_REGEX, Settings
from app.prompt import DEFAULT_SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parent.parent


def test_defaults_are_generic(settings):
    # nothing here may assume a particular agent or deployment
    assert settings.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert settings.protected_regex.pattern == DEFAULT_PROTECTED_REGEX
    assert settings.file_extensions == [".md"]
    assert settings.output_placement == "file"
    assert (settings.backup_subdir, settings.notes_subdir) == ("backups", "notes")
    assert settings.path_prefixes == []
    assert settings.llm_extra_params == {}
    assert settings.extra_headers == {}


def test_extra_params(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_PARAMS", '{"top_p": 0.9, "provider": {"order": ["x"]}}')
    assert Settings.from_env().llm_extra_params == {"top_p": 0.9, "provider": {"order": ["x"]}}


@pytest.mark.parametrize("raw", ['{"model": "other"}', '{"messages": []}', "[1, 2]", "{not json"])
def test_bad_extra_params_fail_loudly(monkeypatch, raw):
    monkeypatch.setenv("LLM_EXTRA_PARAMS", raw)
    with pytest.raises(ValueError):          # json.JSONDecodeError is a ValueError too
        Settings.from_env()


def test_output_placement_is_validated(monkeypatch):
    monkeypatch.setenv("OUTPUT_PLACEMENT", "TOP")
    assert Settings.from_env().output_placement == "top"
    monkeypatch.setenv("OUTPUT_PLACEMENT", "beside")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_notes_can_be_switched_off_but_backups_cannot(monkeypatch):
    monkeypatch.setenv("NOTES_SUBDIR", "")
    monkeypatch.setenv("BACKUP_SUBDIR", "")
    s = Settings.from_env()
    assert s.notes_subdir == "" and s.backup_subdir == "backups"


def test_example_prompt_file_matches_the_built_in_prompt():
    # prompts/system_prompt.example.md is what users copy - it must stay the real default
    example = (ROOT / "prompts" / "system_prompt.example.md").read_text(encoding="utf-8").strip()
    assert example == DEFAULT_SYSTEM_PROMPT


def test_system_prompt_file(monkeypatch, tmp_path):
    f = tmp_path / "p.md"
    f.write_text("คุณคือผู้ตรวจคำสะกด\n", encoding="utf-8")
    monkeypatch.setenv("SYSTEM_PROMPT_FILE", str(f))
    assert Settings.from_env().system_prompt == "คุณคือผู้ตรวจคำสะกด"


def test_missing_or_empty_prompt_file_fails_loudly(monkeypatch, tmp_path):
    monkeypatch.setenv("SYSTEM_PROMPT_FILE", str(tmp_path / "nope.md"))
    with pytest.raises(OSError):
        Settings.from_env()
    empty = tmp_path / "empty.md"
    empty.write_text("  \n", encoding="utf-8")
    monkeypatch.setenv("SYSTEM_PROMPT_FILE", str(empty))
    with pytest.raises(ValueError):
        Settings.from_env()


def test_protected_regex_custom_and_disabled(monkeypatch):
    monkeypatch.setenv("PROTECTED_REGEX", r"DOC-\d{4}")
    assert Settings.from_env().protected_regex.findall("DOC-0012 และ DOC-0013") == ["DOC-0012", "DOC-0013"]
    monkeypatch.setenv("PROTECTED_REGEX", "")
    assert Settings.from_env().protected_regex is None


def test_file_extensions_are_normalised(monkeypatch):
    monkeypatch.setenv("FILE_EXTENSIONS", "md, .TXT")
    assert Settings.from_env().file_extensions == [".md", ".txt"]
