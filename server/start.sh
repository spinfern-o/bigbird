#!/usr/bin/env bash
# Start the PhotoForge GPU server in the background (logs go to server.log).
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PHOTOFORGE_TOKEN:?Set PHOTOFORGE_TOKEN first (copy it from PhotoForge > AI Settings)}"
nohup .venv-server/bin/python -u -m server.photoforge_server --port "${PORT:-8765}" > server.log 2>&1 &
sleep 3
tail -n 5 server.log
echo "Server running (PID $!). Stop it with: kill $!"
