#!/usr/bin/env bash
# Launch FlowKit Chrome from VNC desktop (double-click or terminal).
# Mode: /opt/niche/chrome.env — CHROME_NETWORK_MODE=proxy|direct
export DISPLAY="${DISPLAY:-:1}"
if [[ -r /opt/niche/chrome.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /opt/niche/chrome.env
  set +a
fi
if [[ "${CHROME_NETWORK_MODE:-proxy}" == "proxy" ]]; then
  export CHROME_PROXY="${CHROME_PROXY:-socks5://127.0.0.1:10808}"
else
  unset CHROME_PROXY
fi
exec chrome-flowkit --user-data-dir="${HOME}/.config/google-chrome" "$@"
