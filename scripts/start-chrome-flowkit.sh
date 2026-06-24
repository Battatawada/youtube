#!/usr/bin/env bash
# Launch FlowKit Chrome from VNC desktop (double-click or terminal).
export DISPLAY="${DISPLAY:-:1}"
exec chrome-flowkit --user-data-dir="${HOME}/.config/chrome-flowkit" "$@"
