"""Tooling to enforce self-edit guardrails for the main agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.config.schema import SelfEditConfig
from nanobot.team.self_edit import SelfEditPolicy


class SelfEditGuardTool(Tool):
    """Policy + validation tool for controlled self-modification."""

    def __init__(self, workspace: Path, config: SelfEditConfig, audit_callback: Any | None = None):
        self.workspace = workspace
        self.config = config
        self.policy = SelfEditPolicy(workspace=workspace, config=config)
        self.audit_callback = audit_callback

    @property
    def name(self) -> str:
        return "self_edit_guard"

    @property
    def description(self) -> str:
        return (
            "Run self-edit safety checks for the main agent. "
            "Use preflight before editing and validate after editing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["preflight", "validate", "checkpoint", "rollback"],
                    "description": "preflight checks paths, validate runs lint/tests, checkpoint/rollback manage git recovery",
                },
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files that are planned/changed in self-edit flow",
                },
                "label": {
                    "type": "string",
                    "description": "Checkpoint commit message",
                },
                "commit_ref": {
                    "type": "string",
                    "description": "Commit SHA/ref to rollback to",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        changed_files: list[str] | None = None,
        label: str = "self-edit checkpoint",
        commit_ref: str = "",
        **kwargs: Any,
    ) -> str:
        if not self.config.enabled:
            return "Self-edit guardrails are disabled by configuration (tools.selfEdit.enabled=false)."

        if action == "preflight":
            ok, reasons = self.policy.check_paths(changed_files or [])
            if self.audit_callback:
                self.audit_callback("main-agent", "self_edit_preflight", "workspace", {"ok": ok, "reasons": reasons})
            return json.dumps(
                {
                    "ok": ok,
                    "stage": "preflight",
                    "reasons": reasons,
                },
                ensure_ascii=False,
                indent=2,
            )

        if action == "validate":
            result = await self.policy.run_validation()
            if self.audit_callback:
                self.audit_callback("main-agent", "self_edit_validate", "workspace", result)
            return json.dumps({"ok": result.get("passed", False), "stage": "validate", **result}, ensure_ascii=False, indent=2)

        if action == "checkpoint":
            result = await self.policy.create_checkpoint(label=label)
            if self.audit_callback:
                self.audit_callback("main-agent", "self_edit_checkpoint", "workspace", result)
            return json.dumps({"stage": "checkpoint", **result}, ensure_ascii=False, indent=2)

        if action == "rollback":
            if not commit_ref:
                return "Error: commit_ref is required for rollback"
            result = await self.policy.rollback_to(commit_ref=commit_ref)
            if self.audit_callback:
                self.audit_callback("main-agent", "self_edit_rollback", "workspace", result)
            return json.dumps({"stage": "rollback", **result}, ensure_ascii=False, indent=2)

        return "Error: unsupported action"
