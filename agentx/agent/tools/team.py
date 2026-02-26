"""Tools for main-agent orchestration of the multi-agent team."""

from __future__ import annotations

from typing import Any

from agentx.agent.tools.base import Tool
from agentx.team.orchestrator import TeamOrchestrator


class TeamSubmitGoalTool(Tool):
    """Allow the main agent to enqueue top-level goals for team execution."""

    def __init__(self, orchestrator: TeamOrchestrator, audit_callback: Any | None = None):
        self.orchestrator = orchestrator
        self.audit_callback = audit_callback

    @property
    def name(self) -> str:
        return "team_submit_goal"

    @property
    def description(self) -> str:
        return (
            "Submit a top-level software goal to the multi-agent team orchestrator. "
            "This creates role-assigned tasks for architect/backend/frontend/qa."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project/workspace ID (e.g. 'agentx')",
                },
                "goal": {
                    "type": "string",
                    "description": "Top-level goal to decompose and execute",
                },
                "source": {
                    "type": "string",
                    "description": "Source label for tracing",
                },
            },
            "required": ["project_id", "goal"],
        }

    async def execute(self, project_id: str, goal: str, source: str = "main-agent", **kwargs: Any) -> str:
        tasks = await self.orchestrator.submit_goal(project_id=project_id, goal=goal, source=source)
        if self.audit_callback:
            self.audit_callback(
                "main-agent",
                "team_submit_goal",
                project_id,
                {"goal": goal, "createdTasks": len(tasks), "source": source},
            )
        lines = [f"Submitted goal for project '{project_id}'. Created {len(tasks)} tasks:"]
        for task in tasks:
            lines.append(f"- [{task.assignee_role}] {task.title} ({task.id})")
        return "\n".join(lines)
