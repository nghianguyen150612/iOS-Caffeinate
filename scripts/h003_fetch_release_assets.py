#!/usr/bin/env python3
"""Fetch and pin the public v0.1.0 release assets for H003 host validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from p011_release_preflight import PreflightError, download_release_assets  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-dir", required=True, type=Path, help="empty isolated destination directory")
    args = parser.parse_args(argv)
    try:
        result = download_release_assets(args.asset_dir.absolute())
    except (PreflightError, OSError) as error:
        print(f"H003 release asset retrieval failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"retrieval": "VERIFIED", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
