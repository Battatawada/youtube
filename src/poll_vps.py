#!/usr/bin/env python3
"""Poll VPS until image generation completes."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import httpx_get_json_with_retry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()

    base = os.environ.get("VPS_URL", "").rstrip("/")
    secret = os.environ.get("VPS_SECRET", "")
    if not base or not secret:
        sys.exit("Set VPS_URL and VPS_SECRET")

    headers = {"Authorization": f"Bearer {secret}"}
    deadline = time.time() + args.timeout
    stale_since: float | None = None

    while time.time() < deadline:
        try:
            data = httpx_get_json_with_retry(
                f"{base}/runs/{args.run_id}/status",
                headers=headers,
                timeout=60.0,
                retries=3,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"poll error (retrying): {exc}", flush=True)
            time.sleep(args.interval)
            continue

        status = data.get("status")
        ready = data.get("images_ready", 0)
        total = data.get("total_scenes", 0)
        phase = data.get("phase", "")
        print(f"status={status} phase={phase} images={ready}/{total}", flush=True)

        if status == "complete":
            return

        if status == "failed":
            err = data.get("error") or "unknown error"
            err_lower = str(err).lower()
            if "429" in str(err):
                err += (
                    " — Google Flow rate limit. Re-trigger with same run_id to resume "
                    "(40+ images already saved). SCENE_DELAY_SECONDS=30 helps avoid this."
                )
            elif "unauthorized" in err_lower or "401" in str(err):
                err += (
                    " — Google Flow login expired. On VPS via VNC: open Chrome, "
                    "go to https://labs.google/fx/tools/flow, sign in again, "
                    "then bash /opt/niche/scripts/vps-preflight.sh"
                )
            elif "502" in str(err):
                err += (
                    " — FlowKit bridge error (often login expired). On VPS (VNC): "
                    "start-chrome-flowkit, open labs.google/fx/tools/flow, sign in, "
                    "then bash /opt/niche/scripts/vps-preflight.sh"
                )
            sys.exit(f"VPS job failed: {err}")

        if status == "running" and ready > 0:
            stale_since = None
        elif status in {"running", "pending"} and ready == 0:
            if stale_since is None:
                stale_since = time.time()
            elif time.time() - stale_since > 900:
                sys.exit(
                    "VPS job stuck at 0 images for 15+ minutes — check FlowKit/Chrome on VPS"
                )

        time.sleep(args.interval)

    sys.exit(f"Timeout after {args.timeout}s waiting for run {args.run_id}")


if __name__ == "__main__":
    main()
