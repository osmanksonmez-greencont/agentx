# AgentX

AgentX is a 24/7 multi-agent AI software engineering system built from the agentx base.

It provides:
- A main agent entrypoint (Telegram-ready)
- Concurrent specialist agents (architect, backend, frontend, QA)
- Durable queue-based task orchestration
- Trello-like Kanban state tracking
- Management control-plane API + web panel
- Self-edit guardrails for safe autonomous code changes

## Key Features

- Multi-agent runtime with role-based workers
- Durable SQLite queue with retries and dead-letter queue
- Persistent project/task/event/board store
- Control-plane API for activity, board, usage, schedules, audit
- Web management panel at `/panel`
- Terminal session management from panel/API
- Self-edit safety pipeline:
  - preflight path policy checks
  - validation (lint/tests)
  - checkpoint and rollback actions
- Backup/restore automation scripts
- Kubernetes deployment baseline with HPA

## Project Structure

```text
agentx/
  agent/                 Core agent loop and tools
    tools/
      self_edit.py       Self-edit guardrail tool
      team.py            Team goal submission tool
  team/
    queue.py             Durable queue + DLQ
    store.py             Persistent control-plane state
    orchestrator.py      Goal decomposition
    worker.py            Concurrent role workers
    runtime.py           Team runtime wiring
  controlplane/
    server.py            HTTP API + panel serving + RBAC + SSE
    terminal.py          Terminal session manager
    static/              Panel UI (activity/board/usage/jobs/terminal/config)
scripts/
  backup_team_data.sh
  restore_team_data.sh
  run_smoke_tests.sh
deploy/k8s/
  deployment-team-runtime.yaml
  deployment-controlplane.yaml
  service-controlplane.yaml
  hpa-team-runtime.yaml
```

## Quick Start

One-line install + setup script:

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/osmanksonmez-greencont/agentx/main/scripts/agentx_install.sh)"
```

The script asks if you want to install `systemd --user` services and run AgentX on startup.

```bash
git clone <your-repo-url> agentX
cd agentX
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
agentx onboard
```

Configure `~/.agentx/config.json` (minimum):

```json
{
  "providers": {
    "openrouter": { "apiKey": "YOUR_API_KEY" }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "team": {
    "enabled": true
  },
  "controlPlane": {
    "host": "127.0.0.1",
    "port": 28880,
    "users": [
      { "name": "owner", "token": "cp_admin_token_xxx", "role": "admin" }
    ]
  }
}
```

Start runtime + control plane:

```bash
# terminal 1
agentx team run --project demo

# terminal 2
agentx controlplane
```

Submit work:

```bash
agentx team submit --project demo "Build a todo API and web app"
```

Open panel:
- http://127.0.0.1:28880/panel
- Enter control-plane token in the UI

## Core Commands

```bash
agentx team run --project demo
agentx team submit --project demo "your goal"
agentx team tasks --project demo
agentx team board --project demo
agentx team events --project demo --limit 50
agentx controlplane --host 127.0.0.1 --port 28880
```

## Control-plane API

- `GET /api/health`
- `GET /api/me`
- `GET /api/agents`
- `GET /api/projects/{project}/tasks`
- `GET /api/projects/{project}/board`
- `GET /api/projects/{project}/events`
- `GET /api/projects/{project}/events/stream` (SSE)
- `GET /api/usage`
- `GET /api/schedules`
- `GET /api/queue/dlq`
- `GET /api/audit`
- `GET /api/config`
- `POST /api/config`
- `POST /api/terminal/sessions`
- `POST /api/terminal/sessions/{id}/write`
- `GET /api/terminal/sessions/{id}/read`
- `POST /api/terminal/sessions/{id}/stop`

## RBAC

Roles:
- `viewer`: read APIs
- `operator`: viewer + terminal actions
- `admin`: full control including config writes

Auth methods:
- `X-API-Key: <token>`
- `Authorization: Bearer <token>`

## Reliability and Ops

Backup and restore:

```bash
agentx team backup
agentx team restore /path/to/backup.tar.gz
```

Smoke checks:

```bash
./scripts/run_smoke_tests.sh
```

Kubernetes baseline:

```bash
kubectl apply -f deploy/k8s/pvc.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/deployment-team-runtime.yaml
kubectl apply -f deploy/k8s/deployment-controlplane.yaml
kubectl apply -f deploy/k8s/service-controlplane.yaml
kubectl apply -f deploy/k8s/hpa-team-runtime.yaml
```

## Status

Detailed status and phase checklist:
- `PROJECT_STATUS.md`
- `MULTI_AGENT_TEAM.md`

## License

MIT (inherited from base project).
