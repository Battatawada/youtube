#!/usr/bin/env bash
# Chrome 131 for FlowKit — Oracle VPS / TigerVNC safe launcher.
CHROME_DIR="/opt/chrome-flowkit"

# VNC usually :1; fall back if not set (e.g. launched from desktop menu).
export DISPLAY="${DISPLAY:-:1}"

exec "${CHROME_DIR}/chrome" \
  --no-sandbox \
  --disable-setuid-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-gpu-compositing \
  --use-gl=swiftshader \
  --disable-software-rasterizer \
  --password-store=basic \
  --no-first-run \
  --no-default-browser-check \
  "$@"
