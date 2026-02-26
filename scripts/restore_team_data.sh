#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
  echo "Usage: $0 <backup.tar.gz>"
  exit 1
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

tar -xzf "$ARCHIVE" -C "$TMPDIR"

mkdir -p "$HOME/.agentx/data/team" "$HOME/.agentx/data/cron" "$HOME/.agentx"

[ -f "$TMPDIR/config.json" ] && cp -f "$TMPDIR/config.json" "$HOME/.agentx/config.json"
[ -f "$TMPDIR/queue.db" ] && cp -f "$TMPDIR/queue.db" "$HOME/.agentx/data/team/queue.db"
[ -f "$TMPDIR/jobs.json" ] && cp -f "$TMPDIR/jobs.json" "$HOME/.agentx/data/cron/jobs.json"

if [ -d "$TMPDIR/workspace" ]; then
  rm -rf "$HOME/.agentx/workspace"
  cp -a "$TMPDIR/workspace" "$HOME/.agentx/workspace"
fi

echo "Restore completed from: $ARCHIVE"
