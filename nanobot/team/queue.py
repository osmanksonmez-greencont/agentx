"""Durable queue backends for multi-agent task routing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


QUEUE_TASK_COMMANDS = "team.task.commands"
QUEUE_TASK_EVENTS = "team.task.events"
QUEUE_AGENT_EVENTS = "team.agent.events"


def role_task_queue(role: str) -> str:
    """Queue name for role-specific task commands."""
    return f"{QUEUE_TASK_COMMANDS}.{role}"


@dataclass(slots=True)
class QueueItem:
    """A claimed queue message."""

    message_id: int
    queue_name: str
    payload: dict[str, Any]
    attempts: int


class BaseTeamQueue:
    """Interface for task/event queue operations."""

    async def publish(self, queue_name: str, payload: dict[str, Any]) -> int:
        raise NotImplementedError

    async def claim(self, queue_name: str, consumer: str, visibility_timeout_s: int = 60) -> QueueItem | None:
        raise NotImplementedError

    async def ack(self, message_id: int) -> None:
        raise NotImplementedError

    async def fail(self, message_id: int, error: str, retry_delay_s: int = 10, max_attempts: int = 3) -> None:
        raise NotImplementedError


class InMemoryTeamQueue(BaseTeamQueue):
    """In-memory queue, mainly for tests/local quick runs."""

    def __init__(self) -> None:
        self._q: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def publish(self, queue_name: str, payload: dict[str, Any]) -> int:
        async with self._lock:
            mid = self._next_id
            self._next_id += 1
        body = dict(payload)
        body["_messageId"] = mid
        queue = self._q.setdefault(queue_name, asyncio.Queue())
        await queue.put(body)
        return mid

    async def claim(self, queue_name: str, consumer: str, visibility_timeout_s: int = 60) -> QueueItem | None:
        queue = self._q.setdefault(queue_name, asyncio.Queue())
        try:
            payload = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None
        return QueueItem(
            message_id=int(payload.get("_messageId", 0)),
            queue_name=queue_name,
            payload=payload,
            attempts=int(payload.get("_attempts", 0)),
        )

    async def ack(self, message_id: int) -> None:
        return None

    async def fail(self, message_id: int, error: str, retry_delay_s: int = 10, max_attempts: int = 3) -> None:
        return None


class SQLiteTeamQueue(BaseTeamQueue):
    """SQLite-backed durable queue with visibility timeout semantics."""

    def __init__(self, db_path: Path):
        self.db_path = db_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    available_at TEXT NOT NULL,
                    locked_by TEXT,
                    locked_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_dead_letters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    error TEXT,
                    failed_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_queue_ready ON queue_messages(queue_name, available_at, locked_until)"
            )
            self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat()

    async def publish(self, queue_name: str, payload: dict[str, Any]) -> int:
        return await asyncio.to_thread(self._publish_sync, queue_name, payload)

    def _publish_sync(self, queue_name: str, payload: dict[str, Any]) -> int:
        now = self._now()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO queue_messages(queue_name, payload_json, attempts, available_at, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?, ?)
                """,
                (queue_name, json.dumps(payload, ensure_ascii=False), now, now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    async def claim(self, queue_name: str, consumer: str, visibility_timeout_s: int = 60) -> QueueItem | None:
        return await asyncio.to_thread(self._claim_sync, queue_name, consumer, visibility_timeout_s)

    def _claim_sync(self, queue_name: str, consumer: str, visibility_timeout_s: int) -> QueueItem | None:
        now = datetime.utcnow()
        now_s = now.isoformat()
        lock_until = (now + timedelta(seconds=visibility_timeout_s)).isoformat()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, payload_json, attempts
                FROM queue_messages
                WHERE queue_name = ?
                  AND available_at <= ?
                  AND (locked_until IS NULL OR locked_until < ?)
                ORDER BY id ASC
                LIMIT 1
                """,
                (queue_name, now_s, now_s),
            ).fetchone()
            if not row:
                return None

            self._conn.execute(
                """
                UPDATE queue_messages
                SET locked_by = ?, locked_until = ?, updated_at = ?
                WHERE id = ?
                """,
                (consumer, lock_until, now_s, row["id"]),
            )
            self._conn.commit()

            payload = json.loads(row["payload_json"])
            return QueueItem(
                message_id=int(row["id"]),
                queue_name=queue_name,
                payload=payload,
                attempts=int(row["attempts"]),
            )

    async def ack(self, message_id: int) -> None:
        await asyncio.to_thread(self._ack_sync, message_id)

    def _ack_sync(self, message_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM queue_messages WHERE id = ?", (message_id,))
            self._conn.commit()

    async def fail(self, message_id: int, error: str, retry_delay_s: int = 10, max_attempts: int = 3) -> None:
        await asyncio.to_thread(self._fail_sync, message_id, error, retry_delay_s, max_attempts)

    def _fail_sync(self, message_id: int, error: str, retry_delay_s: int, max_attempts: int) -> None:
        now = datetime.utcnow()
        now_s = now.isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts FROM queue_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if not row:
                return

            attempts = int(row["attempts"]) + 1
            if attempts >= max_attempts:
                failed_row = self._conn.execute(
                    "SELECT queue_name, payload_json FROM queue_messages WHERE id = ?",
                    (message_id,),
                ).fetchone()
                if failed_row:
                    self._conn.execute(
                        """
                        INSERT INTO queue_dead_letters(queue_name, payload_json, attempts, error, failed_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (failed_row["queue_name"], failed_row["payload_json"], attempts, error, now_s),
                    )
                self._conn.execute("DELETE FROM queue_messages WHERE id = ?", (message_id,))
            else:
                available_at = (now + timedelta(seconds=retry_delay_s)).isoformat()
                self._conn.execute(
                    """
                    UPDATE queue_messages
                    SET attempts = ?, error = ?, available_at = ?, locked_by = NULL, locked_until = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (attempts, error, available_at, now_s, message_id),
                )
            self._conn.commit()
