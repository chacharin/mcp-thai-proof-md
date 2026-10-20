"""End-to-end with a fake model: proofread_lines and the file job of proofread_thai."""
import importlib
from pathlib import Path

import pytest

from conftest import checked_lines


def fix_typos(prompt: str) -> str:
    return "\n".join(ln.replace("ขบเคลอน", "ขับเคลื่อน").replace("ท่ี", "ที่") for ln in checked_lines(prompt))


def test_proofread_lines_applies_good_fixes_and_rejects_bad_ones(settings, fake_llm):
    from app.proofread import proofread_lines

    def model(prompt):
        out = []
        for ln in checked_lines(prompt):
            ln = ln.replace("ขบเคลอน", "ขับเคลื่อน")
            out.append(ln.replace("[S1]", "[S9]"))         # a forbidden edit on top of a good one
        return "\n".join(out)

    fake_llm(model)
    r = proofread_lines(["# เรื่อง", "ปัจจัยขบเคลอนหลัก", "ปัจจัยขบเคลอน [S1]"], settings)
    assert r["lines"][1] == "ปัจจัยขับเคลื่อนหลัก"
    assert r["lines"][2] == "ปัจจัยขบเคลอน [S1]"          # whole line kept: the code changed
    assert [c["line"] for c in r["changes"]] == [2]
    assert [c["line"] for c in r["rejected"]] == [3]
    assert r["errors"] == []


def test_wrong_line_count_splits_the_chunk_and_retries(settings, fake_llm):
    from app.proofread import proofread_lines

    def model(prompt):
        lines = checked_lines(prompt)
        return "ตอบผิดจำนวน" if len(lines) > 1 else fix_typos(prompt)

    seen = fake_llm(model)
    r = proofread_lines(["ท่ีหนึ่ง", "ท่ีสอง"], settings)
    assert r["lines"] == ["ที่หนึ่ง", "ที่สอง"]
    assert len(seen) == 3                                  # 1 failed call for 2 lines, then 1 per half


@pytest.fixture
def server(clean_env, monkeypatch):
    """app.server reads its settings at import time - reload it inside the test environment."""
    import app.server
    return importlib.reload(app.server)


def reload_server():
    import app.server
    return importlib.reload(app.server)


def test_file_job_writes_backup_and_notes(server, clean_env, fake_llm):
    fake_llm(fix_typos)
    job = clean_env / "project-a"
    job.mkdir()
    (job / "chapter1.md").write_text("# รายงาน\nปัจจัยขบเคลอน\n", encoding="utf-8")

    res = server._file_job("project-a/chapter1.md", dry_run=False)

    assert res["ok"] and res["lines_changed"] == 1
    assert (job / "chapter1.md").read_text(encoding="utf-8") == "# รายงาน\nปัจจัยขับเคลื่อน\n"
    backups = list((job / "backups").iterdir())
    assert len(backups) == 1 and "ขบเคลอน" in backups[0].read_text(encoding="utf-8")
    assert (job / "notes" / "proofread-chapter1.md").is_file()


def test_path_prefixes_are_stripped_only_when_configured(monkeypatch, clean_env):
    (clean_env / "report.md").write_text("x", encoding="utf-8")
    with pytest.raises(FileNotFoundError):                       # default: no prefix is known
        reload_server().resolve("/opt/data/workspace/report.md")
    monkeypatch.setenv("PATH_PREFIXES", "/opt/data/workspace/")
    assert reload_server().resolve("/opt/data/workspace/report.md") == "report.md"


@pytest.mark.parametrize("placement,where", [("file", "project-a/part1"), ("top", "project-a")])
def test_output_placement(monkeypatch, clean_env, fake_llm, placement, where):
    monkeypatch.setenv("OUTPUT_PLACEMENT", placement)
    server = reload_server()
    fake_llm(fix_typos)
    deep = clean_env / "project-a" / "part1"
    deep.mkdir(parents=True)
    (deep / "x.md").write_text("ปัจจัยขบเคลอน\n", encoding="utf-8")
    server._file_job("project-a/part1/x.md", dry_run=False)
    assert (clean_env / where / "backups").is_dir()
    assert (clean_env / where / "notes" / "proofread-x.md").is_file()


def test_notes_off(monkeypatch, clean_env, fake_llm):
    monkeypatch.setenv("NOTES_SUBDIR", "")
    server = reload_server()
    fake_llm(fix_typos)
    (clean_env / "r.md").write_text("ปัจจัยขบเคลอน\n", encoding="utf-8")
    res = server._file_job("r.md", dry_run=False)
    assert "log" not in res and (clean_env / "backups").is_dir() and not (clean_env / "notes").exists()


def test_request_body_carries_extra_params(monkeypatch):
    import io
    import json
    import urllib.request

    from app.config import Settings
    from app.proofread import LLM

    monkeypatch.setenv("LLM_EXTRA_PARAMS", '{"top_p": 0.5}')
    monkeypatch.setenv("LLM_API_KEY", "k")
    sent = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        sent["body"] = json.loads(req.data)
        sent["auth"] = req.get_header("Authorization")
        return Resp(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert LLM(Settings.from_env()).complete("u") == "ok"
    assert sent["body"]["top_p"] == 0.5 and sent["body"]["messages"][1]["content"] == "u"
    assert sent["auth"] == "Bearer k"


def test_dry_run_changes_nothing(server, clean_env, fake_llm):
    fake_llm(fix_typos)
    f = clean_env / "report.md"
    f.write_text("ปัจจัยขบเคลอน\n", encoding="utf-8")
    res = server._file_job("report.md", dry_run=True)
    assert res["lines_changed"] == 1 and res["changes"]
    assert f.read_text(encoding="utf-8") == "ปัจจัยขบเคลอน\n"
    assert not (clean_env / "backups").exists()


def test_custom_backup_and_notes_folders(monkeypatch, clean_env, fake_llm):
    monkeypatch.setenv("BACKUP_SUBDIR", "_orig")
    monkeypatch.setenv("NOTES_SUBDIR", "_log")
    server = reload_server()
    fake_llm(fix_typos)
    (clean_env / "report.md").write_text("ปัจจัยขบเคลอน\n", encoding="utf-8")
    server._file_job("report.md", dry_run=False)
    assert (clean_env / "_orig").is_dir() and (clean_env / "_log").is_dir()


@pytest.mark.parametrize("path,error", [
    ("../outside.md", "inside the workspace"),
    ("notes.txt", "only .md"),
    ("missing.md", "file not found"),
])
def test_resolve_refuses_bad_paths(server, clean_env, path, error):
    (clean_env / "notes.txt").write_text("x", encoding="utf-8")
    (clean_env.parent / "outside.md").write_text("x", encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError), match=error):
        server.resolve(path)
