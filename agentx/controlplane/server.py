"""HTTP control-plane API and management panel server."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
from urllib.parse import parse_qs, urlparse

from agentx.config.loader import get_config_path, load_config, save_config, get_data_dir
from agentx.config.schema import Config
from agentx.team.runtime import TeamRuntime
from agentx.team.store import TeamStore
from agentx.controlplane.terminal import TerminalManager


_ROLE_ORDER = {"viewer": 1, "operator": 2, "admin": 3}


def _json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _text(handler: BaseHTTPRequestHandler, body: str, status: int = 200, content_type: str = "text/plain") -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", f"{content_type}; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _load_jobs() -> list[dict]:
    path = get_data_dir() / "cron" / "jobs.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("jobs", [])
    except Exception:
        return []


def _redact_config(cfg: dict) -> dict:
    out = json.loads(json.dumps(cfg))
    try:
        providers = out.get("providers", {})
        for p in providers.values():
            if isinstance(p, dict) and p.get("apiKey"):
                p["apiKey"] = "***"
        channels = out.get("channels", {})
        for c in channels.values():
            if isinstance(c, dict):
                for k in ("token", "secret", "appSecret", "password", "clawToken"):
                    if k in c and c[k]:
                        c[k] = "***"
    except Exception:
        pass
    return out


def _restore_secret_placeholders(new_cfg: dict, old_cfg: dict) -> dict:
    """If UI posts redacted placeholders, restore previous secrets."""
    out = json.loads(json.dumps(new_cfg))
    providers_new = out.get("providers", {})
    providers_old = old_cfg.get("providers", {})
    for name, pv in providers_new.items():
        if not isinstance(pv, dict):
            continue
        if pv.get("apiKey") == "***":
            old = providers_old.get(name, {})
            if isinstance(old, dict):
                pv["apiKey"] = old.get("apiKey", "")

    channels_new = out.get("channels", {})
    channels_old = old_cfg.get("channels", {})
    for name, cv in channels_new.items():
        if not isinstance(cv, dict):
            continue
        old = channels_old.get(name, {}) if isinstance(channels_old.get(name, {}), dict) else {}
        for k in ("token", "secret", "appSecret", "password", "clawToken"):
            if cv.get(k) == "***":
                cv[k] = old.get(k, "")
    return out


@dataclass
class ControlPlaneContext:
    store: TeamStore
    terminal: TerminalManager
    users: dict[str, dict[str, str]]


class ControlPlaneHandler(BaseHTTPRequestHandler):
    ctx: ControlPlaneContext

    def _body_json(self) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if size <= 0:
            return {}
        raw = self.rfile.read(size).decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def _auth_user(self) -> dict[str, str] | None:
        if not self.ctx.users:
            return {"name": "anonymous", "role": "admin"}

        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        token = self.headers.get("X-API-Key", "")
        authz = self.headers.get("Authorization", "")
        if authz.lower().startswith("bearer "):
            token = authz.split(" ", 1)[1].strip()
        if not token:
            token = (query.get("token") or [""])[0]
        if not token:
            return None
        return self.ctx.users.get(token)

    def _require_role(self, role: str) -> dict[str, str] | None:
        user = self._auth_user()
        if not user:
            _json(self, {"error": "Unauthorized"}, status=401)
            return None
        if _ROLE_ORDER.get(user.get("role", "viewer"), 0) < _ROLE_ORDER.get(role, 99):
            _json(self, {"error": "Forbidden", "requiredRole": role}, status=403)
            return None
        return user

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/health":
            return _json(self, {"ok": True, "service": "control-plane"})

        if path.startswith("/api/"):
            if not self._require_role("viewer"):
                return

        if path == "/api/me":
            user = self._auth_user() or {"name": "unknown", "role": "viewer"}
            return _json(self, {"user": user})

        if path == "/api/projects":
            return _json(self, {"projects": self.ctx.store.list_projects()})

        if path == "/api/agents":
            return _json(self, {"agents": self.ctx.store.list_agents()})

        if path == "/api/audit":
            limit = int((query.get("limit") or ["50"])[0])
            return _json(self, {"logs": self.ctx.store.list_audit_logs(limit=limit)})

        if path == "/api/queue/dlq":
            limit = int((query.get("limit") or ["50"])[0])
            return _json(self, {"deadLetters": self.ctx.store.list_dead_letters(limit=limit)})

        if path == "/api/schedules":
            return _json(self, {"jobs": _load_jobs()})

        if path == "/api/config":
            cfg = load_config().model_dump(by_alias=True)
            return _json(self, _redact_config(cfg))

        if path == "/api/usage":
            project_id = (query.get("projectId") or [""])[0] or None
            return _json(self, self.ctx.store.usage_summary(project_id=project_id))

        if path == "/api/credits":
            # OpenRouter credits endpoint
            import os
            import urllib.request
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if not api_key:
                return _json(self, {"error": "OPENROUTER_API_KEY not configured"})
            try:
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/credits",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    return _json(self, {
                        "totalCredits": data.get("data", {}).get("total_credits", 0),
                        "totalUsage": data.get("data", {}).get("total_usage", 0),
                        "remainingCredits": data.get("data", {}).get("total_credits", 0) - data.get("data", {}).get("total_usage", 0)
                    })
            except Exception as e:
                return _json(self, {"error": str(e)})

        if path.startswith("/api/terminal/sessions"):
            parts = [p for p in path.split("/") if p]
            if len(parts) == 3:  # /api/terminal/sessions
                return _json(self, {"sessions": self.ctx.terminal.list()})
            if len(parts) >= 5 and parts[4] == "read":
                sid = parts[3]
                limit = int((query.get("limit") or ["200"])[0])
                return _json(self, {"lines": self.ctx.terminal.read(sid, limit=limit)})

        if path.startswith("/api/projects/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 4:
                project_id = parts[2]
                tail = parts[3]
                if len(parts) >= 5 and tail == "events" and parts[4] == "stream":
                    return self._stream_events(project_id=project_id, since_id=int((query.get("sinceId") or ["0"])[0]))
                if tail == "tasks":
                    status = (query.get("status") or [""])[0] or None
                    return _json(self, {"tasks": self.ctx.store.list_tasks(project_id, status=status)})
                if tail == "board":
                    return _json(self, self.ctx.store.list_board(project_id))
                if tail in {"events", "activity"}:
                    limit = int((query.get("limit") or ["30"])[0])
                    return _json(self, {"events": self.ctx.store.list_events(project_id, limit=limit)})

        if path == "/panel" or path == "/panel/":
            return _text(self, (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8"), content_type="text/html")
        if path == "/panel/style.css":
            return _text(self, (Path(__file__).parent / "static" / "style.css").read_text(encoding="utf-8"), content_type="text/css")
        if path == "/panel/app.js":
            return _text(self, (Path(__file__).parent / "static" / "app.js").read_text(encoding="utf-8"), content_type="application/javascript")

        return _json(self, {"error": "Not found"}, status=404)

    def _stream_events(self, project_id: str, since_id: int = 0) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_id = since_id
        try:
            while True:
                events = self.ctx.store.list_events_since(project_id=project_id, since_id=last_id, limit=200)
                for ev in events:
                    last_id = max(last_id, int(ev.get("id", last_id)))
                    payload = json.dumps(ev, ensure_ascii=False)
                    self.wfile.write(f"id: {last_id}\n".encode("utf-8"))
                    self.wfile.write(b"event: team_event\n")
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                if not events:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/config":
            user = self._require_role("admin")
            if not user:
                return
            body = self._body_json()
            try:
                old = load_config().model_dump(by_alias=True)
                merged = _restore_secret_placeholders(body, old)
                cfg = Config.model_validate(merged)
                save_config(cfg)
                self.ctx.store.append_audit_log(user["name"], "config_save", "config", {"ok": True})
                return _json(self, {"ok": True, "message": "config saved"})
            except Exception as e:
                return _json(self, {"ok": False, "error": str(e)}, status=400)

        if path == "/api/terminal/sessions":
            user = self._require_role("operator")
            if not user:
                return
            body = self._body_json()
            command = str(body.get("command") or "bash")
            session = self.ctx.terminal.create(command=command)
            self.ctx.store.append_audit_log(user["name"], "terminal_create", session.get("id", ""), {"command": command})
            return _json(self, session)

        if path.startswith("/api/terminal/sessions/"):
            user = self._require_role("operator")
            if not user:
                return
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 5 and parts[4] == "write":
                sid = parts[3]
                body = self._body_json()
                text = str(body.get("text") or "")
                ok = self.ctx.terminal.write(sid, text)
                self.ctx.store.append_audit_log(user["name"], "terminal_write", sid, {"ok": ok})
                return _json(self, {"ok": ok})
            if len(parts) >= 5 and parts[4] == "stop":
                sid = parts[3]
                ok = self.ctx.terminal.stop(sid)
                self.ctx.store.append_audit_log(user["name"], "terminal_stop", sid, {"ok": ok})
                return _json(self, {"ok": ok})

        return _json(self, {"error": "Not found"}, status=404)

    def log_message(self, format: str, *args):
        # keep stdout clean
        return


def serve_control_plane(host: str = "0.0.0.0", port: int = 28880) -> None:
    config = load_config()
    store = TeamRuntime.make_store(config)
    store.ensure_project("default")
    terminal = TerminalManager(config.workspace_path)
    users = {
        u.token: {"name": u.name or "user", "role": u.role}
        for u in config.control_plane.users
        if u.token
    }

    class _Handler(ControlPlaneHandler):
        ctx = ControlPlaneContext(store=store, terminal=terminal, users=users)

    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"Control plane listening on http://{host}:{port}/panel")
    httpd.serve_forever()
