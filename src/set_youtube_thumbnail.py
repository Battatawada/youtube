#!/usr/bin/env python3
"""Set custom thumbnail on an existing YouTube video (no re-upload)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from googleapiclient.http import MediaFileUpload

from phase5_upload import build_youtube


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--thumbnail", type=Path, required=True)
    args = parser.parse_args()

    for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        if not os.environ.get(key):
            sys.exit(f"Missing env {key}")

    if not args.thumbnail.exists() or args.thumbnail.stat().st_size < 10_000:
        sys.exit(f"Bad thumbnail: {args.thumbnail}")

    youtube = build_youtube()
    media = MediaFileUpload(str(args.thumbnail), mimetype="image/png", resumable=True)
    resp = youtube.thumbnails().set(videoId=args.video_id, media_body=media).execute()
    print(json.dumps({"thumbnail_upload": "ok", "video_id": args.video_id, "items": len(resp.get("items", []))}))


if __name__ == "__main__":
    main()
