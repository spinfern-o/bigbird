#!/usr/bin/env bash
# Make the PhotoForge server start automatically whenever this GPU machine boots,
# so after `brev start` everything is ready without logging in.
#
#   export PHOTOFORGE_TOKEN='<token from PhotoForge > AI Settings>'
#   bash server/install_service.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
: "${PHOTOFORGE_TOKEN:?Set PHOTOFORGE_TOKEN first (copy it from PhotoForge > AI Settings)}"
[ -x .venv-server/bin/python ] || { echo "Run: bash server/setup.sh  first"; exit 1; }

# The token lives in a file only you can read, not in the service definition.
ENV_FILE="$HOME/.photoforge-server.env"
umask 077
printf 'PHOTOFORGE_TOKEN=%s\n' "$PHOTOFORGE_TOKEN" > "$ENV_FILE"

# Stop a server started by hand with start.sh, so the port is free.
pkill -f "server.photoforge_server" 2>/dev/null || true
sleep 1

if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
    sudo tee /etc/systemd/system/photoforge.service >/dev/null <<EOF
[Unit]
Description=PhotoForge GPU server
After=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$REPO
EnvironmentFile=$ENV_FILE
ExecStart=$REPO/.venv-server/bin/python -u -m server.photoforge_server --port ${PORT:-8765}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --now photoforge.service
    sleep 4
    sudo systemctl --no-pager --lines=3 status photoforge.service || true
    echo
    echo "Installed. The server now starts by itself every time this machine boots."
    echo "Logs:    journalctl -u photoforge -f"
    echo "Restart: sudo systemctl restart photoforge"
else
    # No systemd (container environments): start at boot with cron instead.
    LINE="@reboot cd $REPO && set -a && . $ENV_FILE && set +a && .venv-server/bin/python -u -m server.photoforge_server --port ${PORT:-8765} >> $REPO/server.log 2>&1"
    ( crontab -l 2>/dev/null | grep -v "server.photoforge_server" ; echo "$LINE" ) | crontab -
    set -a; . "$ENV_FILE"; set +a
    nohup .venv-server/bin/python -u -m server.photoforge_server --port "${PORT:-8765}" >> server.log 2>&1 &
    sleep 3
    tail -n 3 server.log
    echo "Installed (cron @reboot). The server now starts by itself every time this machine boots."
fi
