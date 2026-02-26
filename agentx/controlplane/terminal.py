"""Simple terminal session manager for control-plane API."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any


@dataclass
class TerminalSession:
    id: str
    command: str
    cwd: str
    created_at: str
    proc: subprocess.Popen
    output: deque[str] = field(default_factory=lambda: deque(maxlen=2000))


class TerminalManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    def create(self, command: str = "bash") -> dict[str, Any]:
        sid = uuid.uuid4().hex[:12]
        proc = subprocess.Popen(
            command,
            cwd=str(self.workspace),
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        session = TerminalSession(
            id=sid,
            command=command,
            cwd=str(self.workspace),
            created_at=datetime.utcnow().isoformat(),
            proc=proc,
        )
        with self._lock:
            self._sessions[sid] = session

        t = threading.Thread(target=self._pump_output, args=(session,), daemon=True)
        t.start()
        return self.get(sid) or {}

    def _pump_output(self, session: TerminalSession) -> None:
        if not session.proc.stdout:
            return
        for line in session.proc.stdout:
            session.output.append(line.rstrip("\n"))
        session.output.append("[process exited]")

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(self._sessions)
        return [self.get(sid) for sid in ids if self.get(sid)]

    def get(self, sid: str) -> dict[str, Any] | None:
        with self._lock:
            s = self._sessions.get(sid)
        if not s:
            return None
        return {
            "id": s.id,
            "command": s.command,
            "cwd": s.cwd,
            "createdAt": s.created_at,
            "running": s.proc.poll() is None,
        }

    def write(self, sid: str, text: str) -> bool:
        with self._lock:
            s = self._sessions.get(sid)
        if not s or not s.proc.stdin or s.proc.poll() is not None:
            return False
        s.proc.stdin.write(text)
        s.proc.stdin.flush()
        return True

    def read(self, sid: str, limit: int = 200) -> list[str]:
        with self._lock:
            s = self._sessions.get(sid)
        if not s:
            return []
        lines = list(s.output)
        return lines[-max(1, limit):]

    def stop(self, sid: str) -> bool:
        with self._lock:
            s = self._sessions.get(sid)
        if not s:
            return False
        if s.proc.poll() is None:
            s.proc.terminate()
        return True
