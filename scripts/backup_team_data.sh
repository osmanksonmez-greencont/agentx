#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${1:-$HOME/.agentx/backups/agentx-backup-${STAMP}.tar.gz}"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

mkdir -p "$(dirname "$DEST")"

cp -f "$HOME/.agentx/config.json" "$TMPDIR/config.json" 2>/dev/null || true
cp -f "$HOME/.agentx/data/team/queue.db" "$TMPDIR/queue.db" 2>/dev/null || true
cp -f "$HOME/.agentx/data/cron/jobs.json" "$TMPDIR/jobs.json" 2>/dev/null || true

if [ -d "$HOME/.agentx/workspace" ]; then
  tar -C "$HOME/.agentx" -czf "$DEST" workspace -C "$TMPDIR" .
else
  tar -C "$TMPDIR" -czf "$DEST" .
fi

echo "Backup created: $DEST"
