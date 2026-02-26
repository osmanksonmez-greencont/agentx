# Project Status: Multi-Agent AI Development System

Date: February 26, 2026
Base repository: `HKUDS/nanobot`

## 1. Goal
Build a 24/7 multi-agent software engineering system where:
- A main agent is the entrypoint (Telegram chat)
- Multiple concurrent agents collaborate through a queue
- Work is visible on a Trello-like Kanban board
- A management panel provides config, terminal access, usage, jobs, and activity oversight
- Main agent can safely self-modify code when needed

## 2. What We Are Doing (Implementation Direction)
We are extending `nanobot` in phases:
1. Phase 1: Core team runtime and safety foundations
2. Phase 2: Management API + board/task persistence and activity streams
3. Phase 3: Web management panel (Activity + Kanban)
4. Phase 4: Token/cost accounting, terminal control, scheduled jobs UI
5. Phase 5: Reliability hardening for 24/7 production

## 3. Current Progress Summary
Status: **Baseline implementation delivered across all 5 phases**

### 3.1 Completed
- Added team runtime configuration schema (`team.*`) and self-edit guard config (`tools.selfEdit.*`)
- Added durable queue backend (`sqlite`) with role-specific task queues
- Added orchestrator that decomposes high-level goals into role tasks
- Added concurrent role workers (`architect`, `backend`, `frontend`, `qa`)
- Added runtime entry to run worker pool continuously
- Added main-agent tool: `team_submit_goal`
- Added main-agent tool: `self_edit_guard` (preflight + validate)
- Added persistent team store for projects/tasks/events/board state
- Added task status transitions (`ready -> in_progress -> review/done`, and `failed`)
- Added CLI inspection views for persisted state:
  - `nanobot team tasks`
  - `nanobot team board`
  - `nanobot team events` (store-backed)
- Added control-plane HTTP API server (`nanobot controlplane`)
- Added web management panel (`/panel`) with tabs for activity, board, usage, schedules, terminal, config
- Added terminal session service (create/write/read/stop) with audit logs
- Added audit log persistence and API
- Added usage tracking persistence and summary API
- Added queue dead-letter archival and DLQ API
- Wired team orchestration and self-edit tools into gateway/agent runtime
- Added new CLI commands:
  - `nanobot team run`
  - `nanobot team submit`
  - `nanobot team events`
  - `nanobot team tasks`
  - `nanobot team board`
- Added technical usage docs in `MULTI_AGENT_TEAM.md`
- README updated with multi-agent runtime section

### 3.2 Not Done Yet
- None in current implementation scope.

## 4. Detailed Checklist

## Phase 1: Team Runtime + Self-Edit Safety
- [x] Team config schema
- [x] Self-edit config schema
- [x] Durable queue abstraction
- [x] SQLite queue backend
- [x] Orchestrator goal decomposition
- [x] Concurrent worker runtime
- [x] Main-agent `team_submit_goal` tool
- [x] Main-agent `self_edit_guard` tool
- [x] CLI commands for team runtime
- [x] Automated smoke coverage baseline (`scripts/run_smoke_tests.sh`)

## Phase 2: Backend Control Plane
- [x] Persistent task/board/event store
- [x] Task API
- [x] Agent registry/health API
- [x] Board API (read view)
- [x] Activity/event stream API (SSE)
- [x] Usage/credits API (token usage + configurable model rates)
- [x] Scheduled jobs API (read view)

## Phase 3: Management Panel UI
- [x] Agent activity page
- [x] Software dev Kanban page
- [x] Config management page
- [x] Usage dashboard
- [x] Scheduled jobs page

## Phase 4: Ops and Governance
- [x] Terminal access service + UI
- [x] Audit logs and action history
- [x] Policy gates for high-risk actions (self-edit path checks + validation)
- [x] Rollback automation baseline for self-edits (git checkpoint/rollback actions)

## Phase 5: 24/7 Production Hardening
- [x] Retry policies and DLQ strategy
- [x] Health checks baseline
- [x] Backup/recovery automation baseline
- [x] Multi-instance orchestration and autoscaling baseline (k8s manifests + HPA)

## 5. Code Areas Already Added/Changed
- `nanobot/config/schema.py`
- `nanobot/agent/loop.py`
- `nanobot/agent/tools/self_edit.py`
- `nanobot/agent/tools/team.py`
- `nanobot/team/queue.py`
- `nanobot/team/types.py`
- `nanobot/team/orchestrator.py`
- `nanobot/team/worker.py`
- `nanobot/team/runtime.py`
- `nanobot/team/store.py`
- `nanobot/controlplane/server.py`
- `nanobot/controlplane/terminal.py`
- `nanobot/controlplane/static/index.html`
- `nanobot/controlplane/static/style.css`
- `nanobot/controlplane/static/app.js`
- `scripts/backup_team_data.sh`
- `scripts/restore_team_data.sh`
- `deploy/k8s/*`
- `nanobot/cli/commands.py`
- `README.md`
- `MULTI_AGENT_TEAM.md`

## 6. Immediate Next Step
Next optional upgrades: TLS/SSO integration, secrets manager, and provider-invoice reconciliation.
