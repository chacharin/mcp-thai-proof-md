"""The two MCP tools as an agent sees them: parameter descriptions, hints, and proofread_text results."""
import asyncio
import importlib

from tests.conftest import checked_lines


def load_server():
    import app.server
    return importlib.reload(app.server)


def fix_spelling(prompt: str) -> str:
    return "\n".join(line.replace("โอกาศ", "โอกาส") for line in checked_lines(prompt))


def test_every_parameter_is_described():
    server = load_server()
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for name in ("proofread_thai", "proofread_text"):
        props = tools[name].input_schema["properties"]
        assert all(p.get("description") for p in props.values()), name
    assert tools["proofread_text"].annotations.read_only_hint is True
    assert tools["proofread_thai"].annotations.destructive_hint is False      # a backup is always kept


def test_text_line_numbers_ignore_the_title(fake_llm):
    server = load_server()
    fake_llm(fix_spelling)
    out = asyncio.run(server.proofread_text("บรรทัดแรก\nมีโอกาศสำเร็จ", title="รายงาน"))
    assert out["text"] == "บรรทัดแรก\nมีโอกาสสำเร็จ"
    assert out["changes"] == [{"line": 2, "before": "มีโอกาศสำเร็จ", "after": "มีโอกาสสำเร็จ"}]


def test_text_without_a_title(fake_llm):
    server = load_server()
    fake_llm(fix_spelling)
    out = asyncio.run(server.proofread_text("มีโอกาศสำเร็จ"))
    assert out["changes"][0]["line"] == 1 and out["lines_changed"] == 1
