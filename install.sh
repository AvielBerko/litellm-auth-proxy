#!/usr/bin/env bash
# Install litellm-auth-proxy as a systemd *user* service that starts at login.
#
#   ./install.sh                 # prompts for the API key
#   LITELLM_API_KEY=sk-... LITELLM_MODEL=qwen3-asr ./install.sh
#
# Re-run any time to update the key/model; it restarts the service.
set -euo pipefail

NAME=litellm-auth-proxy
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$REPO_DIR/litellm_auth_proxy.py"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$NAME"
ENV_FILE="$CONF_DIR/env"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/$NAME.service"

PYTHON="$(command -v python3 || true)"
[[ -n "$PYTHON" ]] || { echo "python3 not found" >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemctl not found (systemd required)" >&2; exit 1; }

# Keep an existing key/model unless new ones are given.
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  existing_key="$(. "$ENV_FILE"; echo "${LITELLM_API_KEY:-}")"
  existing_model="$(. "$ENV_FILE"; echo "${LITELLM_MODEL:-}")"
fi
key="${LITELLM_API_KEY:-${existing_key:-}}"
model="${LITELLM_MODEL-${existing_model:-}}"

if [[ -z "$key" ]]; then
  read -rsp "LiteLLM API key: " key; echo
  [[ -n "$key" ]] || { echo "No key given" >&2; exit 1; }
fi
if [[ -z "${LITELLM_MODEL+x}" && -z "$model" ]]; then
  read -rp "Force model name (e.g. qwen3-asr, blank = don't rewrite): " model
fi

# Secrets file, readable only by you.
mkdir -p "$CONF_DIR"
umask 077
cat > "$ENV_FILE" <<ENV
LITELLM_API_KEY=$key
LITELLM_MODEL=$model
ENV
chmod 600 "$ENV_FILE"
umask 022

mkdir -p "$UNIT_DIR"
cat > "$UNIT_FILE" <<UNIT
[Unit]
Description=LiteLLM auth proxy for OpenWhispr
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON $SCRIPT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable "$NAME" >/dev/null
systemctl --user restart "$NAME"
sleep 1
systemctl --user --no-pager status "$NAME" | head -n 12

cat <<MSG

Installed. The proxy now starts automatically when you log in.
  Logs:     journalctl --user -u $NAME -f
  Restart:  systemctl --user restart $NAME   (after editing LITELLM_URL in the script)
  Remove:   $REPO_DIR/uninstall.sh
Optional, to keep it running even when you're not logged in:
  sudo loginctl enable-linger \$USER
MSG
