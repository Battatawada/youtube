#!/usr/bin/env bash
# Install Chrome for Testing ~2 months old (FlowKit v1.1.0 compatible).
# Does NOT modify FlowKit. Keeps system google-chrome; adds /opt/chrome-flowkit.
set -euo pipefail

CHROME_DIR="/opt/chrome-flowkit"
# Default: Chrome 131 — FlowKit v1.1.0 tested era; override with CHROME_VERSION=
CHROME_VERSION="${CHROME_VERSION:-131.0.6778.264}"

mkdir -p "$CHROME_DIR"
cd /tmp
ZIP="chrome-linux64.zip"
URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip"

echo "Downloading Chrome for Testing ${CHROME_VERSION}..."
curl -fL "$URL" -o "$ZIP"
rm -rf "$CHROME_DIR"/*
unzip -q -o "$ZIP" -d "$CHROME_DIR"
mv "$CHROME_DIR/chrome-linux64"/* "$CHROME_DIR/"
rmdir "$CHROME_DIR/chrome-linux64" 2>/dev/null || true
chmod +x "$CHROME_DIR/chrome"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/chrome-flowkit-wrapper.sh" ]]; then
  cp "$SCRIPT_DIR/chrome-flowkit-wrapper.sh" /usr/local/bin/chrome-flowkit
else
  cat > /usr/local/bin/chrome-flowkit <<'EOF'
#!/usr/bin/env bash
CHROME_DIR="/opt/chrome-flowkit"
export DISPLAY="${DISPLAY:-:1}"
exec "${CHROME_DIR}/chrome" \
  --no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage \
  --disable-gpu --disable-gpu-compositing --use-gl=swiftshader \
  --password-store=basic --no-first-run --no-default-browser-check "$@"
EOF
fi
chmod +x /usr/local/bin/chrome-flowkit

echo "Installed: chrome-flowkit ($("${CHROME_DIR}/chrome" --version 2>/dev/null || echo ${CHROME_VERSION}))"
echo "Use in VNC: chrome-flowkit --user-data-dir=\$HOME/.config/chrome-flowkit"
