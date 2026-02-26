"""Role-based worker runtime for executing team tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from loguru import logger

from agentx.agent.loop import AgentLoop
from agentx.config.schema import PricingConfig
from agentx.team.queue import BaseTeamQueue, QUEUE_TASK_EVENTS, role_task_queue
from agentx.team.store import TeamStore
from agentx.team.types import TeamEvent, TeamTask


@dataclass(slots=True)
class TeamWorker:
    """Consumes queued tasks for one role and executes them with an AgentLoop."""

    name: str
    role: str
    queue: BaseTeamQueue
    agent: AgentLoop
    store: TeamStore | None = None
    pricing: PricingConfig | None = None
    visibility_timeout_s: int = 120
    retry_delay_s: int = 10
    max_attempts: int = 3

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # Rough fallback estimate when provider usage is not exposed.
        return max(1, len(text) // 4)

    def _compute_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        if not self.pricing:
            return 0.0
        mcfg = self.pricing.models.get(model)
        input_rate = mcfg.input_per_million if mcfg else self.pricing.default_input_per_million
        output_rate = mcfg.output_per_million if mcfg else self.pricing.default_output_per_million
        return (prompt_tokens / 1_000_000.0) * input_rate + (completion_tokens / 1_000_000.0) * output_rate

    def _role_prompt_prefix(self, task: TeamTask) -> str:
        return (
            f"You are the '{self.role}' agent in a multi-agent software engineering team.\n"
            "Stay within role responsibilities, implement concrete output, and avoid unrelated work.\n"
            "When writing code, prefer incremental changes with verification commands.\n\n"
            f"Task title: {task.title}\n"
            f"Project ID: {task.project_id}\n\n"
            "Task details:\n"
            f"{task.prompt}"
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info("Team worker '{}' ({}) started", self.name, self.role)
        if self.store:
            self.store.upsert_agent(name=self.name, role=self.role, status="idle")
        while not stop_event.is_set():
            if self.store:
                self.store.upsert_agent(name=self.name, role=self.role, status="idle")
            item = await self.queue.claim(
                role_task_queue(self.role),
                consumer=self.name,
                visibility_timeout_s=self.visibility_timeout_s,
            )
            if not item:
                await asyncio.sleep(0.8)
                continue

            task_data = item.payload.get("task")
            if not isinstance(task_data, dict):
                await self.queue.ack(item.message_id)
                continue

            task = TeamTask.from_dict(task_data)
            start_event = TeamEvent(
                kind="task_started",
                project_id=task.project_id,
                task_id=task.id,
                assignee_role=self.role,
                message=task.title,
                metadata={"worker": self.name, "startedAt": datetime.utcnow().isoformat()},
            )
            if self.store:
                self.store.set_task_status(task.id, "in_progress")
                self.store.append_event(start_event)
                self.store.upsert_agent(
                    name=self.name,
                    role=self.role,
                    status="busy",
                    current_task_id=task.id,
                    project_id=task.project_id,
                )
            await self.queue.publish(QUEUE_TASK_EVENTS, start_event.to_dict())

            try:
                result = await self.agent.process_direct(
                    self._role_prompt_prefix(task),
                    session_key=f"team:{task.project_id}:{task.id}:{self.role}",
                    channel="system",
                    chat_id=f"team:{task.project_id}",
                )
                await self.queue.ack(item.message_id)
                final_status = "done" if self.role == "qa" else "review"
                done_event = TeamEvent(
                    kind="task_completed",
                    project_id=task.project_id,
                    task_id=task.id,
                    assignee_role=self.role,
                    message=task.title,
                    metadata={"worker": self.name, "result": result},
                )
                if self.store:
                    usage = self.agent.last_run_usage or {}
                    prompt_tokens = int(usage.get("prompt_tokens", 0)) or self._estimate_tokens(task.prompt)
                    completion_tokens = int(usage.get("completion_tokens", 0)) or self._estimate_tokens(result or "")
                    provider = self.agent.model.split("/", 1)[0] if "/" in self.agent.model else "custom"
                    self.store.set_task_status(task.id, final_status, result=result)
                    self.store.append_event(done_event)
                    self.store.record_usage(
                        project_id=task.project_id,
                        task_id=task.id,
                        agent_name=self.name,
                        provider=provider,
                        model=self.agent.model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        estimated_cost_usd=self._compute_cost(self.agent.model, prompt_tokens, completion_tokens),
                    )
                    self.store.upsert_agent(name=self.name, role=self.role, status="idle")
                await self.queue.publish(QUEUE_TASK_EVENTS, done_event.to_dict())
            except Exception as e:
                logger.exception("Worker '{}' failed task {}", self.name, task.id)
                await self.queue.fail(
                    item.message_id,
                    error=str(e),
                    retry_delay_s=self.retry_delay_s,
                    max_attempts=self.max_attempts,
                )
                fail_event = TeamEvent(
                    kind="task_failed",
                    project_id=task.project_id,
                    task_id=task.id,
                    assignee_role=self.role,
                    message=task.title,
                    metadata={"worker": self.name, "error": str(e)},
                )
                if self.store:
                    self.store.set_task_status(task.id, "failed", error=str(e))
                    self.store.append_event(fail_event)
                    self.store.upsert_agent(name=self.name, role=self.role, status="idle")
                await self.queue.publish(QUEUE_TASK_EVENTS, fail_event.to_dict())
