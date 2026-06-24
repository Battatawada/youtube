#!/usr/bin/env bash
# Install Chrome for Testing ~2 months old (FlowKit v1.1.0 compatible).
# Does NOT modify FlowKit. Keeps system google-chrome; adds /opt/chrome-flowkit.
set -euo pipefail

CHROME_DIR="/opt/chrome-flowkit"
# Stable channel snapshot ~April 2026 (Chrome 146 — ~2 months before 149)
CHROME_VERSION="${CHROME_VERSION:-146.0.7653.0}"

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

cat > /usr/local/bin/chrome-flowkit <<EOF
#!/usr/bin/env bash
exec ${CHROME_DIR}/chrome "\$@"
EOF
chmod +x /usr/local/bin/chrome-flowkit

echo "Installed: chrome-flowkit ($("${CHROME_DIR}/chrome" --version))"
echo "Use in VNC: chrome-flowkit --user-data-dir=\$HOME/.config/chrome-flowkit"
