#!/usr/bin/env python3
"""Download scene PNGs from VPS."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import httpx_download_with_retry, httpx_get_json_with_retry, load_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, default=Path("output/images"))
    parser.add_argument("--durations", type=Path, default=Path("output/scene_durations.json"))
    args = parser.parse_args()

    base = os.environ.get("VPS_URL", "").rstrip("/")
    secret = os.environ.get("VPS_SECRET", "")
    if not base or not secret:
        sys.exit("Set VPS_URL and VPS_SECRET")

    headers = {"Authorization": f"Bearer {secret}"}
    args.output.mkdir(parents=True, exist_ok=True)

    if args.durations.exists():
        durations = load_json(args.durations)
        filenames = [d["file"] for d in durations]
    else:
        status = httpx_get_json_with_retry(
            f"{base}/runs/{args.run_id}/status",
            headers=headers,
            timeout=60.0,
        )
        total = status.get("total_scenes", 20)
        filenames = [f"scene_{i:02d}.png" for i in range(1, total + 1)]

    for name in filenames:
        dest = args.output / name
        httpx_download_with_retry(
            f"{base}/runs/{args.run_id}/images/{name}",
            dest,
            headers=headers,
            timeout=180.0,
            retries=5,
        )
        if dest.stat().st_size < 10_000:
            raise RuntimeError(f"Downloaded image too small: {dest} ({dest.stat().st_size} bytes)")
        print(f"saved {dest} ({dest.stat().st_size // 1024}KB)")

    print(f"Downloaded {len(filenames)} images")


if __name__ == "__main__":
    main()
