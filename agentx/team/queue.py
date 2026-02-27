"""Durable queue backends for multi-agent task routing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from redis.asyncio import Redis


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
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA synchronous = NORMAL")
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


class RedisTeamQueue(BaseTeamQueue):
    """Redis-backed durable queue with visibility timeout semantics."""

    _CLAIM_LUA = """
    local pending_key = KEYS[1]
    local inflight_key = KEYS[2]
    local now = tonumber(ARGV[1])
    local lock_until = tonumber(ARGV[2])

    local expired = redis.call('ZRANGEBYSCORE', inflight_key, '-inf', now, 'LIMIT', 0, 50)
    for _, message_id in ipairs(expired) do
        redis.call('ZREM', inflight_key, message_id)
        redis.call('ZADD', pending_key, now, message_id)
    end

    local ready = redis.call('ZRANGEBYSCORE', pending_key, '-inf', now, 'LIMIT', 0, 1)
    if #ready == 0 then
      return nil
    end

    local message_id = ready[1]
    if redis.call('ZREM', pending_key, message_id) == 0 then
      return nil
    end

    redis.call('ZADD', inflight_key, lock_until, message_id)
    return message_id
    """

    def __init__(self, redis_url: str, key_prefix: str = "agentx:team"):
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._prefix = key_prefix.rstrip(":") or "agentx:team"
        self._id_key = f"{self._prefix}:sequence"
        self._dlq_key = f"{self._prefix}:dead_letters"

    def _pending_key(self, queue_name: str) -> str:
        return f"{self._prefix}:queue:{queue_name}:pending"

    def _inflight_key(self, queue_name: str) -> str:
        return f"{self._prefix}:queue:{queue_name}:inflight"

    def _message_key(self, message_id: int) -> str:
        return f"{self._prefix}:message:{message_id}"

    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().isoformat()

    async def publish(self, queue_name: str, payload: dict[str, Any]) -> int:
        message_id = int(await self._redis.incr(self._id_key))
        now_s = time.time()
        now_iso = self._now_iso()

        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(
            self._message_key(message_id),
            mapping={
                "queue_name": queue_name,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "attempts": "0",
                "error": "",
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )
        pipe.zadd(self._pending_key(queue_name), {str(message_id): now_s})
        await pipe.execute()
        return message_id

    async def claim(self, queue_name: str, consumer: str, visibility_timeout_s: int = 60) -> QueueItem | None:
        del consumer  # Visibility lock is tracked via sorted-set scores in Redis.

        now_s = time.time()
        lock_until = now_s + visibility_timeout_s
        message_id = await self._redis.eval(
            self._CLAIM_LUA,
            2,
            self._pending_key(queue_name),
            self._inflight_key(queue_name),
            str(now_s),
            str(lock_until),
        )
        if message_id is None:
            return None

        mid = int(message_id)
        raw = await self._redis.hgetall(self._message_key(mid))
        if not raw:
            await self._redis.zrem(self._inflight_key(queue_name), str(mid))
            return None

        payload = json.loads(raw.get("payload_json", "{}"))
        return QueueItem(
            message_id=mid,
            queue_name=queue_name,
            payload=payload,
            attempts=int(raw.get("attempts", "0")),
        )

    async def ack(self, message_id: int) -> None:
        message_key = self._message_key(message_id)
        queue_name = await self._redis.hget(message_key, "queue_name")
        if not queue_name:
            return

        pipe = self._redis.pipeline(transaction=True)
        pipe.zrem(self._inflight_key(queue_name), str(message_id))
        pipe.delete(message_key)
        await pipe.execute()

    async def fail(self, message_id: int, error: str, retry_delay_s: int = 10, max_attempts: int = 3) -> None:
        message_key = self._message_key(message_id)
        raw = await self._redis.hgetall(message_key)
        if not raw:
            return

        queue_name = raw.get("queue_name", "")
        attempts = int(raw.get("attempts", "0")) + 1
        now_iso = self._now_iso()

        pipe = self._redis.pipeline(transaction=True)
        if attempts >= max_attempts:
            dlq_entry = {
                "messageId": message_id,
                "queueName": queue_name,
                "payload": json.loads(raw.get("payload_json", "{}")),
                "attempts": attempts,
                "error": error,
                "failedAt": now_iso,
            }
            pipe.zrem(self._inflight_key(queue_name), str(message_id))
            pipe.delete(message_key)
            pipe.lpush(self._dlq_key, json.dumps(dlq_entry, ensure_ascii=False))
            pipe.ltrim(self._dlq_key, 0, 999)
        else:
            available_at_s = time.time() + retry_delay_s
            pipe.hset(
                message_key,
                mapping={
                    "attempts": str(attempts),
                    "error": error,
                    "updated_at": now_iso,
                },
            )
            pipe.zrem(self._inflight_key(queue_name), str(message_id))
            pipe.zadd(self._pending_key(queue_name), {str(message_id): available_at_s})
        await pipe.execute()
