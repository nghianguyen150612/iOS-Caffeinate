#!/usr/bin/env python3
"""Prepare an auditable P010 operator-observation bundle without fabricating P009 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/evidence/P010-OPERATOR-REPORTED.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(output: Path) -> dict:
    record = json.loads(SOURCE.read_text(encoding="utf-8"))
    if record.get("record_type") != "operator-reported-hardware-observations":
        raise ValueError("unexpected P010 source record type")
    if record.get("evidence_origin") != "OPERATOR_RECORDED" or record.get("review_status") != "REVIEW_REQUIRED":
        raise ValueError("operator observations cannot be promoted to reviewed hardware evidence")
    if record.get("p009_review", {}).get("human_review_field_is_not_approval") is not True:
        raise ValueError("P009 review safety marker is missing")
    output.mkdir(parents=True, exist_ok=False)
    summary = output / "operator-reported-observations.json"
    shutil.copyfile(SOURCE, summary)
    bundle = {
        "bundle_version": 1,
        "bundle_kind": "P010 operator-reported summary; not a P009 acceptance session",
        "observation_date": record["observation_date"],
        "evidence_origin": "OPERATOR_RECORDED",
        "source_record": {
            "path": "operator-reported-observations.json",
            "sha256": sha256(summary),
            "size_bytes": summary.stat().st_size,
            "digest_scope": "this normalized summary file only; no raw device evidence was supplied",
        },
        "raw_evidence_files": [],
        "raw_provenance_records": [],
        "review_status": "REVIEW_REQUIRED",
        "p009_gates": record["p009_review"]["P009_gates"],
        "release_authorization": "BLOCKED",
        "instruction": "Use the P009 session template and add genuine source-classified attachments before requesting gate review. This bundle cannot pass hardware gates.",
    }
    (output / "bundle-metadata.json").write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepare", choices=("prepare",))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        bundle = prepare(args.output_dir.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"bundle={args.output_dir.resolve()}")
    print(f"source_summary_sha256={bundle['source_record']['sha256']}")
    print("evidence_origin=OPERATOR_RECORDED")
    print("review_status=REVIEW_REQUIRED")
    print("release_authorization=BLOCKED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
