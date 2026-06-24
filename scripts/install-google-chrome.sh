#!/usr/bin/env bash
# Install official Google Chrome (.deb) — NOT Chrome for Testing / Chromium zip.
set -euo pipefail

echo "==> Remove Chrome for Testing bundle (if present)"
rm -rf /opt/chrome-flowkit

echo "==> Remove old google-chrome if installed"
export DEBIAN_FRONTEND=noninteractive
apt-get remove -y google-chrome-stable 2>/dev/null || true

echo "==> Add Google Chrome apt repository"
install -m 0755 -d /usr/share/keyrings
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --batch --yes --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
  > /etc/apt/sources.list.d/google-chrome.list

echo "==> Install google-chrome-stable"
apt-get update
apt-get install -y google-chrome-stable

CHROME_BIN="/usr/bin/google-chrome-stable"
if [[ ! -x "$CHROME_BIN" ]]; then
  CHROME_BIN="/usr/bin/google-chrome"
fi
if [[ ! -x "$CHROME_BIN" ]]; then
  echo "ERROR: google-chrome binary not found after install"
  exit 1
fi

echo "==> Install VNC-safe launcher (wraps real Google Chrome)"
cat > /usr/local/bin/chrome-flowkit <<LAUNCHER
#!/usr/bin/env bash
export DISPLAY="\${DISPLAY:-:1}"
export GNOME_KEYRING_CONTROL=""
export SSH_AUTH_SOCK=""
exec "${CHROME_BIN}" \\
  --no-sandbox \\
  --disable-setuid-sandbox \\
  --disable-dev-shm-usage \\
  --disable-gpu \\
  --disable-gpu-compositing \\
  --use-gl=swiftshader \\
  --password-store=basic \\
  --disable-breakpad \\
  --no-first-run \\
  --no-default-browser-check \\
  --load-extension=/opt/flowkit/extension \\
  "\$@"
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

echo "==> Done"
"${CHROME_BIN}" --version
echo "Launch in VNC: start-chrome-flowkit"
