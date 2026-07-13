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

    # Save inside images/ so the GHA `images` artifact ships the thumbnail
    # (parent-only path was dropped before render/upload).
    thumb_dest = args.output / "thumbnail.png"
    try:
        httpx_download_with_retry(
            f"{base}/runs/{args.run_id}/images/thumbnail.png",
            thumb_dest,
            headers=headers,
            timeout=180.0,
            retries=3,
        )
        if thumb_dest.stat().st_size >= 10_000:
            print(f"saved {thumb_dest} ({thumb_dest.stat().st_size // 1024}KB)")
            parent_thumb = args.output.parent / "thumbnail.png"
            parent_thumb.write_bytes(thumb_dest.read_bytes())
            print(f"copied {parent_thumb}")
        else:
            print(f"thumbnail.png too small: {thumb_dest.stat().st_size} bytes")
    except Exception as exc:  # noqa: BLE001
        print(f"thumbnail.png not available: {exc}")

    print(f"Downloaded {len(filenames)} scene images")


if __name__ == "__main__":
    main()
