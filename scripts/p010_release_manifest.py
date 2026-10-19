#!/usr/bin/env python3
"""Generate the exact-source P010 RC readiness manifest from CI artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "packaging/signing/profiles/amethyst-ios12-rootful.plist"
PACKAGE_VERSION = (ROOT / "packaging/rootful/VERSION").read_text(encoding="utf-8").strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def release_status(device_package_acceptance: str, hardware_review_complete: bool = False) -> str:
    if device_package_acceptance != "DEVICE_PACKAGE_ACCEPTED" or not hardware_review_complete:
        return "BLOCKED"
    return "RC_REVIEW_REQUIRED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dist = args.dist.resolve()
    packages = sorted((dist / "package").glob("*.deb"))
    if len(packages) != 1:
        raise SystemExit(f"ERROR: expected one CI package, found {len(packages)}")
    package = packages[0]
    if re.search(r"_UNSIGNED-DEVICE-UNVERIFIED\.deb$", package.name) is None:
        raise SystemExit("ERROR: P010 CI manifest expects the separate unsigned CI package")
    source_sha = os.environ.get("P010_SOURCE_SHA", "")
    checkout_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or checkout_sha != source_sha:
        raise SystemExit("ERROR: P010 manifest source SHA does not match the checked out commit")
    workflow_url = os.environ.get("P010_WORKFLOW_URL", "")
    if not workflow_url.startswith("https://"):
        raise SystemExit("ERROR: exact-source workflow URL is missing")
    profile_sha = sha256(PROFILE)
    package_sha = sha256(package)
    package_build_manifest = Path(str(package) + ".manifest.json")
    package_build = json.loads(package_build_manifest.read_text(encoding="utf-8"))
    if package_build.get("source_commit_sha") != source_sha:
        raise SystemExit("ERROR: unsigned package manifest source SHA differs from the workflow checkout")
    if package_build.get("package_version") != PACKAGE_VERSION or package_build.get("architecture") != "iphoneos-arm":
        raise SystemExit("ERROR: unsigned package manifest identity/version/architecture mismatch")
    if package_build.get("signing", {}).get("state") != "UNSIGNED":
        raise SystemExit("ERROR: unsigned CI package manifest claims a signed payload")
    if package_build.get("signing", {}).get("profile_id") is not None:
        raise SystemExit("ERROR: unsigned CI package manifest contains a signing profile claim")
    sidecar = Path(str(package) + ".sha256")
    if not sidecar.is_file() or f"{package_sha}  {package.name}" not in sidecar.read_text(encoding="utf-8"):
        raise SystemExit("ERROR: unsigned CI package checksum sidecar is missing or inconsistent")
    if package_build.get("signing", {}).get("profile_sha256") is not None:
        raise SystemExit("ERROR: unsigned CI package manifest contains a profile hash claim")
    unsigned_hashes = package_build["signing"]["final_binary_sha256"]
    if set(unsigned_hashes) != {"ios-caffeinate", "ios-caffeinated"} or any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None for value in unsigned_hashes.values()
    ):
        raise SystemExit("ERROR: unsigned CI package manifest has invalid executable hashes")
    ci_jobs = {
        "linux-protocol": os.environ.get("P010_LINUX_PROTOCOL_RESULT", "missing"),
        "ios-cross-build": os.environ.get("P010_IOS_CROSS_BUILD_RESULT", "missing"),
        "ios-artifact-inspection": os.environ.get("P010_IOS_INSPECTION_RESULT", "missing"),
        "ios-rootful-package": os.environ.get("P010_ROOTFUL_PACKAGE_RESULT", "missing"),
        "p009-evidence-validation": os.environ.get("P010_P009_RESULT", "missing"),
        "p008-release-attestation": "SKIPPED_EXPECTED_BRANCH_GUARD",
        "p010-signing-release-gate": "PASS",
    }
    if any(value not in ("success", "PASS", "SKIPPED_EXPECTED_BRANCH_GUARD") for value in ci_jobs.values()):
        raise SystemExit(f"ERROR: exact-source CI job result is not successful: {ci_jobs}")
    manifest = {
        "manifest_version": 1,
        "release_candidate": "v0.1.0" if PACKAGE_VERSION == "0.1.0-1" else "v0.1.0-rc1",
        "package_version": PACKAGE_VERSION,
        "source": {
            "repository": os.environ.get("GITHUB_REPOSITORY", "nghianguyen150612/iOS-Caffeinate"),
            "commit_sha": source_sha,
            "workflow_url": workflow_url,
        },
        "target": {
            "device": "iPad mini 2 A1489",
            "cpu": "Apple A7 ARM64",
            "ios": "12.5.7",
            "bootstrap": "Amethyst/Procursus rootful",
            "debian_architecture": "iphoneos-arm",
            "device_binary_architecture": "arm64",
            "minimum_ios_version": "12.0",
        },
        "signing": {
            "profile_id": "amethyst-ios12-rootful",
            "profile_path": str(PROFILE.relative_to(ROOT)),
            "profile_sha256": profile_sha,
            "signing_tool_version": None,
            "signing_tool_sha256": None,
            "signing_tool_status": "PENDING_OPERATOR_HOST_SIGNING",
            "signature_verification": "PENDING",
            "embedded_entitlements": "NOT_APPLICABLE_TO_UNSIGNED_CI_PACKAGE",
        },
        "artifacts": {
            "unsigned_ci_binaries": {
                "ios-caffeinate_sha256": unsigned_hashes["ios-caffeinate"],
                "ios-caffeinated_sha256": unsigned_hashes["ios-caffeinated"],
            },
            "unsigned_ci_package": {
                "path": str(package.relative_to(dist)),
                "sha256": package_sha,
                "architecture": "iphoneos-arm",
            },
            "final_signed_binaries": None,
            "signed_candidate_package": None,
        },
        "ci": {"jobs": ci_jobs, "source_sha_pinned": True},
        "device_evidence": {
            "operator_reported_execution_and_iokit": "REVIEW_REQUIRED",
            "locked_screen_lan_and_tailscale": "REVIEW_REQUIRED",
            "device_execution_verification": "PENDING_P009_REVIEW",
            "device_package_acceptance": "PENDING",
        },
        "known_limitations": [
            "No signed Debian candidate was produced by hosted CI.",
            "Signature integrity and device trust are separate and not established by unsigned CI artifacts.",
            "Package installation, upgrade/removal, rollback, and state preservation on device are pending.",
            "No-assertion comparison, battery/thermal impact, long idle reproducibility, and unattended 24/7 reliability are not validated.",
            "Scheduled wake is unverified; assertion success does not guarantee prevention of deep sleep.",
        ],
        "release_authorization_status": release_status("PENDING", False),
        "stable_v0_1_0_authorization_status": "BLOCKED",
    }
    if manifest["release_authorization_status"] != "BLOCKED":
        raise SystemExit("ERROR: missing device package acceptance must block release authorization")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"P010 release manifest: {output}")
    print(f"source_sha={source_sha}")
    print(f"unsigned_package_sha256={package_sha}")
    print("signed_candidate_package=NOT_PRODUCED")
    print("release_authorization=BLOCKED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
