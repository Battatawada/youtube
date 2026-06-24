#!/usr/bin/env bash
# One-shot: remove system Chrome 149, reinstall Chrome 131 for FlowKit, fix VNC launcher.
set -euo pipefail

CHROME_DIR="/opt/chrome-flowkit"
# Chrome for Testing 149 — FlowKit on Oracle VPS / TigerVNC
CHROME_VERSION="${CHROME_VERSION:-149.0.7827.155}"

echo "==> Remove old Chrome for Testing / system Chrome"
export DEBIAN_FRONTEND=noninteractive
if dpkg -l google-chrome-stable 2>/dev/null | grep -q ^ii; then
  apt-get remove -y google-chrome-stable || true
  apt-get autoremove -y || true
fi
rm -f /etc/apt/sources.list.d/google-chrome.list
rm -f /usr/bin/google-chrome /usr/bin/google-chrome-stable 2>/dev/null || true

echo "==> Extra libraries for Chrome for Testing"
apt-get update
apt-get install -y --no-install-recommends \
  libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 \
  libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2t64 libpango-1.0-0 \
  libcairo2 libu2f-udev libvulkan1 libxss1 fonts-liberation ca-certificates \
  unzip curl

echo "==> Install Chrome for Testing ${CHROME_VERSION}"
mkdir -p "$CHROME_DIR"
cd /tmp
URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip"
curl -fL "$URL" -o chrome-linux64.zip
rm -rf "$CHROME_DIR"/*
unzip -q -o chrome-linux64.zip -d "$CHROME_DIR"
mv "$CHROME_DIR"/chrome-linux64/* "$CHROME_DIR/"
rmdir "$CHROME_DIR"/chrome-linux64 2>/dev/null || true
chmod +x "$CHROME_DIR"/chrome "$CHROME_DIR"/chrome_crashpad_handler 2>/dev/null || true

echo "==> Install launcher"
cat > /usr/local/bin/chrome-flowkit <<'LAUNCHER'
#!/usr/bin/env bash
CHROME_DIR="/opt/chrome-flowkit"
export DISPLAY="${DISPLAY:-:1}"
# Avoid keyring portal crash on minimal VNC desktops
export GNOME_KEYRING_CONTROL=""
export SSH_AUTH_SOCK=""
exec "${CHROME_DIR}/chrome" \
  --no-sandbox \
  --disable-setuid-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-gpu-compositing \
  --use-gl=swiftshader \
  --password-store=basic \
  --disable-breakpad \
  --no-first-run \
  --no-default-browser-check \
  --load-extension=/opt/flowkit/extension \
  "$@"
LAUNCHER
chmod +x /usr/local/bin/chrome-flowkit

cat > /usr/local/bin/start-chrome-flowkit <<'START'
#!/usr/bin/env bash
export DISPLAY="${DISPLAY:-:1}"
PROFILE="${HOME}/.config/chrome-flowkit"
mkdir -p "$PROFILE"
exec chrome-flowkit --user-data-dir="$PROFILE" "$@"
START
chmod +x /usr/local/bin/start-chrome-flowkit

echo "==> Reset broken Chrome profile (backed up)"
for u in ubuntu niche; do
  if [[ -d "/home/$u/.config/chrome-flowkit" ]]; then
    mv "/home/$u/.config/chrome-flowkit" "/home/$u/.config/chrome-flowkit.bak.$(date +%s)" 2>/dev/null || true
  fi
done

echo "==> Done"
chrome-flowkit --version
echo "Run inside VNC: start-chrome-flowkit"
