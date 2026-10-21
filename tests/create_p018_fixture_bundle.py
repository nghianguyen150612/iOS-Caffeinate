#!/usr/bin/env python3
"""Create a deterministic non-device bundle fixture for the P018 validator."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import p018_validate_export  # noqa: E402


def create_bundle(output: Path, source_sha: str) -> dict[str, object]:
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("fixture output must be a new absolute path")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("source SHA must contain 40 lowercase hexadecimal digits")
    payloads = {
        "evidence/ci/mock-source.json": {
            "source_class": "MOCK",
            "fixture_kind": "p018-export-validator",
            "hardware_evidence_accepted": "NOT_ESTABLISHED",
        },
        "snapshots/doctor.json": {
            "schema_version": 1,
            "source_class": "MOCK",
            "checks": [{"component": "fixture", "status": "PENDING_VERIFICATION"}],
            "hardware_evidence_accepted": "NOT_ESTABLISHED",
        },
        "snapshots/inventory.json": {
            "schema_version": 1,
            "inventory_status": "FIXTURE_ONLY",
            "source_class": "MOCK",
            "hardware_evidence_accepted": "NOT_ESTABLISHED",
        },
    }
    output.mkdir(mode=0o700, parents=True)
    records = []
    for relative, value in sorted(payloads.items()):
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        target = output / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o600)
        records.append({
            "path": relative,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "content_type": "application/json",
            "source_id": "ci-mock-fixture-" + Path(relative).stem,
            "provenance": "MOCK",
            "review_state": "UNREVIEWED",
        })
    manifest = {
        "schema_version": 1,
        "export_type": "ioscaffeinate-diagnostic-bundle",
        "exported_at_utc": "2026-01-01T00:00:00Z",
        "package_identifier": "com.ioscaffeinate.cli",
        "source_metadata": {
            "package_version": "TEST_FIXTURE",
            "source_commit_sha": source_sha,
            "export_tool": "p018_validate_export.py",
        },
        "files": records,
        "validation_report": {
            "status": "REQUIRES_STANDALONE_VALIDATOR",
            "validator": "p018_validate_export.py",
            "scope": "schema_paths_types_sizes_hashes_encoding_privacy",
        },
        "hardware_evidence_accepted": "NOT_ESTABLISHED",
        "privacy_notice": "Synthetic CI fixture only; this is not device evidence.",
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                             encoding="utf-8")
    manifest_path.chmod(0o600)
    return p018_validate_export.validate_bundle(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    try:
        result = create_bundle(args.output, args.source_sha)
    except (OSError, ValueError, p018_validate_export.ExportValidationError) as error:
        print(f"fixture=INVALID reason={error}", file=sys.stderr)
        return 1
    print(f"fixture=VALID files={result['files_checked']} source=MOCK")
    print(f"hardware_evidence_accepted={result['hardware_evidence_accepted']}")
    print("device_evidence=no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
