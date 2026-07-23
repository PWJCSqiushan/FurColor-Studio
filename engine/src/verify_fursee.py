from __future__ import annotations

import argparse
import json
from pathlib import Path

from fursee_assets import inspect_assets


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a local Fursee model package")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--hash", action="store_true")
    args = parser.parse_args()
    status = inspect_assets(args.model_dir, args.manifest, verify_hashes=args.hash)
    public = {
        "configured": status.get("configured", False),
        "ready": status.get("ready", False),
        "verified": status.get("verified", False),
        "model": status.get("model", "Fursee"),
        "model_dir": status.get("model_dir", ""),
        "error": status.get("error", ""),
        "files": {
            name: {
                "exists": item.get("exists", False),
                "bytes": item.get("bytes"),
                "size_ok": item.get("size_ok", False),
                "hash_ok": item.get("hash_ok"),
            }
            for name, item in status.get("files", {}).items()
        },
    }
    print(json.dumps(public, ensure_ascii=False, indent=2))
    return 0 if status.get("ready") and (not args.hash or status.get("verified")) else 2


if __name__ == "__main__":
    raise SystemExit(main())