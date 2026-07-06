#!/usr/bin/env bash
# Toggle Chrome Flow traffic: proxy (xray) <-> direct (VPS IP). Called by image worker on 403.
# Usage: sudo bash vps-chrome-network.sh {proxy|direct|status}
# niche user needs: sudo NOPASSWD for this script (see bottom).
set -euo pipefail

CHROME_ENV="${CHROME_ENV_PATH:-/opt/niche/chrome.env}"
PROXY_URL="${CHROME_PROXY_URL:-socks5://127.0.0.1:10808}"
DISPLAY="${CHROME_DISPLAY:-:1}"
CHROME_USER="${CHROME_USER:-ubuntu}"

write_mode() {
  local mode="$1"
  case "$mode" in
    proxy)
      cat >"$CHROME_ENV" <<EOF
CHROME_NETWORK_MODE=proxy
CHROME_PROXY=${PROXY_URL}
EOF
      ;;
    direct)
      cat >"$CHROME_ENV" <<EOF
CHROME_NETWORK_MODE=direct
CHROME_PROXY=
EOF
      ;;
    *)
      echo "Unknown mode: $mode" >&2
      exit 1
      ;;
  esac
  chmod 644 "$CHROME_ENV"
  echo "chrome.env -> ${mode}"
}

restart_chrome() {
  echo "[chrome-network] restarting Chrome (${CHROME_USER}@${DISPLAY})..."
  sudo -u "$CHROME_USER" env DISPLAY="$DISPLAY" bash -lc '
    pkill -f "google-chrome|chrome-flowkit" 2>/dev/null || true
    sleep 2
    nohup start-chrome-flowkit >/tmp/chrome-flowkit.log 2>&1 &
  '
  sleep 6
}

restart_flowkit() {
  if [[ -f /opt/niche/scripts/restart_flowkit_stack.sh ]]; then
    bash /opt/niche/scripts/restart_flowkit_stack.sh || true
  elif systemctl is-active --quiet flowkit-agent 2>/dev/null; then
    systemctl restart flowkit-agent || true
  fi
  for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8100/health | grep -q '"extension_connected"[[:space:]]*:[[:space:]]*true'; then
      echo "[chrome-network] FlowKit extension connected"
      return 0
    fi
    sleep 2
  done
  echo "[chrome-network] WARN: FlowKit extension not connected — open Flow tab in VNC" >&2
  return 1
}

cmd_status() {
  if [[ -f "$CHROME_ENV" ]]; then
    cat "$CHROME_ENV"
  else
    echo "CHROME_NETWORK_MODE=proxy (default, no chrome.env)"
  fi
}

MODE="${1:-status}"
case "$MODE" in
  proxy)
    write_mode proxy
    restart_chrome
    restart_flowkit
    ;;
  direct)
    write_mode direct
    restart_chrome
    restart_flowkit
    ;;
  status)
    cmd_status
    ;;
  *)
    echo "Usage: $0 {proxy|direct|status}" >&2
    exit 1
    ;;
esac

# One-time on VPS (root):
#   echo 'niche ALL=(ALL) NOPASSWD: /opt/niche/scripts/vps-chrome-network.sh' | sudo tee /etc/sudoers.d/niche-chrome
#   sudo chmod 440 /etc/sudoers.d/niche-chrome
