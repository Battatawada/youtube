#!/usr/bin/env python3
"""Poll VPS until image generation completes."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()

    base = os.environ.get("VPS_URL", "").rstrip("/")
    secret = os.environ.get("VPS_SECRET", "")
    if not base or not secret:
        sys.exit("Set VPS_URL and VPS_SECRET")

    headers = {"Authorization": f"Bearer {secret}"}
    deadline = time.time() + args.timeout

    while time.time() < deadline:
        resp = httpx.get(f"{base}/runs/{args.run_id}/status", headers=headers, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        print(f"status={status} images={data.get('images_ready')}/{data.get('total_scenes')}")
        if status == "complete":
            return
        if status == "failed":
            err = data.get("error") or "unknown error"
            if "502" in str(err):
                err += (
                    " — FlowKit Chrome extension offline. On VPS (VNC): "
                    "start-chrome-flowkit, open labs.google/fx/tools/flow, "
                    "then bash /opt/niche/scripts/vps-preflight.sh"
                )
            sys.exit(f"VPS job failed: {err}")
        time.sleep(args.interval)

    sys.exit(f"Timeout after {args.timeout}s waiting for run {args.run_id}")


if __name__ == "__main__":
    main()
