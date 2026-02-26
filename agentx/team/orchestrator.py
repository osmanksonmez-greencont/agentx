"""Main orchestrator for decomposing goals into role-assigned tasks."""

from __future__ import annotations

from dataclasses import dataclass

from agentx.team.queue import BaseTeamQueue, QUEUE_TASK_EVENTS, role_task_queue
from agentx.team.store import TeamStore
from agentx.team.types import TeamEvent, TeamTask


@dataclass(slots=True)
class TeamOrchestrator:
    """Creates and enqueues implementation tasks from a top-level goal."""

    queue: BaseTeamQueue
    store: TeamStore | None = None

    async def submit_goal(
        self,
        project_id: str,
        goal: str,
        source: str = "telegram",
        create_default_flow: bool = True,
    ) -> list[TeamTask]:
        tasks = self._default_plan(project_id, goal) if create_default_flow else []
        if self.store:
            self.store.ensure_project(project_id)

        goal_event = TeamEvent(
            kind="goal_submitted",
            project_id=project_id,
            message=goal,
            metadata={"source": source},
        )
        await self.queue.publish(QUEUE_TASK_EVENTS, goal_event.to_dict())
        if self.store:
            self.store.append_event(goal_event)

        for task in tasks:
            task.status = "ready"
            await self.queue.publish(role_task_queue(task.assignee_role), {"task": task.to_dict()})
            create_event = TeamEvent(
                kind="task_created",
                project_id=project_id,
                task_id=task.id,
                assignee_role=task.assignee_role,
                message=task.title,
            )
            await self.queue.publish(QUEUE_TASK_EVENTS, create_event.to_dict())
            if self.store:
                self.store.upsert_task(task)
                self.store.append_event(create_event)
        return tasks

    def _default_plan(self, project_id: str, goal: str) -> list[TeamTask]:
        """Default software-delivery pipeline; can be replaced by LLM planning later."""
        return [
            TeamTask.new(
                title="Define architecture and implementation plan",
                prompt=(
                    "Produce a concise architecture and a sequenced implementation plan for this goal.\n\n"
                    f"Goal:\n{goal}\n\n"
                    "Output expected: architecture summary, milestones, risks, and immediate next coding steps."
                ),
                project_id=project_id,
                assignee_role="architect",
            ),
            TeamTask.new(
                title="Implement backend foundations",
                prompt=(
                    "Implement backend/core service components required by the goal. "
                    "Create tests for critical paths and document assumptions.\n\n"
                    f"Goal:\n{goal}"
                ),
                project_id=project_id,
                assignee_role="backend",
            ),
            TeamTask.new(
                title="Implement frontend workflow",
                prompt=(
                    "Implement UI pages and flows required by the goal, with production-ready states and error handling.\n\n"
                    f"Goal:\n{goal}"
                ),
                project_id=project_id,
                assignee_role="frontend",
            ),
            TeamTask.new(
                title="Run QA validation and release checklist",
                prompt=(
                    "Run tests, verify expected behavior, identify regressions, and provide release readiness summary.\n\n"
                    f"Goal:\n{goal}"
                ),
                project_id=project_id,
                assignee_role="qa",
            ),
        ]
