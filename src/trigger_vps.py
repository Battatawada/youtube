#!/usr/bin/env python3
"""POST /generate on VPS image worker."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import append_github_output, httpx_post_json_with_retry, load_json, new_run_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenes", type=Path, default=Path("output/scenes.json"))
    parser.add_argument("--entities", type=Path, default=Path("output/entities.json"))
    parser.add_argument("--metadata", type=Path, default=Path("output/metadata.json"))
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    base = os.environ.get("VPS_URL", "").rstrip("/")
    secret = os.environ.get("VPS_SECRET", "")
    if not base or not secret:
        sys.exit("Set VPS_URL and VPS_SECRET")

    run_id = args.run_id
    if not run_id and args.metadata.exists():
        run_id = load_json(args.metadata).get("run_id")
    run_id = run_id or new_run_id()

    payload = {
        "run_id": run_id,
        "scenes": load_json(args.scenes),
        "entities": load_json(args.entities) if args.entities.exists() else [],
    }

    data = httpx_post_json_with_retry(
        f"{base}/generate",
        json_body=payload,
        headers={"Authorization": f"Bearer {secret}"},
        timeout=180.0,
        retries=5,
    )
    append_github_output("run_id", run_id)
    print(f"run_id={run_id}")
    print(data)


if __name__ == "__main__":
    main()
