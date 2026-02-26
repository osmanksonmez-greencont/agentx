"""Guardrails for controlled self-modification by the main agent."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import subprocess

from nanobot.config.schema import SelfEditConfig


@dataclass(slots=True)
class SelfEditPolicy:
    """Path policy and validation pipeline for self-edit operations."""

    workspace: Path
    config: SelfEditConfig

    def _normalize(self, raw: str) -> Path:
        p = (self.workspace / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        return p

    def _is_under_workspace(self, path: Path) -> bool:
        return path == self.workspace or self.workspace in path.parents

    def check_paths(self, changed_files: list[str]) -> tuple[bool, list[str]]:
        """Return policy decision and reasons."""
        reasons: list[str] = []
        if not changed_files:
            return False, ["No changed files were provided."]

        allowed = [self._normalize(p) for p in self.config.allowed_paths]
        protected = [self._normalize(p) for p in self.config.protected_paths]

        for raw in changed_files:
            p = self._normalize(raw)
            if not self._is_under_workspace(p):
                reasons.append(f"{raw}: outside workspace")
                continue

            blocked = any(p == pp or pp in p.parents for pp in protected)
            if blocked:
                reasons.append(f"{raw}: protected path")
                continue

            if not any(p == ap or ap in p.parents for ap in allowed):
                reasons.append(f"{raw}: not in allowed_paths")

        return len(reasons) == 0, reasons

    async def run_validation(self) -> dict[str, Any]:
        """Execute lint/test validation commands after code edits."""
        results: dict[str, Any] = {
            "passed": True,
            "steps": [],
        }
        if not self.config.require_validation:
            results["steps"].append({"name": "validation", "status": "skipped"})
            return results

        commands = [
            ("lint", self.config.lint_command.strip()),
            ("tests", self.config.test_command.strip()),
        ]
        for name, cmd in commands:
            if not cmd:
                continue
            run = await self._run_command(cmd, timeout_s=self.config.validation_timeout_s)
            results["steps"].append({"name": name, **run})
            if run["exit_code"] != 0:
                results["passed"] = False
                break

        return results

    async def create_checkpoint(self, label: str = "self-edit checkpoint") -> dict[str, Any]:
        """Create a git commit checkpoint for rollback."""
        return await asyncio.to_thread(self._create_checkpoint_sync, label)

    def _create_checkpoint_sync(self, label: str) -> dict[str, Any]:
        if not (self.workspace / ".git").exists():
            return {"ok": False, "error": "Not a git repository"}
        try:
            subprocess.run(["git", "add", "-A"], cwd=str(self.workspace), check=True, capture_output=True, text=True)
            proc = subprocess.run(
                ["git", "commit", "-m", label],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
            )
            # commit can fail when there is nothing to commit.
            if proc.returncode != 0 and "nothing to commit" not in (proc.stdout + proc.stderr).lower():
                return {"ok": False, "error": (proc.stdout + proc.stderr).strip()}
            rev = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.workspace),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            return {"ok": True, "commit": rev}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def rollback_to(self, commit_ref: str) -> dict[str, Any]:
        """Rollback workspace to a specific commit."""
        return await asyncio.to_thread(self._rollback_to_sync, commit_ref)

    def _rollback_to_sync(self, commit_ref: str) -> dict[str, Any]:
        if not (self.workspace / ".git").exists():
            return {"ok": False, "error": "Not a git repository"}
        try:
            subprocess.run(
                ["git", "reset", "--hard", commit_ref],
                cwd=str(self.workspace),
                check=True,
                capture_output=True,
                text=True,
            )
            return {"ok": True, "commit": commit_ref}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _run_command(self, command: str, timeout_s: int) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "command": command,
                "exit_code": 124,
                "stdout": "",
                "stderr": f"Timed out after {timeout_s}s",
            }

        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": (stdout or b"").decode("utf-8", errors="replace")[-6000:],
            "stderr": (stderr or b"").decode("utf-8", errors="replace")[-6000:],
        }
