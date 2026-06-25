#!/usr/bin/env bash
# Finish VPS worker install after vps-setup.sh — run as root
set -euo pipefail

NICHE_ROOT="${NICHE_ROOT:-/opt/niche}"
WEBHOOK_SECRET="${WEBHOOK_SECRET:-}"

if [[ -z "$WEBHOOK_SECRET" ]]; then
  WEBHOOK_SECRET="$(openssl rand -hex 32)"
  echo "Generated WEBHOOK_SECRET=$WEBHOOK_SECRET"
  echo "Add to GitHub: gh secret set VPS_WEBHOOK_SECRET"
fi

cat > "$NICHE_ROOT/.env" <<EOF
WEBHOOK_SECRET=${WEBHOOK_SECRET}
REFERENCE_IMAGES_DIR=${NICHE_ROOT}/config/references
FLOWKIT_BASE_URL=http://127.0.0.1:8100
SCENE_DELAY_SECONDS=15
SCENE_MAX_RETRIES=3
RUNS_DIR=${NICHE_ROOT}/runs
NICHE_HOST=0.0.0.0
NICHE_PORT=8765
FLOWKIT_USE_SYSTEMD=1
FLOWKIT_START_SCRIPT=${NICHE_ROOT}/scripts/start_flowkit.sh
FLOWKIT_STOP_SCRIPT=${NICHE_ROOT}/scripts/stop_flowkit.sh
FLOWKIT_RESTART_SCRIPT=${NICHE_ROOT}/scripts/restart_flowkit_stack.sh
FLOWKIT_API_RETRIES=6
EOF

chown niche:niche "$NICHE_ROOT/.env"
chmod 600 "$NICHE_ROOT/.env"

mkdir -p "$NICHE_ROOT/runs"
chown -R niche:niche "$NICHE_ROOT/runs"

cp "$NICHE_ROOT/deploy/niche-image-worker.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable niche-image-worker
systemctl restart niche-image-worker

echo "Worker status:"
systemctl status niche-image-worker --no-pager || true
echo ""
echo "Health check:"
curl -sf "http://127.0.0.1:8765/health" || echo "Worker not responding yet"
echo ""
echo "GitHub secrets to set:"
echo "  VPS_WEBHOOK_URL=http://140.245.245.123:8765"
echo "  VPS_WEBHOOK_SECRET=${WEBHOOK_SECRET}"
