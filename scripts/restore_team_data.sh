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

mkdir -p "$HOME/.nanobot/data/team" "$HOME/.nanobot/data/cron" "$HOME/.nanobot"

[ -f "$TMPDIR/config.json" ] && cp -f "$TMPDIR/config.json" "$HOME/.nanobot/config.json"
[ -f "$TMPDIR/queue.db" ] && cp -f "$TMPDIR/queue.db" "$HOME/.nanobot/data/team/queue.db"
[ -f "$TMPDIR/jobs.json" ] && cp -f "$TMPDIR/jobs.json" "$HOME/.nanobot/data/cron/jobs.json"

if [ -d "$TMPDIR/workspace" ]; then
  rm -rf "$HOME/.nanobot/workspace"
  cp -a "$TMPDIR/workspace" "$HOME/.nanobot/workspace"
fi

echo "Restore completed from: $ARCHIVE"
