#!/usr/bin/env bash
# Run on VPS before re-triggering pipeline — verifies Chrome + FlowKit + image worker.
set -euo pipefail

echo "=== niche-image-worker ==="
curl -sf http://127.0.0.1:8765/health && echo || echo "FAIL: worker not on :8765"

echo ""
echo "=== flowkit /health ==="
HEALTH=$(curl -sf http://127.0.0.1:8100/health || echo '{"error":"no response"}')
echo "$HEALTH"
echo "$HEALTH" | grep -q '"extension_connected"[[:space:]]*:[[:space:]]*true' || {
  echo ""
  echo "FIX: VNC -> start-chrome-flowkit -> open https://labs.google/fx/tools/flow"
  echo "     Confirm FlowKit extension shows connected, then re-run this script."
  exit 1
}

echo ""
echo "=== flowkit GET /api/projects ==="
curl -sf http://127.0.0.1:8100/api/projects | head -c 200 && echo " ... OK" || {
  echo "FAIL: /api/projects not responding — run: bash /opt/niche/scripts/restart_flowkit_stack.sh"
  exit 1
}

echo ""
echo "All preflight checks passed."
