"""The workspace whose files proofread_thai fixes, reached one of two ways:

  local   WORKSPACE_DIR is a mounted folder (this server runs on the same host as the agent)
  hermes  no folder, but a Hermes dashboard login is set: files are read and written over HTTP through the
          Hermes dashboard files API (GET /api/files/read, POST /api/files/upload, /api/files/mkdir),
          so this server can run on another host, like any MCP server that only talks HTTP

Every path here is relative to the workspace root ("project-a/report.md"); callers never see the mode.
"""
from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import posixpath
import urllib.error
import urllib.parse
import urllib.request

from app.config import Settings


class WorkspaceError(Exception):
    pass


def safe_relative(path: str) -> str:
    """A relative POSIX path that cannot leave the workspace root."""
    p = posixpath.normpath((path or "").replace("\\", "/").lstrip("/"))
    if p in ("", ".") or p == ".." or p.startswith("../"):
        raise ValueError("path must be inside the workspace")
    return p


class LocalWorkspace:
    mode = "local"

    def __init__(self, root: str):
        self.root = root.rstrip("/") or "/"

    def _real(self, rel: str) -> str:
        root = os.path.realpath(self.root)
        real = os.path.realpath(os.path.join(root, rel))
        if not real.startswith(root + os.sep):     # also catches a symlink that points outside
            raise ValueError("path must be inside the workspace")
        return real

    def reachable(self) -> bool:
        return os.path.isdir(self.root)

    def is_file(self, rel: str) -> bool:
        return os.path.isfile(self._real(rel))

    def read(self, rel: str) -> str:
        with open(self._real(rel), encoding="utf-8") as f:
            return f.read()

    def write(self, rel: str, text: str) -> None:
        real = self._real(rel)
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, "w", encoding="utf-8") as f:
            f.write(text)

    def append(self, rel: str, text: str) -> None:
        real = self._real(rel)
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, "a", encoding="utf-8") as f:
            f.write(text)


class HermesWorkspace:
    """The agent's workspace inside Hermes, through its dashboard (needs the dashboard login)."""
    mode = "hermes"

    def __init__(self, url: str, user: str, password: str, root: str, timeout: float = 30):
        self.url, self.user, self.password = url.rstrip("/"), user, password
        self.root = root.rstrip("/")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._signed_in = False

    def _abs(self, rel: str) -> str:
        return f"{self.root}/{safe_relative(rel)}"

    def _send(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        url = self.url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        with self._opener.open(req, timeout=self.timeout) as r:
            raw = r.read()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _login(self) -> None:
        try:
            self._send("POST", "/auth/password-login",
                       body={"provider": "basic", "username": self.user, "password": self.password, "next": "/"})
        except urllib.error.HTTPError as e:
            raise WorkspaceError("the Hermes dashboard refused HERMES_DASHBOARD_USER / HERMES_DASHBOARD_PASSWORD"
                                 if e.code == 401 else f"Hermes dashboard login failed: HTTP {e.code}") from e
        self._signed_in = True

    def _call(self, method: str, path: str, **kw):
        """One dashboard call; signs in first, and once more if the session has expired."""
        try:
            for attempt in (1, 2):
                if not self._signed_in or attempt == 2:
                    self._login()
                try:
                    return self._send(method, path, **kw)
                except urllib.error.HTTPError as e:
                    if e.code != 401 or attempt == 2:
                        raise
                    self._signed_in = False
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):   # 400 = the path is a folder, not a file
                raise FileNotFoundError(path) from e
            raise WorkspaceError(f"Hermes dashboard {method} {path}: HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise WorkspaceError(f"cannot reach the Hermes dashboard at {self.url} ({type(e).__name__})") from e

    def reachable(self) -> bool:
        try:
            self._call("GET", "/api/files", params={"path": self.root})
            return True
        except (WorkspaceError, FileNotFoundError):
            return False

    def read(self, rel: str) -> str:
        d = self._call("GET", "/api/files/read", params={"path": self._abs(rel)})
        data_url = d.get("data_url") or ""
        return base64.b64decode(data_url.split(",", 1)[1]).decode("utf-8") if "," in data_url else ""

    def is_file(self, rel: str) -> bool:
        try:
            self._call("GET", "/api/files/read", params={"path": self._abs(rel)})
            return True
        except FileNotFoundError:
            return False

    def write(self, rel: str, text: str) -> None:
        data_url = "data:text/plain;base64," + base64.b64encode(text.encode("utf-8")).decode("ascii")
        self._call("POST", "/api/files/upload", body={"path": self._abs(rel), "data_url": data_url, "overwrite": True})

    def append(self, rel: str, text: str) -> None:
        try:
            current = self.read(rel)
        except FileNotFoundError:
            current = ""
        self.write(rel, current + text)


def open_workspace(s: Settings):
    """local when WORKSPACE_DIR is a folder here; hermes when the dashboard login is set; else None."""
    if os.path.isdir(s.workspace_dir):
        return LocalWorkspace(s.workspace_dir)
    if s.hermes_dashboard_url and s.hermes_dashboard_user and s.hermes_dashboard_password:
        return HermesWorkspace(s.hermes_dashboard_url, s.hermes_dashboard_user, s.hermes_dashboard_password,
                               s.hermes_workspace)
    return None
