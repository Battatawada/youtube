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
echo "=== flowkit POST /api/projects (auth probe) ==="
PROBE_JSON='{"name":"niche-preflight-probe","story":null}'
HTTP=$(curl -s -o /tmp/niche_flow_probe.json -w '%{http_code}' \
  -X POST http://127.0.0.1:8100/api/projects \
  -H 'Content-Type: application/json' \
  -d "$PROBE_JSON")
echo "HTTP $HTTP"
head -c 300 /tmp/niche_flow_probe.json && echo
if [[ "$HTTP" == "502" ]]; then
  echo ""
  echo "FAIL: Flow project create returned 502 (usually Google Flow login expired)."
  echo "FIX: VNC into VPS -> Chrome -> https://labs.google/fx/tools/flow"
  echo "     Sign in to your Google account, reload the page, confirm extension connected."
  echo "     Then re-run: bash /opt/niche/scripts/vps-preflight.sh"
  exit 1
fi
if [[ "$HTTP" != "200" && "$HTTP" != "201" ]]; then
  echo ""
  echo "FAIL: cannot create Flow project (HTTP $HTTP)."
  echo "FIX: VNC -> re-login at labs.google/fx/tools/flow, or run restart_flowkit_stack.sh"
  exit 1
fi
echo " ... create project OK"

echo ""
echo "=== flowkit POST /api/flow/generate-image (quota probe) ==="
PROBE_PID=$(python3 -c "import json; d=json.load(open('/tmp/niche_flow_probe.json')); print(d.get('id',''))")
GEN_HTTP=$(curl -s -o /tmp/niche_flow_gen_probe.json -w '%{http_code}' \
  -X POST http://127.0.0.1:8100/api/flow/generate-image \
  -H 'Content-Type: application/json' \
  -d "{\"prompt\":\"Minimalist stick figure at a window, cream background, line art, no text\",\"project_id\":\"${PROBE_PID}\",\"aspect_ratio\":\"IMAGE_ASPECT_RATIO_LANDSCAPE\"}")
echo "HTTP $GEN_HTTP"
head -c 300 /tmp/niche_flow_gen_probe.json && echo
if [[ "$GEN_HTTP" == "403" ]]; then
  echo ""
  echo "FAIL: generate-image returned 403 — Google Flow image quota exhausted."
  echo "FIX: Wait 1-2 hours (or until tomorrow UTC), then re-run this script."
  echo "     Check labs.google/fx/tools/flow in VNC — try one manual image first."
  exit 1
fi
if [[ "$GEN_HTTP" != "200" && "$GEN_HTTP" != "201" ]]; then
  echo ""
  echo "FAIL: generate-image probe failed (HTTP $GEN_HTTP)."
  echo "FIX: bash /opt/niche/scripts/restart_flowkit_stack.sh then re-login in Chrome."
  exit 1
fi
echo " ... generate-image OK"

echo ""
echo "All preflight checks passed."
