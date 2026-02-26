"""Persistent store for projects, tasks, events, and board state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from nanobot.team.types import TeamEvent, TeamTask

_DEFAULT_COLUMNS = ["Backlog", "Ready", "In Progress", "Review", "Done", "Blocked"]


def _now() -> str:
    return datetime.utcnow().isoformat()


def _status_to_column(status: str) -> str:
    mapping = {
        "backlog": "Backlog",
        "ready": "Ready",
        "in_progress": "In Progress",
        "review": "Review",
        "done": "Done",
        "failed": "Blocked",
        "blocked": "Blocked",
    }
    return mapping.get(status, "Backlog")


@dataclass(slots=True)
class TeamStore:
    """SQLite-backed store for control-plane state."""

    db_path: Path
    _lock: threading.Lock = field(init=False, repr=False)
    _conn: sqlite3.Connection = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path = self.db_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS team_projects (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    assignee_role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    parent_task_id TEXT,
                    metadata_json TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    task_id TEXT,
                    assignee_role TEXT,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_board_columns (
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    ord_idx INTEGER NOT NULL,
                    PRIMARY KEY(project_id, name)
                );

                CREATE TABLE IF NOT EXISTS team_board_cards (
                    task_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    column_name TEXT NOT NULL,
                    ord_idx INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    task_id TEXT,
                    agent_name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_agents (
                    name TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_task_id TEXT,
                    project_id TEXT,
                    heartbeat_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def list_projects(self) -> list[dict[str, Any]]:
        """List all projects with their stats."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT 
                    p.id,
                    p.created_at,
                    p.updated_at,
                    COUNT(DISTINCT t.id) as task_count,
                    COUNT(DISTINCT CASE WHEN t.status = 'done' THEN t.id END) as done_count,
                    COUNT(DISTINCT e.id) as event_count
                FROM team_projects p
                LEFT JOIN team_tasks t ON t.project_id = p.id
                LEFT JOIN team_events e ON e.project_id = p.id
                GROUP BY p.id
                ORDER BY p.updated_at DESC
                """
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({
                "id": r["id"],
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
                "taskCount": r["task_count"],
                "doneCount": r["done_count"],
                "eventCount": r["event_count"],
            })
        return out

    def ensure_project(self, project_id: str) -> None:
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO team_projects(id, created_at, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (project_id, now, now),
            )
            # Create default columns if missing.
            for idx, name in enumerate(_DEFAULT_COLUMNS):
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO team_board_columns(project_id, name, ord_idx)
                    VALUES(?, ?, ?)
                    """,
                    (project_id, name, idx),
                )
            self._conn.commit()

    def upsert_task(self, task: TeamTask) -> None:
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO team_tasks(
                    id, project_id, title, prompt, assignee_role, status,
                    parent_task_id, metadata_json, result, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    prompt = excluded.prompt,
                    assignee_role = excluded.assignee_role,
                    status = excluded.status,
                    parent_task_id = excluded.parent_task_id,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    task.id,
                    task.project_id,
                    task.title,
                    task.prompt,
                    task.assignee_role,
                    task.status,
                    task.parent_task_id,
                    json.dumps(task.metadata, ensure_ascii=False),
                    task.created_at,
                    now,
                ),
            )
            self._upsert_board_card(task_id=task.id, project_id=task.project_id, status=task.status)
            self._conn.commit()

    def set_task_status(
        self,
        task_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        now = _now()
        with self._lock:
            row = self._conn.execute(
                "SELECT project_id FROM team_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return

            self._conn.execute(
                """
                UPDATE team_tasks
                SET status = ?, result = COALESCE(?, result), error = COALESCE(?, error), updated_at = ?
                WHERE id = ?
                """,
                (status, result, error, now, task_id),
            )
            self._upsert_board_card(task_id=task_id, project_id=row["project_id"], status=status)
            self._conn.commit()

    def append_event(self, event: TeamEvent) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO team_events(project_id, task_id, assignee_role, kind, message, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.project_id,
                    event.task_id,
                    event.assignee_role,
                    event.kind,
                    event.message,
                    json.dumps(event.metadata, ensure_ascii=False),
                    event.created_at,
                ),
            )
            self._conn.commit()

    def list_tasks(self, project_id: str, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    """
                    SELECT * FROM team_tasks
                    WHERE project_id = ? AND status = ?
                    ORDER BY updated_at DESC
                    """,
                    (project_id, status),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM team_tasks
                    WHERE project_id = ?
                    ORDER BY updated_at DESC
                    """,
                    (project_id,),
                ).fetchall()

        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "projectId": r["project_id"],
                    "title": r["title"],
                    "assigneeRole": r["assignee_role"],
                    "status": r["status"],
                    "result": r["result"],
                    "error": r["error"],
                    "updatedAt": r["updated_at"],
                }
            )
        return out

    def list_board(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            cols = self._conn.execute(
                """
                SELECT name FROM team_board_columns
                WHERE project_id = ?
                ORDER BY ord_idx ASC
                """,
                (project_id,),
            ).fetchall()
            cards = self._conn.execute(
                """
                SELECT c.column_name, c.ord_idx, t.id, t.title, t.assignee_role, t.status
                FROM team_board_cards c
                JOIN team_tasks t ON t.id = c.task_id
                WHERE c.project_id = ?
                ORDER BY c.column_name ASC, c.ord_idx ASC
                """,
                (project_id,),
            ).fetchall()

        board = {c["name"]: [] for c in cols}
        for r in cards:
            col = r["column_name"]
            board.setdefault(col, []).append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "assigneeRole": r["assignee_role"],
                    "status": r["status"],
                }
            )
        return board

    def list_events(self, project_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM team_events
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()

        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "projectId": r["project_id"],
                    "taskId": r["task_id"],
                    "assigneeRole": r["assignee_role"],
                    "kind": r["kind"],
                    "message": r["message"],
                    "metadata": json.loads(r["metadata_json"] or "{}"),
                    "createdAt": r["created_at"],
                }
            )
        return out

    def list_events_since(self, project_id: str, since_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM team_events
                WHERE project_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (project_id, since_id, limit),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "projectId": r["project_id"],
                    "taskId": r["task_id"],
                    "assigneeRole": r["assignee_role"],
                    "kind": r["kind"],
                    "message": r["message"],
                    "metadata": json.loads(r["metadata_json"] or "{}"),
                    "createdAt": r["created_at"],
                }
            )
        return out

    def upsert_agent(
        self,
        name: str,
        role: str,
        status: str,
        current_task_id: str | None = None,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO team_agents(name, role, status, current_task_id, project_id, heartbeat_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    role = excluded.role,
                    status = excluded.status,
                    current_task_id = excluded.current_task_id,
                    project_id = excluded.project_id,
                    heartbeat_at = excluded.heartbeat_at,
                    metadata_json = excluded.metadata_json
                """,
                (name, role, status, current_task_id, project_id, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            self._conn.commit()

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT name, role, status, current_task_id, project_id, heartbeat_at, metadata_json
                FROM team_agents
                ORDER BY name ASC
                """
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "name": r["name"],
                    "role": r["role"],
                    "status": r["status"],
                    "currentTaskId": r["current_task_id"],
                    "projectId": r["project_id"],
                    "heartbeatAt": r["heartbeat_at"],
                    "metadata": json.loads(r["metadata_json"] or "{}"),
                }
            )
        return out

    def record_usage(
        self,
        project_id: str,
        task_id: str | None,
        agent_name: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        total = max(0, int(prompt_tokens)) + max(0, int(completion_tokens))
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO team_usage(
                    project_id, task_id, agent_name, provider, model,
                    prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    task_id,
                    agent_name,
                    provider,
                    model,
                    int(prompt_tokens),
                    int(completion_tokens),
                    total,
                    float(estimated_cost_usd),
                    _now(),
                ),
            )
            self._conn.commit()

    def usage_summary(self, project_id: str | None = None) -> dict[str, Any]:
        query = """
            SELECT
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
            FROM team_usage
        """
        params: tuple[Any, ...] = ()
        if project_id:
            query += " WHERE project_id = ?"
            params = (project_id,)
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return {
            "projectId": project_id,
            "promptTokens": int(row["prompt_tokens"] if row else 0),
            "completionTokens": int(row["completion_tokens"] if row else 0),
            "totalTokens": int(row["total_tokens"] if row else 0),
            "estimatedCostUsd": float(row["estimated_cost_usd"] if row else 0.0),
        }

    def append_audit_log(self, actor: str, action: str, target: str, detail: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO team_audit_logs(actor, action, target, detail_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (actor, action, target, json.dumps(detail or {}, ensure_ascii=False), _now()),
            )
            self._conn.commit()

    def list_audit_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, actor, action, target, detail_json, created_at
                FROM team_audit_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "actor": r["actor"],
                    "action": r["action"],
                    "target": r["target"],
                    "detail": json.loads(r["detail_json"] or "{}"),
                    "createdAt": r["created_at"],
                }
            )
        return out

    def list_dead_letters(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, queue_name, payload_json, attempts, error, failed_at
                FROM queue_dead_letters
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "queueName": r["queue_name"],
                    "payload": json.loads(r["payload_json"] or "{}"),
                    "attempts": r["attempts"],
                    "error": r["error"],
                    "failedAt": r["failed_at"],
                }
            )
        return out

    def _upsert_board_card(self, task_id: str, project_id: str, status: str) -> None:
        column_name = _status_to_column(status)
        now = _now()
        row = self._conn.execute(
            "SELECT COALESCE(MAX(ord_idx), -1) + 1 as next_idx FROM team_board_cards WHERE project_id = ? AND column_name = ?",
            (project_id, column_name),
        ).fetchone()
        next_idx = int(row["next_idx"]) if row else 0
        self._conn.execute(
            """
            INSERT INTO team_board_cards(task_id, project_id, column_name, ord_idx, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                column_name = excluded.column_name,
                ord_idx = excluded.ord_idx,
                updated_at = excluded.updated_at
            """,
            (task_id, project_id, column_name, next_idx, now),
        )
