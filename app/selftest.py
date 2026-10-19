"""Self-test inside the container: list the tools and run proofread_text (one real LLM call).
Optional: --file <path in the workspace> runs proofread_thai with dry_run=true (no file is changed).
Run: docker exec mcp-thai-proofread /app/.venv/bin/python -m app.selftest [--file report.md]"""
import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = f"http://127.0.0.1:{os.getenv('MCP_PORT', '8800')}/mcp"
SAMPLE = "| เรยน | ผู้อำนวยการ |\nรายงานวิเคราะหปจจัยขบเคลอนการเปลี่ยนแปลงสภาพภูมิอากาศ ข่าวถึงวantry 30 ก.ย. 2569 [S2]"


async def main() -> None:
    headers = {"Authorization": f"Bearer {os.environ['MCP_AUTH_TOKEN']}"} if os.getenv("MCP_AUTH_TOKEN") else None
    kwargs = {"headers": headers} if headers else {}
    try:
        cm = streamable_http_client(URL, **kwargs)
    except TypeError:
        cm = streamable_http_client(URL)
    async with cm as (r, w, *_):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("tools:", [t.name for t in (await s.list_tools()).tools])
            res = json.loads((await s.call_tool("proofread_text", {"text": SAMPLE, "title": "ทดสอบ"})).content[0].text)
            print("model:", res.get("model"), "| ok:", res.get("ok"), "| errors:", res.get("errors"))
            print("before:\n" + SAMPLE)
            print("after:\n" + res.get("text", ""))
            if "--file" in sys.argv:
                path = sys.argv[sys.argv.index("--file") + 1]
                d = json.loads((await s.call_tool("proofread_thai", {"path": path, "dry_run": True})).content[0].text)
                print(json.dumps({k: d.get(k) for k in ("ok", "file", "chunks", "lines_changed", "lines_rejected",
                                                        "suspect_before", "suspect_after", "errors", "seconds", "error")},
                                 ensure_ascii=False, indent=1))
                for c in (d.get("changes") or [])[:15]:
                    print(f"  line {c['line']}: {c['before'][:90]}\n        => {c['after'][:90]}")
                for c in (d.get("rejected") or [])[:10]:
                    print(f"  REJECTED line {c['line']} ({c['reason']}): {c['suggested'][:90]}")


asyncio.run(main())
