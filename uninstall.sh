#!/usr/bin/env bash
# Stop and remove the litellm-auth-proxy user service and its stored key.
set -euo pipefail
NAME=litellm-auth-proxy
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
systemctl --user disable --now "$NAME" 2>/dev/null || true
rm -f "$CFG/systemd/user/$NAME.service"
rm -rf "$CFG/$NAME"
systemctl --user daemon-reload
echo "Removed $NAME service and $CFG/$NAME (stored key)."
