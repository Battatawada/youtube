#!/usr/bin/env python3
"""
Disable broken declarativeNetRequest rules — FlowKit sets Referer/Origin via
agent/services/headers.py in fetch headers. rules.json prevents extension load on Chrome 131+.
"""
import json
import shutil
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/flowkit/extension/manifest.json")
backup = manifest_path.with_suffix(".json.bak2")

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if not backup.exists():
    shutil.copy2(manifest_path, backup)

perms = [p for p in manifest.get("permissions", []) if p not in (
    "declarativeNetRequest",
    "declarativeNetRequestWithHostAccess",
    "declarativeNetRequestFeedback",
)]
manifest["permissions"] = perms
manifest.pop("declarative_net_request", None)

manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"Patched {manifest_path}: removed declarative_net_request block")
print("Permissions:", manifest["permissions"])
