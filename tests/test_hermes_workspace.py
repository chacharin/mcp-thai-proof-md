"""proofread_thai with no mounted folder: the files live in Hermes and are reached through its dashboard API.
A small fake dashboard (password login + cookie, /api/files/read, /upload, /mkdir) stands in for Hermes."""
import asyncio
import base64
import importlib
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import checked_lines

ROOT = "/opt/data/workspace"


class FakeDashboard:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.sessions: set[str] = set()
        self.logins = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, body, cookie=None):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                if cookie:
                    self.send_header("Set-Cookie", f"hermes_session_at={cookie}; Path=/")
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def _authed(self):
                cookie = self.headers.get("Cookie") or ""
                return any(f"hermes_session_at={s}" in cookie for s in outer.sessions)

            def do_POST(self):
                url = urllib.parse.urlparse(self.path)
                outer.calls.append(f"POST {url.path}")
                body = self._body()
                if url.path == "/auth/password-login":
                    if body.get("username") == "tester" and body.get("password") == "test-pass-not-real":
                        outer.logins += 1
                        token = f"t{outer.logins}"
                        outer.sessions.add(token)
                        return self._json(200, {"ok": True}, cookie=token)
                    return self._json(401, {"detail": "Invalid credentials"})
                if not self._authed():
                    return self._json(401, {"error": "unauthenticated"})
                if url.path == "/api/files/upload":
                    data = base64.b64decode(body["data_url"].split(",", 1)[1])
                    outer.files[body["path"]] = data
                    return self._json(200, {"ok": True})
                if url.path == "/api/files/mkdir":
                    return self._json(200, {"ok": True})
                return self._json(404, {"detail": "no route"})

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(url.query)
                outer.calls.append(f"GET {url.path}")
                if not self._authed():
                    return self._json(401, {"error": "unauthenticated"})
                path = (q.get("path") or [""])[0]
                if url.path == "/api/files":
                    return self._json(200, {"path": path, "entries": []})
                if url.path == "/api/files/read":
                    if path not in outer.files:
                        return self._json(404, {"detail": "File not found"})
                    enc = base64.b64encode(outer.files[path]).decode()
                    return self._json(200, {"path": path, "data_url": f"data:text/markdown;base64,{enc}"})
                return self._json(404, {"detail": "no route"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def dashboard(monkeypatch, tmp_path):
    d = FakeDashboard()
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "not-mounted"))      # no folder -> hermes mode
    monkeypatch.setenv("HERMES_DASHBOARD_URL", d.url)
    monkeypatch.setenv("HERMES_DASHBOARD_USER", "tester")
    monkeypatch.setenv("HERMES_DASHBOARD_PASSWORD", "test-pass-not-real")
    yield d
    d.httpd.shutdown()


def load_server():
    import app.server
    return importlib.reload(app.server)


def fix_typos(prompt: str) -> str:
    return "\n".join(ln.replace("ขบเคลอน", "ขับเคลื่อน") for ln in checked_lines(prompt))


def test_hermes_mode_is_chosen_without_a_folder(dashboard):
    server = load_server()
    h = server.health_report()
    assert h["workspace"] == {"mode": "hermes", "root": ROOT, "reachable": True}


def test_file_is_fixed_backed_up_and_logged_in_hermes(dashboard, fake_llm, monkeypatch):
    monkeypatch.setenv("PATH_PREFIXES", "/opt/data/workspace/")
    dashboard.files[f"{ROOT}/collection01/step3.md"] = "# ขั้นที่ 3\nปัจจัยขบเคลอนหลัก\n".encode()
    server = load_server()
    fake_llm(fix_typos)
    res = asyncio.run(server.proofread_thai("/opt/data/workspace/collection01/step3.md"))
    assert res["ok"] and res["lines_changed"] == 1
    assert dashboard.files[f"{ROOT}/collection01/step3.md"].decode() == "# ขั้นที่ 3\nปัจจัยขับเคลื่อนหลัก\n"
    backup = f"{ROOT}/{res['backup']}"
    assert res["backup"].startswith("collection01/backups/step3.md.bak-proof-")
    assert "ขบเคลอน" in dashboard.files[backup].decode()                        # the original is kept
    assert "ขับเคลื่อน" in dashboard.files[f"{ROOT}/collection01/notes/proofread-step3.md"].decode()


def test_dry_run_writes_nothing(dashboard, fake_llm):
    dashboard.files[f"{ROOT}/report.md"] = "ปัจจัยขบเคลอน".encode()
    server = load_server()
    fake_llm(fix_typos)
    res = asyncio.run(server.proofread_thai("report.md", dry_run=True))
    assert res["lines_changed"] == 1 and list(dashboard.files) == [f"{ROOT}/report.md"]


@pytest.mark.parametrize("path,error", [("../etc/passwd.md", "inside the workspace"),
                                        ("missing.md", "file not found"), ("notes.txt", "only .md")])
def test_bad_paths_are_refused(dashboard, path, error):
    server = load_server()
    res = asyncio.run(server.proofread_thai(path))
    assert res["ok"] is False and error in res["error"]
    assert not any(c.startswith("POST /api/files/upload") for c in dashboard.calls)


def test_wrong_password_is_explained(dashboard, monkeypatch):
    monkeypatch.setenv("HERMES_DASHBOARD_PASSWORD", "wrong")
    server = load_server()
    h = server.health_report()
    assert h["workspace"]["reachable"] is False and any("HERMES_DASHBOARD" in p for p in h["problems"])
    res = asyncio.run(server.proofread_thai("report.md"))
    assert res["ok"] is False and "refused" in res["error"]


def test_expired_session_signs_in_again(dashboard, fake_llm):
    dashboard.files[f"{ROOT}/report.md"] = "ปัจจัยขบเคลอน".encode()
    server = load_server()
    assert server.WS.reachable() and dashboard.logins == 1
    dashboard.sessions.clear()                                                 # the dashboard forgets the session
    fake_llm(fix_typos)
    res = asyncio.run(server.proofread_thai("report.md"))
    assert res["ok"] and dashboard.logins == 2
