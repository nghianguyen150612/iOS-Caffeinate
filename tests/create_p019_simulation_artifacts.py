#!/usr/bin/env python3
"""Create deterministic SIMULATED-only P019 CI review artifacts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from p019_fixtures import make_session


SHA40 = re.compile(r"^[0-9a-f]{40}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if not SHA40.fullmatch(args.source_sha):
        raise SystemExit("source SHA must be a lowercase 40-character Git SHA")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session = make_session(args.source_sha, full=True)
    session["session_id"] = "p019-ci-simulation"
    session["created_at_utc"] = "2037-01-04T00:00:00Z"
    session_path = args.output_dir / "session-simulated.json"
    session_path.write_text(json.dumps(session, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    summary = {
        "artifact_version": 1,
        "milestone": "P019",
        "source_sha": args.source_sha,
        "fixture_provenance": "SIMULATED",
        "evidence_class": "SIMULATED",
        "expected_decision": "PREREQUISITES_BLOCKED",
        "hardware_acceptance": "NOT_ESTABLISHED",
        "device_actions": "NOT_PERFORMED",
        "ssh_probe_execution": "NOT_PERFORMED",
        "daemon_execution": "NOT_PERFORMED",
        "assertion_acquisition": "NOT_PERFORMED",
        "package_installation_or_rollback": "NOT_PERFORMED",
        "launchd_mutation": "NOT_PERFORMED",
        "unattended_execution": "NOT_PERFORMED",
    }
    (args.output_dir / "SIMULATED-ONLY.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
