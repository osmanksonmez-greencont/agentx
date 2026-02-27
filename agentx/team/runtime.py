"""Runtime wiring for orchestrator + concurrent worker agents."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from agentx.agent.loop import AgentLoop
from agentx.bus.queue import MessageBus
from agentx.config.schema import Config
from agentx.providers.base import LLMProvider
from agentx.team.orchestrator import TeamOrchestrator
from agentx.team.queue import BaseTeamQueue, InMemoryTeamQueue, RedisTeamQueue, SQLiteTeamQueue
from agentx.team.store import TeamStore
from agentx.team.worker import TeamWorker


@dataclass(slots=True)
class TeamRuntime:
    """Long-running process for orchestrator and role workers."""

    config: Config
    provider: LLMProvider
    queue: BaseTeamQueue

    @staticmethod
    def make_queue(config: Config) -> BaseTeamQueue:
        qcfg = config.team.queue
        if qcfg.backend == "memory":
            return InMemoryTeamQueue()
        if qcfg.backend == "redis":
            return RedisTeamQueue(redis_url=qcfg.redis_url, key_prefix=qcfg.redis_prefix)
        return SQLiteTeamQueue(Path(qcfg.sqlite_path).expanduser())

    @staticmethod
    def make_store(config: Config) -> TeamStore:
        return TeamStore(Path(config.team.queue.sqlite_path).expanduser())

    def _make_agent_loop(self, role: str, store: TeamStore) -> AgentLoop:
        # Each worker gets isolated bus/session context.
        bus = MessageBus()
        role_cfg = self.config.team.roles.get(role)
        model = role_cfg.model.strip() if role_cfg and role_cfg.model else self.config.agents.defaults.model

        return AgentLoop(
            bus=bus,
            provider=self.provider,
            workspace=self.config.workspace_path,
            model=model,
            temperature=self.config.agents.defaults.temperature,
            max_tokens=self.config.agents.defaults.max_tokens,
            max_iterations=self.config.agents.defaults.max_tool_iterations,
            memory_window=self.config.agents.defaults.memory_window,
            brave_api_key=self.config.tools.web.search.api_key or None,
            exec_config=self.config.tools.exec,
            restrict_to_workspace=self.config.tools.restrict_to_workspace,
            mcp_servers=self.config.tools.mcp_servers,
            channels_config=self.config.channels,
            self_edit_config=self.config.tools.self_edit,
            team_store=store,
        )

    async def run(self, project_id: str | None = None, goal: str | None = None) -> None:
        store = self.make_store(self.config)
        orchestrator = TeamOrchestrator(queue=self.queue, store=store)
        stop_event = asyncio.Event()

        workers: list[TeamWorker] = []
        worker_tasks: list[asyncio.Task] = []
        for role, role_cfg in self.config.team.roles.items():
            if not role_cfg.enabled:
                continue
            for i in range(max(1, role_cfg.concurrency)):
                name = f"{role}-{i+1}"
                worker = TeamWorker(
                    name=name,
                    role=role,
                    queue=self.queue,
                    agent=self._make_agent_loop(role, store=store),
                    store=store,
                    pricing=self.config.pricing,
                    visibility_timeout_s=self.config.team.queue.visibility_timeout_s,
                    retry_delay_s=self.config.team.queue.retry_delay_s,
                    max_attempts=self.config.team.queue.max_attempts,
                )
                workers.append(worker)
                worker_tasks.append(asyncio.create_task(worker.run(stop_event)))

        if goal and project_id:
            created = await orchestrator.submit_goal(project_id=project_id, goal=goal, source="team-runtime")
            logger.info("Team runtime submitted {} tasks for project {}", len(created), project_id)

        try:
            await asyncio.gather(*worker_tasks)
        except KeyboardInterrupt:
            logger.info("Team runtime interrupted")
        finally:
            stop_event.set()
            for t in worker_tasks:
                t.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
