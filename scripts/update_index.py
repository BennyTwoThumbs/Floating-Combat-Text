"""Regenerate index.json (the update manifest / registry-format feed).

Usage:
    python scripts/update_index.py --version 1.9.1 \
        --url https://github.com/.../floating-combat-text-1.9.1.zip \
        --sha256 <64 hex> [--requires-sdk ">=1.0,<2"]
"""

from __future__ import annotations

import argparse
import json
import pathlib

INDEX = pathlib.Path(__file__).resolve().parent.parent / "index.json"
PLUGIN_ID = "floating-combat-text"
PLUGIN_NAME = "Floating Combat Text"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--sha256", required=True)
    ap.add_argument("--requires-sdk", default=">=1.0,<2")
    args = ap.parse_args()

    doc = {
        "schema_version": 1,
        "plugins": [
            {
                "id": PLUGIN_ID,
                "name": PLUGIN_NAME,
                "latest": {
                    "version": args.version,
                    "url": args.url,
                    "sha256": args.sha256,
                    "requires_sdk": args.requires_sdk,
                },
            }
        ],
    }
    INDEX.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {INDEX} for v{args.version}")


if __name__ == "__main__":
    main()
