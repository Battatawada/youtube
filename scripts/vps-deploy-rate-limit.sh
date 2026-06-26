#!/usr/bin/env bash
set -euo pipefail
ENV=/opt/niche/.env
for kv in SCENE_DELAY_SECONDS=45 FLOW_BATCH_COOLDOWN_SEC=300 FLOW_RESUME_COOLDOWN_SEC=600; do
  k="${kv%%=*}"
  if sudo grep -q "^${k}=" "$ENV" 2>/dev/null; then
    sudo sed -i "s/^${k}=.*/${kv}/" "$ENV"
  else
    echo "$kv" | sudo tee -a "$ENV" >/dev/null
  fi
done
sudo cp /tmp/phase3_sequential.py /tmp/flowkit_client.py /opt/niche/vps/
sudo chown niche:niche /opt/niche/vps/phase3_sequential.py /opt/niche/vps/flowkit_client.py
sudo systemctl restart niche-image-worker
sleep 2
sudo bash /opt/niche/scripts/vps-resume-run.sh 20260626-073808
