"""mcp-thai-proofread: MCP server over streamable HTTP (http://<host>:<port>/mcp) + GET /health.

Tools
  proofread_thai(path, dry_run=False)  fix Thai spelling of a file (FILE_EXTENSIONS, default .md) under
                                       WORKSPACE_DIR; the original is backed up to <folder>/BACKUP_SUBDIR/
                                       and the changes are logged to <folder>/NOTES_SUBDIR/proofread-<name>.md
                                       (NOTES_SUBDIR empty = no log)
  proofread_text(text, title="")       fix Thai spelling of a text and return it (no file access)

<folder> depends on OUTPUT_PLACEMENT: "file" (default) = the folder of the file itself,
"top" = the first folder under the workspace (one place per project folder, however deep the file is).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hmac
import os
import sys

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app.config import Settings, key_state
from app.proofread import proofread_lines, suspect_count

S = Settings.from_env()
if key_state(S.llm_api_key) == "placeholder":   # visible in `docker logs` right after start-up
    print("WARNING: LLM_API_KEY is still the example value from .env.example - every LLM call will fail",
          file=sys.stderr, flush=True)
mcp = MCPServer(
    name="thai-proofread",
    instructions=("ตรวจและแก้การสะกดภาษาไทยของไฟล์ใน workspace หรือของข้อความ "
                  "แก้เฉพาะการสะกด ไม่เปลี่ยนเนื้อหา ตัวเลข รหัสที่กำหนดไว้ URL และคำภาษาอังกฤษ"),
)


def output_dir(real: str, rel: str) -> str:
    """Folder that receives the backups/ and notes/ sub-folders (see OUTPUT_PLACEMENT)."""
    parts = rel.split("/")
    if S.output_placement == "top" and len(parts) > 1:
        return os.path.join(S.workspace_dir, parts[0])
    return os.path.dirname(real)


# ------------------------------------------------------------------ files
def resolve(path: str) -> tuple[str, str]:
    """Map a path given by the agent to a real file under WORKSPACE_DIR. Returns (real, relative)."""
    p = (path or "").strip().replace("\\", "/")
    for pre in S.path_prefixes:
        if p.startswith(pre):
            p = p[len(pre):]
            break
    p = p.lstrip("/")
    root = os.path.realpath(S.workspace_dir)
    real = os.path.realpath(os.path.join(root, p))
    if not real.startswith(root + os.sep):
        raise ValueError("path must be inside the workspace")
    if not real.lower().endswith(tuple(S.file_extensions)):
        raise ValueError(f"only {', '.join(S.file_extensions)} files can be proofread")
    if not os.path.isfile(real):
        raise FileNotFoundError(f"file not found: {path}")
    return real, os.path.relpath(real, root)


def _file_job(path: str, dry_run: bool) -> dict:
    real, rel = resolve(path)
    with open(real, encoding="utf-8") as f:
        original = f.read()
    t0 = dt.datetime.now()
    r = proofread_lines(original.split("\n"), S)
    text = "\n".join(r["lines"])
    res = {"ok": not r["errors"], "file": rel, "model": S.llm_model, "dry_run": dry_run, "chunks": r["chunks"],
           "lines_changed": len(r["changes"]), "lines_rejected": len(r["rejected"]),
           "suspect_before": suspect_count(original), "suspect_after": suspect_count(text),
           "errors": r["errors"], "seconds": round((dt.datetime.now() - t0).total_seconds(), 1)}
    if dry_run:
        return {**res, "changes": r["changes"][:60], "rejected": r["rejected"][:60]}
    job_dir = output_dir(real, rel)
    stamp = t0.strftime("%Y%m%d-%H%M%S")
    name = os.path.basename(real)
    if r["changes"]:
        bdir = os.path.join(job_dir, S.backup_subdir)
        os.makedirs(bdir, exist_ok=True)
        backup = os.path.join(bdir, f"{name}.bak-proof-{stamp}")
        with open(backup, "w", encoding="utf-8") as f:
            f.write(original)
        with open(real, "w", encoding="utf-8") as f:
            f.write(text)
        res["backup"] = os.path.relpath(backup, S.workspace_dir)
    res["sample_changes"] = [{"before": c["before"][:120], "after": c["after"][:120]} for c in r["changes"][:10]]
    if not S.notes_subdir:
        return res
    ndir = os.path.join(job_dir, S.notes_subdir)
    os.makedirs(ndir, exist_ok=True)
    log = os.path.join(ndir, f"proofread-{os.path.splitext(name)[0]}.md")
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n## ตรวจภาษาไทย {stamp} · {S.llm_model}\n\n"
                f"- ไฟล์: `{rel}` · ส่งตรวจ {r['chunks']} ช่วง · แก้ {len(r['changes'])} บรรทัด · "
                f"ไม่รับการแก้ {len(r['rejected'])} บรรทัด\n"
                f"- จุดที่น่าสงสัย (ตรวจด้วยรูปแบบ) ก่อน/หลัง: {res['suspect_before']} / {res['suspect_after']}\n")
        for e in r["errors"]:
            f.write(f"- ข้อผิดพลาด: {e}\n")
        for c in r["changes"]:
            f.write(f"\n- บรรทัด {c['line']}\n  - เดิม: {c['before']}\n  - แก้: {c['after']}\n")
        for c in r["rejected"]:
            f.write(f"\n- บรรทัด {c['line']} ไม่รับการแก้ ({c['reason']})\n  - เดิม: {c['before']}\n  - ที่เสนอ: {c['suggested']}\n")
    res["log"] = os.path.relpath(log, S.workspace_dir)
    return res


# ------------------------------------------------------------------ tools
async def proofread_thai(path: str, dry_run: bool = False) -> dict:
    """ตรวจและแก้การสะกดภาษาไทยของไฟล์ (ค่าเริ่มต้น .md) ใน workspace แก้เฉพาะการสะกด ไม่เปลี่ยนเนื้อหา ตัวเลข รหัส และ URL

    path: path สัมพัทธ์จากราก workspace เช่น "report.md" หรือ "project-a/chapter1.md"
    dry_run: true = ตรวจอย่างเดียว ไม่เขียนไฟล์ (คืนรายการที่จะแก้)
    คืนค่า: ok, lines_changed, lines_rejected, suspect_before, suspect_after, errors, backup, log
    ไฟล์ยาวใช้เวลาหลายนาที เพราะส่งให้ LLM ตรวจทีละช่วง
    """
    try:
        return await asyncio.to_thread(_file_job, path, dry_run)
    except (ValueError, FileNotFoundError, OSError) as e:
        return {"ok": False, "error": str(e)}


async def proofread_text(text: str, title: str = "") -> dict:
    """ตรวจและแก้การสะกดภาษาไทยของข้อความ แล้วคืนข้อความที่แก้แล้ว (ไม่อ่าน/เขียนไฟล์)

    text: ข้อความ (Markdown ได้) · title: ชื่อเรื่องใช้เป็นบริบท (ไม่บังคับ)
    คืนค่า: ok, text, lines_changed, lines_rejected, changes, rejected, errors
    """
    lines = ((f"# {title}\n" if title else "") + (text or "")).split("\n")
    r = await asyncio.to_thread(proofread_lines, lines, S)
    out = r["lines"][1:] if title else r["lines"]
    return {"ok": not r["errors"], "model": S.llm_model, "text": "\n".join(out),
            "lines_changed": len(r["changes"]), "lines_rejected": len(r["rejected"]),
            "changes": r["changes"][:60], "rejected": r["rejected"][:60], "errors": r["errors"]}


mcp.add_tool(proofread_thai)
mcp.add_tool(proofread_text)


# ------------------------------------------------------------------ http app
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal")


def health_report() -> dict:
    """ok = the LLM settings look usable. problems explains every reason it is not (or may not be)."""
    state = key_state(S.llm_api_key)
    local = any(h in S.llm_base_url for h in _LOCAL_HOSTS)
    mounted = os.path.isdir(S.workspace_dir)
    problems = []
    if state == "placeholder":
        problems.append("LLM_API_KEY is still the example value from .env.example - put your real key in .env")
    elif state == "empty" and not local:
        problems.append("LLM_API_KEY is empty - fine only if LLM_BASE_URL needs no key")
    if not mounted:
        problems.append("the workspace is not mounted - proofread_thai cannot reach any file")
    return {"ok": state == "set" or (state == "empty" and local),
            "model": S.llm_model, "base_url": S.llm_base_url,
            "key_configured": state == "set", "workspace": S.workspace_dir, "workspace_mounted": mounted,
            "auth": bool(S.auth_token), "problems": problems}


async def health(_: Request) -> JSONResponse:
    return JSONResponse(health_report())


class BearerAuth:
    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.token and scope["path"].startswith("/mcp"):
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


app = BearerAuth(Starlette(routes=[Route("/health", health), Mount("/", app=mcp_app)], lifespan=lifespan), S.auth_token)

if __name__ == "__main__":
    uvicorn.run(app, host=S.host, port=S.port, log_level="info")
