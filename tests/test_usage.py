"""The usage log: one record per model call and per tool call, read back through GET /usage."""
import asyncio
import importlib
import io
import json
import urllib.request

import pytest
from starlette.testclient import TestClient

from conftest import checked_lines

USAGE = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150, "cost": 0.0004,
         "prompt_tokens_details": {"cached_tokens": 20}, "completion_tokens_details": {"reasoning_tokens": 5}}


@pytest.fixture
def openrouter(monkeypatch):
    """A fake OpenAI-compatible endpoint that fixes one typo and reports token usage like OpenRouter."""
    def urlopen(req, timeout=None):
        prompt = json.loads(req.data)["messages"][1]["content"]
        fixed = "\n".join(ln.replace("ขบเคลอน", "ขับเคลื่อน") for ln in checked_lines(prompt))
        body = {"model": "google/gemma-4-31b-it", "provider": "Google",
                "choices": [{"message": {"content": fixed}, "finish_reason": "stop"}], "usage": USAGE}
        resp = io.BytesIO(json.dumps(body).encode())
        resp.__enter__ = lambda *a: resp
        resp.__exit__ = lambda *a: None
        return resp
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def load_server():
    import app.server
    return importlib.reload(app.server)


def records(server, **params):
    return TestClient(server.app).get("/usage", params=params).json()["records"]


def test_file_job_logs_model_call_and_tool_call(clean_env, openrouter):
    (clean_env / "report.md").write_text("ปัจจัยขบเคลอนหลัก\n", encoding="utf-8")
    server = load_server()
    res = asyncio.run(server.proofread_thai("report.md"))
    assert res["ok"] and "_llm_calls" not in res and "_file_chars" not in res   # internal fields stay out
    call, tool = records(server)
    assert call["kind"] == "llm_call" and call["tool"] == "proofread_thai"
    assert (call["input_tokens"], call["cache_read_tokens"], call["output_tokens"], call["reasoning_tokens"]) \
        == (100, 20, 30, 5)
    assert call["cost_usd"] == 0.0004 and call["upstream_provider"] == "Google" and call["status"] == "ok"
    assert tool["kind"] == "mcp_tool" and tool["request_id"] == call["request_id"]
    assert tool["total_tokens"] == 150 and tool["detail"]["llm_calls"] == 1 and tool["detail"]["lines_changed"] == 1
    assert "ขบเคลอน" not in json.dumps([call, tool], ensure_ascii=False)                # no text is logged


def test_text_tool_and_failures_are_logged(openrouter):
    server = load_server()
    asyncio.run(server.proofread_text("ปัจจัยขบเคลอน"))
    asyncio.run(server.proofread_thai("missing.md"))
    kinds = [(r["kind"], r["tool"], r["status"]) for r in records(server)]
    assert kinds == [("llm_call", "proofread_text", "ok"), ("mcp_tool", "proofread_text", "ok"),
                     ("mcp_tool", "proofread_thai", "error")]


def test_since_filter_and_environment(openrouter):
    server = load_server()
    asyncio.run(server.proofread_text("ปัจจัยขบเคลอน"))
    body = TestClient(server.app).get("/usage").json()
    assert body["schema"] == "harness-usage/1" and body["environment"]["component"] == "mcp-thai-proofread"
    assert records(server, since=body["records"][-1]["ts"] + 1) == []


def test_usage_needs_the_token_when_set(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "t0ken")
    server = load_server()
    client = TestClient(server.app)
    assert client.get("/usage").status_code == 401
    assert client.get("/usage", headers={"Authorization": "Bearer t0ken"}).status_code == 200


def test_usage_log_can_be_switched_off(monkeypatch, openrouter):
    monkeypatch.setenv("USAGE_LOG", "false")
    server = load_server()
    asyncio.run(server.proofread_text("ปัจจัยขบเคลอน"))
    assert records(server) == []
