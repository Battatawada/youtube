#!/usr/bin/env bash
# Restart FlowKit agent (and optionally Chrome) after extension/502 errors.
set -euo pipefail

echo "[restart] FlowKit stack..."

if systemctl is-active --quiet flowkit-agent 2>/dev/null; then
  systemctl restart flowkit-agent
  echo "[restart] flowkit-agent restarted via systemd"
elif [[ -f /opt/niche/scripts/start_flowkit.sh ]]; then
  bash /opt/niche/scripts/stop_flowkit.sh || true
  sleep 2
  bash /opt/niche/scripts/start_flowkit.sh
  echo "[restart] flowkit agent started via start_flowkit.sh"
fi

# Chrome must stay open with Flow tab + extension connected (usually via VNC).
if pgrep -f "chrome-flowkit|google-chrome" >/dev/null 2>&1; then
  echo "[restart] Chrome already running — open labs.google/fx/tools/flow if 502 persists"
else
  echo "[restart] WARNING: Chrome not running. In VNC run: start-chrome-flowkit"
  echo "[restart] Then open https://labs.google/fx/tools/flow and confirm extension connected"
fi

for i in $(seq 1 24); do
  if curl -sf http://127.0.0.1:8100/health | grep -q '"extension_connected"[[:space:]]*:[[:space:]]*true'; then
    echo "[restart] FlowKit health OK (extension_connected=true)"
    exit 0
  fi
  echo "[restart] waiting for extension ($i/24)..."
  sleep 5
done

echo "[restart] FlowKit still not ready — check /var/log/flowkit-agent.log and Chrome in VNC"
exit 1
