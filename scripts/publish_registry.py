"""Announce a release to the nParse+ plugin registry.

POSTs to /api/v1/plugins/{id}/releases with a bearer token and an
Idempotency-Key, so re-running with the same version is a no-op rather than a
duplicate publish.

The token is minted once by signing in at https://nparseplugins.prokopto.dev/
with GitHub and claiming the plugin id. In CI it lives in the repo secret
NPARSE_REGISTRY_TOKEN; locally, pass --token or set the env var.

NOTE: the exact request body field names are per the registry's API contract
(see https://prokopto-dev.github.io/nparse-plus/latest/plugins/registry/). If
the API rejects a field, adjust the payload below to match the documented
contract — the values are all correct, only the key names may differ.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://nparseplugins.prokopto.dev/api/v1"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--sha256", required=True)
    ap.add_argument("--requires-sdk", default=">=1.0,<2")
    ap.add_argument("--min-app-version", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument("--token", default=os.environ.get("NPARSE_REGISTRY_TOKEN", ""))
    args = ap.parse_args()

    if not args.token:
        sys.exit("no token: pass --token or set NPARSE_REGISTRY_TOKEN")

    payload: dict[str, object] = {
        "version": args.version,
        "url": args.url,
        "sha256": args.sha256,
        "requires_sdk": args.requires_sdk,
    }
    if args.min_app_version:
        payload["min_app_version"] = args.min_app_version
    if args.notes:
        payload["notes"] = args.notes

    req = urllib.request.Request(
        f"{BASE}/plugins/{args.id}/releases",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {args.token}",
            "Content-Type": "application/json",
            "Idempotency-Key": f"{args.id}-{args.version}",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"registry: {resp.status} {resp.read().decode('utf-8', 'replace')}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        sys.exit(f"registry POST failed: {exc.code} {body}")


if __name__ == "__main__":
    main()
