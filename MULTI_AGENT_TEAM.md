# Multi-Agent Team Runtime (Phase 1)

This repository now includes a first implementation of a concurrent software-engineering team runtime.

## Implemented

- Durable task queue backend (`sqlite`) with retry + visibility timeout semantics.
- Role-based concurrent workers (`architect`, `backend`, `frontend`, `qa`).
- Main orchestrator that decomposes top-level goals into role-assigned tasks.
- Main-agent tool `team_submit_goal` to enqueue goals from chat.
- Self-edit guardrails tool `self_edit_guard` with:
  - preflight path policy checks
  - lint/test validation pipeline
  - git checkpoint/rollback actions
- Persistent control-plane store for:
  - projects
  - tasks and status transitions
  - activity events
  - board columns/cards

## CLI

```bash
# Start worker runtime (runs until stopped)
nanobot team run --project agentx

# Start worker runtime and submit a goal immediately
nanobot team run --project agentx --goal "Build a multi-agent coding platform"

# Submit a goal without starting workers
nanobot team submit --project agentx "Build a multi-agent coding platform"

# Inspect persisted state
nanobot team tasks --project agentx
nanobot team board --project agentx
nanobot team events --project agentx --limit 30

# Start management API + web panel
nanobot controlplane --host 127.0.0.1 --port 18880
# open http://127.0.0.1:18880/panel

# Backup/restore
nanobot team backup
nanobot team restore ~/.nanobot/backups/nanobot-backup-YYYYMMDD-HHMMSS.tar.gz
```

## Control-plane API (baseline)

- `GET /api/health`
- `GET /api/agents`
- `GET /api/me`
- `GET /api/projects/{project}/tasks`
- `GET /api/projects/{project}/board`
- `GET /api/projects/{project}/events?limit=30`
- `GET /api/usage?projectId={project}`
- `GET /api/schedules`
- `GET /api/queue/dlq?limit=20`
- `GET /api/audit?limit=50`
- `GET /api/config`
- `POST /api/config`
- `POST /api/terminal/sessions`
- `POST /api/terminal/sessions/{id}/write`
- `GET /api/terminal/sessions/{id}/read?limit=200`
- `POST /api/terminal/sessions/{id}/stop`

## RBAC / Auth

Control-plane tokens are configured in `controlPlane.users`:

```json
{
  "controlPlane": {
    "users": [
      { "name": "owner", "token": "cp_admin_token_xxx", "role": "admin" },
      { "name": "ops", "token": "cp_ops_token_xxx", "role": "operator" },
      { "name": "viewer", "token": "cp_view_token_xxx", "role": "viewer" }
    ]
  }
}
```

Roles:
- `viewer`: read APIs
- `operator`: viewer + terminal actions
- `admin`: full access (including config writes)

## Deploy / Recovery

- Kubernetes baseline manifests: `deploy/k8s/`
- Backup script: `scripts/backup_team_data.sh`
- Restore script: `scripts/restore_team_data.sh`
- Smoke checks: `scripts/run_smoke_tests.sh`

## Reliability notes

- Queue retries with visibility timeout and dead-letter archival (`queue_dead_letters` table).
- Worker activity heartbeats and task lifecycle persisted in `team_agents` / `team_events`.
- Usage is recorded with estimated token accounting per completed task.

## Config additions (`~/.nanobot/config.json`)

```json
{
  "team": {
    "enabled": true,
    "queue": {
      "backend": "sqlite",
      "sqlitePath": "~/.nanobot/data/team/queue.db",
      "visibilityTimeoutS": 120,
      "retryDelayS": 10,
      "maxAttempts": 3
    }
  },
  "tools": {
    "selfEdit": {
      "enabled": true,
      "allowedPaths": ["nanobot", "tests", "README.md"],
      "protectedPaths": [".git", ".env", "secrets", "docker-compose.yml"],
      "requireValidation": true,
      "lintCommand": "ruff check nanobot tests",
      "testCommand": "pytest -q",
      "validationTimeoutS": 300
    }
  }
}
```
