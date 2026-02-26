#!/usr/bin/env sh
set -eu

REPO_URL="${AGENTX_REPO_URL:-https://github.com/osmanksonmez-greencont/agentx.git}"
REPO_DIR="${AGENTX_REPO_DIR:-$HOME/agentX}"
PROJECT_ID="${AGENTX_PROJECT_ID:-default}"
CONTROLPLANE_HOST="${AGENTX_CONTROLPLANE_HOST:-127.0.0.1}"
CONTROLPLANE_PORT="${AGENTX_CONTROLPLANE_PORT:-18880}"

say() {
  printf '%s\n' "$*"
}

ask_yes_no() {
  prompt="$1"
  default_no="${2:-yes}"
  while true; do
    if [ "$default_no" = "yes" ]; then
      printf "%s [y/N]: " "$prompt"
    else
      printf "%s [Y/n]: " "$prompt"
    fi
    read ans || true
    ans="$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]')"
    if [ -z "$ans" ]; then
      if [ "$default_no" = "yes" ]; then
        return 1
      fi
      return 0
    fi
    case "$ans" in
      y|yes) return 0 ;;
      n|no) return 1 ;;
    esac
  done
}

ensure_repo() {
  if [ -f "./pyproject.toml" ] && [ -d "./nanobot" ]; then
    REPO_DIR="$(pwd)"
    say "Using existing repo: $REPO_DIR"
    return
  fi

  if [ -d "$REPO_DIR/.git" ]; then
    say "Updating existing repo: $REPO_DIR"
    git -C "$REPO_DIR" pull --ff-only origin main
  else
    say "Cloning AgentX into: $REPO_DIR"
    git clone "$REPO_URL" "$REPO_DIR"
  fi
}

setup_python() {
  say "Setting up virtual environment"
  if [ ! -d "$REPO_DIR/.venv" ]; then
    python3 -m venv "$REPO_DIR/.venv"
  fi

  # shellcheck disable=SC1091
  . "$REPO_DIR/.venv/bin/activate"
  pip install -e "$REPO_DIR"

  if [ ! -f "$HOME/.nanobot/config.json" ]; then
    say "Creating default nanobot config"
    nanobot onboard
  else
    say "Config already exists at ~/.nanobot/config.json (skipping onboard)"
  fi
}

install_services() {
  USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
  mkdir -p "$USER_SYSTEMD_DIR"

  TEAM_SERVICE="$USER_SYSTEMD_DIR/agentx-team.service"
  CP_SERVICE="$USER_SYSTEMD_DIR/agentx-controlplane.service"

  cat > "$TEAM_SERVICE" <<SERVICE
[Unit]
Description=AgentX Team Runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
ExecStart=/bin/sh -lc '. "$REPO_DIR/.venv/bin/activate" && nanobot team run --project "$PROJECT_ID"'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
SERVICE

  cat > "$CP_SERVICE" <<SERVICE
[Unit]
Description=AgentX Control Plane
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
ExecStart=/bin/sh -lc '. "$REPO_DIR/.venv/bin/activate" && nanobot controlplane --host "$CONTROLPLANE_HOST" --port "$CONTROLPLANE_PORT"'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
SERVICE

  systemctl --user daemon-reload
  systemctl --user enable --now agentx-team.service
  systemctl --user enable --now agentx-controlplane.service

  if ask_yes_no "Enable lingering so services keep running after logout?" yes; then
    if command -v loginctl >/dev/null 2>&1; then
      loginctl enable-linger "$USER" || say "Could not enable lingering automatically; you can run: loginctl enable-linger $USER"
    fi
  fi

  say "Services installed and started:"
  say "  - agentx-team.service"
  say "  - agentx-controlplane.service"
  say "Panel URL: http://$CONTROLPLANE_HOST:$CONTROLPLANE_PORT/panel"
}

run_now() {
  say "To run manually now:"
  say "  1) cd $REPO_DIR && . .venv/bin/activate && nanobot team run --project $PROJECT_ID"
  say "  2) cd $REPO_DIR && . .venv/bin/activate && nanobot controlplane --host $CONTROLPLANE_HOST --port $CONTROLPLANE_PORT"
}

main() {
  ensure_repo
  setup_python

  if ask_yes_no "Install systemd user services and auto-start on login?" yes; then
    install_services
  else
    run_now
  fi

  say "Done."
}

main "$@"
