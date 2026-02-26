"""Task and event models for the multi-agent development team runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
import uuid

TaskStatus = Literal[
    "backlog",
    "ready",
    "in_progress",
    "review",
    "done",
    "failed",
    "blocked",
]

EventKind = Literal[
    "goal_submitted",
    "task_created",
    "task_started",
    "task_completed",
    "task_failed",
    "task_blocked",
]


@dataclass(slots=True)
class TeamTask:
    """A queued task assigned to a role/agent."""

    id: str
    title: str
    prompt: str
    project_id: str
    assignee_role: str
    status: TaskStatus = "backlog"
    parent_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @staticmethod
    def new(
        title: str,
        prompt: str,
        project_id: str,
        assignee_role: str,
        parent_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "TeamTask":
        return TeamTask(
            id=uuid.uuid4().hex[:10],
            title=title,
            prompt=prompt,
            project_id=project_id,
            assignee_role=assignee_role,
            parent_task_id=parent_task_id,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "prompt": self.prompt,
            "projectId": self.project_id,
            "assigneeRole": self.assignee_role,
            "status": self.status,
            "parentTaskId": self.parent_task_id,
            "metadata": self.metadata,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TeamTask":
        return TeamTask(
            id=data["id"],
            title=data["title"],
            prompt=data["prompt"],
            project_id=data["projectId"],
            assignee_role=data["assigneeRole"],
            status=data.get("status", "backlog"),
            parent_task_id=data.get("parentTaskId"),
            metadata=data.get("metadata", {}),
            created_at=data.get("createdAt", datetime.now().isoformat()),
            updated_at=data.get("updatedAt", datetime.now().isoformat()),
        )


@dataclass(slots=True)
class TeamEvent:
    """Lifecycle event emitted by orchestrator/workers."""

    kind: EventKind
    project_id: str
    task_id: str | None = None
    assignee_role: str | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "projectId": self.project_id,
            "taskId": self.task_id,
            "assigneeRole": self.assignee_role,
            "message": self.message,
            "metadata": self.metadata,
            "createdAt": self.created_at,
        }
