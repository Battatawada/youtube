#!/usr/bin/env bash
# Official Google Chrome — Oracle VPS / TigerVNC launcher (not Chromium).
CHROME_BIN="/usr/bin/google-chrome-stable"
[[ -x "$CHROME_BIN" ]] || CHROME_BIN="/usr/bin/google-chrome"

export DISPLAY="${DISPLAY:-:1}"
export GNOME_KEYRING_CONTROL=""
export SSH_AUTH_SOCK=""

PROXY_ARGS=()
if [[ -n "${CHROME_PROXY:-}" ]]; then
  PROXY_ARGS+=(--proxy-server="${CHROME_PROXY}")
  PROXY_ARGS+=(--proxy-bypass-list="127.0.0.1;localhost;<-loopback>")
fi

exec "${CHROME_BIN}" \
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
  "${PROXY_ARGS[@]}" \
  "$@"
