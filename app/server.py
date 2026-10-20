"""mcp-thai-proofread: MCP server over streamable HTTP (http://<host>:<port>/mcp) + GET /health.

Tools
  proofread_thai(path, dry_run=False)  fix Thai spelling of a file (FILE_EXTENSIONS, default .md) in the
                                       workspace; the original is backed up to <folder>/BACKUP_SUBDIR/
                                       and the changes are logged to <folder>/NOTES_SUBDIR/proofread-<name>.md
                                       (NOTES_SUBDIR empty = no log)
  proofread_text(text, title="")       fix Thai spelling of a text and return it (no file access)

GET /usage?since=&until=&limit=  the usage log (tokens and timings of every model call and tool call, no text)
                                 - see usage.py; needs the MCP_AUTH_TOKEN like /mcp when one is set

<folder> depends on OUTPUT_PLACEMENT: "file" (default) = the folder of the file itself,
"top" = the first folder under the workspace (one place per project folder, however deep the file is).

The workspace is WORKSPACE_DIR when it is mounted here, otherwise the agent's workspace inside Hermes through
the Hermes dashboard files API (HERMES_DASHBOARD_URL / _USER / _PASSWORD) - see workspace.py.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hmac
import posixpath
import sys
import time
import uuid
from typing import Annotated

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app.config import Settings, key_state
from app.proofread import proofread_lines, suspect_count
from app.usage import SCHEMA, UsageLog, sum_tokens
from app.workspace import WorkspaceError, open_workspace, safe_relative

S = Settings.from_env()
if key_state(S.llm_api_key) == "placeholder":   # visible in `docker logs` right after start-up
    print("WARNING: LLM_API_KEY is still the example value from .env.example - every LLM call will fail",
          file=sys.stderr, flush=True)
WS = open_workspace(S)   # LocalWorkspace / HermesWorkspace / None (no workspace: proofread_text only)
VERSION = "0.3.0"
USAGE = UsageLog("mcp-thai-proofread", VERSION, S.usage_dir, S.usage_log)
mcp = MCPServer(
    name="thai-proofread",
    instructions=("ตรวจและแก้การสะกดภาษาไทยของไฟล์ใน workspace หรือของข้อความ "
                  "แก้เฉพาะการสะกด ไม่เปลี่ยนเนื้อหา ตัวเลข รหัสที่กำหนดไว้ URL และคำภาษาอังกฤษ"),
)


def output_dir(rel: str) -> str:
    """Folder (relative to the workspace) that receives the backups/ and notes/ sub-folders (see OUTPUT_PLACEMENT)."""
    parts = rel.split("/")
    if S.output_placement == "top" and len(parts) > 1:
        return parts[0]
    return posixpath.dirname(rel)


# ------------------------------------------------------------------ files
def resolve(path: str) -> str:
    """Map a path given by the agent to a file in the workspace. Returns its path relative to the workspace."""
    if WS is None:
        raise WorkspaceError("no workspace: mount WORKSPACE_DIR, or set the Hermes dashboard login "
                             "(HERMES_DASHBOARD_URL / _USER / _PASSWORD)")
    p = (path or "").strip().replace("\\", "/")
    for pre in S.path_prefixes:
        if p.startswith(pre):
            p = p[len(pre):]
            break
    rel = safe_relative(p)
    if not rel.lower().endswith(tuple(S.file_extensions)):
        raise ValueError(f"only {', '.join(S.file_extensions)} files can be proofread")
    if not WS.is_file(rel):
        raise FileNotFoundError(f"file not found: {path}")
    return rel


def _file_job(path: str, dry_run: bool) -> dict:
    rel = resolve(path)
    original = WS.read(rel)
    t0 = dt.datetime.now()
    r = proofread_lines(original.split("\n"), S)
    text = "\n".join(r["lines"])
    res = {"_llm_calls": r["llm_calls"], "_file_chars": len(original), "ok": not r["errors"], "file": rel, "model": S.llm_model, "dry_run": dry_run, "chunks": r["chunks"],
           "lines_changed": len(r["changes"]), "lines_rejected": len(r["rejected"]),
           "suspect_before": suspect_count(original), "suspect_after": suspect_count(text),
           "errors": r["errors"], "seconds": round((dt.datetime.now() - t0).total_seconds(), 1)}
    if dry_run:
        return {**res, "changes": r["changes"][:60], "rejected": r["rejected"][:60]}
    job_dir = output_dir(rel)
    stamp = t0.strftime("%Y%m%d-%H%M%S")
    name = posixpath.basename(rel)
    if r["changes"]:
        backup = posixpath.join(job_dir, S.backup_subdir, f"{name}.bak-proof-{stamp}")
        WS.write(backup, original)      # the backup first: the file is only replaced once it is safe
        WS.write(rel, text)
        res["backup"] = backup
    res["sample_changes"] = [{"before": c["before"][:120], "after": c["after"][:120]} for c in r["changes"][:10]]
    if not S.notes_subdir:
        return res
    log = posixpath.join(job_dir, S.notes_subdir, f"proofread-{posixpath.splitext(name)[0]}.md")
    lines = [f"\n## ตรวจภาษาไทย {stamp} · {S.llm_model}\n\n"
             f"- ไฟล์: `{rel}` · ส่งตรวจ {r['chunks']} ช่วง · แก้ {len(r['changes'])} บรรทัด · "
             f"ปฏิเสธการแก้ไข {len(r['rejected'])} บรรทัด\n"
             f"- จุดที่น่าสงสัย (ตรวจด้วยรูปแบบ) ก่อน/หลัง: {res['suspect_before']} / {res['suspect_after']}\n"]
    lines += [f"- ข้อผิดพลาด: {e}\n" for e in r["errors"]]
    lines += [f"\n- บรรทัด {c['line']}\n  - เดิม: {c['before']}\n  - แก้: {c['after']}\n" for c in r["changes"]]
    lines += [f"\n- บรรทัด {c['line']} ปฏิเสธการแก้ไข ({c['reason']})\n  - เดิม: {c['before']}\n  - ที่เสนอ: {c['suggested']}\n"
              for c in r["rejected"]]
    WS.append(log, "".join(lines))
    res["log"] = log
    return res


# ------------------------------------------------------------------ usage log
def log_tool(tool: str, t0: float, calls: list[dict], status: str, error: str | None, detail: dict) -> None:
    """One usage record per model call, then one for the whole tool call (with the summed tokens)."""
    rid = uuid.uuid4().hex[:16]
    for c in calls:
        USAGE.write({**c, "tool": tool, "request_id": rid})
    t1 = time.time()
    USAGE.write({"kind": "mcp_tool", "tool": tool, "request_id": rid, "model": S.llm_model,
                 "started_at": round(t0, 3), "ended_at": round(t1, 3), "duration_s": round(t1 - t0, 3),
                 **sum_tokens(calls), "tokens_estimated": False if calls else None,
                 "status": status, "error": error,
                 "detail": {"llm_calls": len(calls), "llm_seconds": round(sum(c["duration_s"] for c in calls), 3),
                            **detail}})


# ------------------------------------------------------------------ tools
PROOFREAD_THAI_DESCRIPTION = (
    "ตรวจและแก้คำสะกดภาษาไทยในไฟล์ใน workspace แล้วบันทึกทับไฟล์เดิม โดยสำรองไฟล์ต้นฉบับไว้ก่อนเสมอ "
    "แก้เฉพาะการสะกด ไม่เปลี่ยนเนื้อหา ตัวเลข รหัสอ้างอิง URL และคำภาษาอังกฤษ "
    "ไฟล์ยาวอาจใช้เวลาหลายนาที เพราะระบบส่งให้ LLM ตรวจทีละช่วง "
    "หากต้องการดูรายการที่จะแก้ก่อนโดยยังไม่เปลี่ยนไฟล์ ให้กำหนด dry_run เป็น true"
)
PATH_HELP = ("ตำแหน่งไฟล์เทียบกับราก workspace เช่น \"report.md\" หรือ \"project-a/chapter1.md\" "
             f"(รับเฉพาะไฟล์นามสกุล {', '.join(S.file_extensions)})")
PROOFREAD_TEXT_DESCRIPTION = (
    "ตรวจและแก้คำสะกดภาษาไทยในข้อความ แล้วส่งข้อความที่แก้แล้วกลับมา โดยไม่อ่านหรือเขียนไฟล์ใด ๆ "
    "เหมาะกับข้อความที่ยังไม่ได้บันทึกเป็นไฟล์ เช่น ร่างคำตอบหรือย่อหน้าที่ผู้ใช้วางมา"
)


async def proofread_thai(
    path: Annotated[str, Field(description=PATH_HELP)],
    dry_run: Annotated[bool, Field(description=(
        "true = ตรวจอย่างเดียว แล้วส่งรายการที่จะแก้กลับมา โดยไม่เปลี่ยนไฟล์"))] = False,
) -> dict:
    t0 = time.time()
    try:
        res = await asyncio.to_thread(_file_job, path, dry_run)
    except (ValueError, FileNotFoundError, OSError, WorkspaceError) as e:
        log_tool("proofread_thai", t0, [], "error", type(e).__name__, {"dry_run": dry_run})
        return {"ok": False, "error": str(e)}
    calls, chars = res.pop("_llm_calls", []), res.pop("_file_chars", None)
    log_tool("proofread_thai", t0, calls, "ok" if res["ok"] else "error", None if res["ok"] else "llm_errors",
             {"dry_run": dry_run, "file_chars": chars, "chunks": res.get("chunks"),
              "lines_changed": res.get("lines_changed"), "lines_rejected": res.get("lines_rejected"),
              "workspace": WS.mode if WS else None})
    return res


def _without_title(items: list[dict]) -> list[dict]:
    """proofread_text puts the title on line 1 as context: drop that line and number the rest from 1."""
    return [{**c, "line": c["line"] - 1} for c in items if c["line"] > 1]


async def proofread_text(
    text: Annotated[str, Field(description="ข้อความที่ต้องการตรวจ (ใช้ Markdown ได้)")],
    title: Annotated[str, Field(description=(
        "ชื่อเรื่องของข้อความ ใช้เป็นบริบทให้ LLM เท่านั้น ไม่ถูกแก้ไขและไม่รวมอยู่ในผลลัพธ์"))] = "",
) -> dict:
    lines = ((f"# {title}\n" if title else "") + (text or "")).split("\n")
    t0 = time.time()
    r = await asyncio.to_thread(proofread_lines, lines, S)
    out = r["lines"][1:] if title else r["lines"]
    changes = _without_title(r["changes"]) if title else r["changes"]
    rejected = _without_title(r["rejected"]) if title else r["rejected"]
    log_tool("proofread_text", t0, r["llm_calls"], "error" if r["errors"] else "ok",
             "llm_errors" if r["errors"] else None,
             {"text_chars": len(text or ""), "chunks": r["chunks"], "lines_changed": len(changes),
              "lines_rejected": len(rejected)})
    return {"ok": not r["errors"], "model": S.llm_model, "text": "\n".join(out),
            "lines_changed": len(changes), "lines_rejected": len(rejected),
            "changes": changes[:60], "rejected": rejected[:60], "errors": r["errors"]}


# proofread_thai rewrites a file, but always keeps a backup first, so it is not marked destructive
mcp.add_tool(proofread_thai, description=PROOFREAD_THAI_DESCRIPTION,
             annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True))
mcp.add_tool(proofread_text, description=PROOFREAD_TEXT_DESCRIPTION,
             annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))


# ------------------------------------------------------------------ http app
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal")


def health_report() -> dict:
    """ok = the LLM settings look usable. problems explains every reason it is not (or may not be)."""
    state = key_state(S.llm_api_key)
    local = any(h in S.llm_base_url for h in _LOCAL_HOSTS)
    reachable = WS is not None and WS.reachable()
    problems = []
    if state == "placeholder":
        problems.append("LLM_API_KEY is still the example value from .env.example - put your real key in .env")
    elif state == "empty" and not local:
        problems.append("LLM_API_KEY is empty - fine only if LLM_BASE_URL needs no key")
    if S.usage_log and not USAGE.writable():
        problems.append(f"the usage log folder {S.usage_dir} is not writable - usage records are not kept")
    if WS is None:
        problems.append("no workspace: mount WORKSPACE_DIR, or set the Hermes dashboard login - "
                        "proofread_thai cannot reach any file (proofread_text still works)")
    elif not reachable:
        problems.append("the workspace cannot be reached - " + ("is the folder mounted?" if WS.mode == "local"
                        else "check HERMES_DASHBOARD_URL / _USER / _PASSWORD"))
    return {"ok": state == "set" or (state == "empty" and local),
            "model": S.llm_model, "base_url": S.llm_base_url,
            "key_configured": state == "set",
            "workspace": {"mode": WS.mode if WS else None, "root": WS.root if WS else None, "reachable": reachable},
            "usage_log": {"enabled": S.usage_log, "dir": S.usage_dir, "writable": USAGE.writable(),
                          "last_error": USAGE.error},
            "auth": bool(S.auth_token), "problems": problems}


async def health(_: Request) -> JSONResponse:
    return JSONResponse(health_report())


def _qf(request: Request, name: str) -> float | None:
    v = request.query_params.get(name)
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


async def usage(request: Request) -> JSONResponse:
    """The usage log: ?since=<epoch s>&until=<epoch s>&limit=<n> (default: everything kept, newest 50000)."""
    limit = int(_qf(request, "limit") or 50000)
    return JSONResponse({"schema": SCHEMA, "environment": USAGE.env,
                         "records": USAGE.read(_qf(request, "since"), _qf(request, "until"), max(1, limit))})


class BearerAuth:
    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.token and scope["path"].startswith(("/mcp", "/usage")):
            got = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
            if not hmac.compare_digest(got, f"Bearer {self.token}"):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp", stateless_http=True, host=S.host,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@contextlib.asynccontextmanager
async def lifespan(app):
    async with mcp_app.router.lifespan_context(app):
        yield


app = BearerAuth(Starlette(routes=[Route("/health", health), Route("/usage", usage), Mount("/", app=mcp_app)], lifespan=lifespan), S.auth_token)

if __name__ == "__main__":
    uvicorn.run(app, host=S.host, port=S.port, log_level="info")
