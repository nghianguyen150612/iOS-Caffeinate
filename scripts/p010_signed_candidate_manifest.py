#!/usr/bin/env python3
"""Join exact-source CI evidence with one locally signed P010 candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PROFILE_ID = "amethyst-ios12-rootful"
EXPECTED_VERSION = (ROOT / "packaging/rootful/VERSION").read_text(encoding="utf-8").strip()
EXPECTED_RELEASE = "v0.1.0" if EXPECTED_VERSION == "0.1.0-1" else "v0.1.0-rc1"
EXPECTED_JOBS = {
    "linux-protocol", "ios-cross-build", "ios-artifact-inspection",
    "ios-rootful-package", "p009-evidence-validation",
    "p010-signing-release-gate", "p008-release-attestation",
}


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(value: object, label: str, length: int = 64) -> str:
    if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
        raise ValueError(f"invalid {label}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci-manifest", type=Path, required=True, help="exact-source P010-RELEASE-MANIFEST.json from CI")
    parser.add_argument("--package", type=Path, required=True, help="locally signed .deb produced by package-rootful.sh")
    parser.add_argument("--ldid", type=Path, required=True, help="same absolute host-compatible ldid used to build the package")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.ci_manifest.is_symlink() or not args.ci_manifest.is_file():
        raise SystemExit("ERROR: CI manifest must be a regular, non-symlink file")
    if args.package.is_symlink() or not args.package.is_file():
        raise SystemExit("ERROR: signed candidate must be a regular, non-symlink .deb file")
    if not args.ldid.is_absolute() or args.ldid.is_symlink() or not args.ldid.is_file():
        raise SystemExit("ERROR: signer must be supplied as an absolute, regular, non-symlink path")
    if args.output.is_symlink():
        raise SystemExit("ERROR: refusing to replace a symlink with the signed-candidate manifest")
    ci_path = args.ci_manifest.resolve()
    package = args.package.resolve()
    signer = args.ldid.resolve()
    ci = read_object(ci_path)
    source = ci.get("source")
    artifacts = ci.get("artifacts")
    ci_state = ci.get("ci")
    signing_ci = ci.get("signing")
    if not all(isinstance(value, dict) for value in (source, artifacts, ci_state, signing_ci)):
        raise SystemExit("ERROR: exact-source CI manifest is missing required objects")
    assert isinstance(source, dict) and isinstance(artifacts, dict)
    assert isinstance(ci_state, dict) and isinstance(signing_ci, dict)
    source_sha = require_hash(source.get("commit_sha"), "CI source commit", 40)
    if ci.get("release_candidate") != EXPECTED_RELEASE:
        raise SystemExit("ERROR: unexpected release candidate identifier")
    workflow_url = source.get("workflow_url")
    if not isinstance(workflow_url, str) or not workflow_url.startswith("https://"):
        raise SystemExit("ERROR: exact-source workflow URL is missing")
    if ci_state.get("source_sha_pinned") is not True:
        raise SystemExit("ERROR: CI source is not recorded as pinned")
    jobs = ci_state.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != EXPECTED_JOBS or any(
        value not in ("success", "PASS", "SKIPPED_EXPECTED_BRANCH_GUARD") for value in jobs.values()
    ):
        raise SystemExit("ERROR: CI manifest contains an unsuccessful or missing job result")
    ci_jobs = EXPECTED_JOBS - {"p008-release-attestation", "p010-signing-release-gate"}
    if any(jobs[name] != "success" for name in ci_jobs) or jobs["p010-signing-release-gate"] != "PASS" or jobs["p008-release-attestation"] != "SKIPPED_EXPECTED_BRANCH_GUARD":
        raise SystemExit("ERROR: exact-source CI jobs do not match the P010 workflow result contract")
    if ci.get("release_authorization_status") != "BLOCKED":
        raise SystemExit("ERROR: unsigned CI manifest must keep authorization blocked")

    if package.suffix != ".deb" or not package.is_file() or package.is_symlink():
        raise SystemExit("ERROR: signed candidate must be a regular .deb file")
    expected_filename = f"ioscaffeinate_{EXPECTED_VERSION}_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb"
    if package.name != expected_filename:
        raise SystemExit("ERROR: candidate filename does not identify a signed, device-unverified package")
    sidecar_path = Path(str(package) + ".manifest.json")
    sidecar = read_object(sidecar_path)
    signing = sidecar.get("signing")
    recorded_package = sidecar.get("package")
    if not isinstance(signing, dict) or not isinstance(recorded_package, dict):
        raise SystemExit("ERROR: signed package sidecar is missing signing/package records")
    if sidecar.get("source_commit_sha") != source_sha:
        raise SystemExit("ERROR: signed package source SHA differs from exact-source CI")
    if sidecar.get("package_identifier") != "com.ioscaffeinate.cli":
        raise SystemExit("ERROR: signed package identifier is unexpected")
    if sidecar.get("package_version") != EXPECTED_VERSION or sidecar.get("architecture") != "iphoneos-arm":
        raise SystemExit("ERROR: signed package version or architecture is unexpected")
    if sidecar.get("source_tree_clean") is not True:
        raise SystemExit("ERROR: signed package was not built from a clean source tree")
    if recorded_package.get("file") != package.name or recorded_package.get("sha256") != sha256(package):
        raise SystemExit("ERROR: signed package sidecar hash or filename mismatch")
    if signing.get("state") != "SIGNATURE_PRESENT" or signing.get("profile_id") != EXPECTED_PROFILE_ID:
        raise SystemExit("ERROR: package is unsigned or uses an unapproved signing profile")
    if signing.get("profile_sha256") != signing_ci.get("profile_sha256"):
        raise SystemExit("ERROR: signed package profile hash differs from the exact-source CI profile")
    require_hash(signing.get("profile_sha256"), "approved profile SHA-256")
    if signing.get("embedded_entitlements") != "EXACT_MATCH":
        raise SystemExit("ERROR: package does not record exact embedded entitlement extraction")
    signer_version = signing.get("signing_tool_version")
    if not isinstance(signer_version, str) or not signer_version:
        raise SystemExit("ERROR: signing tool version is missing")
    signer_hash = require_hash(signing.get("signing_tool_sha256"), "signing tool SHA-256")
    source_hashes = signing.get("source_binary_sha256")
    final_hashes = signing.get("final_binary_sha256")
    unsigned_ci = artifacts.get("unsigned_ci_binaries")
    if not all(isinstance(value, dict) for value in (source_hashes, final_hashes, unsigned_ci)):
        raise SystemExit("ERROR: binary hash records are missing")
    assert isinstance(source_hashes, dict) and isinstance(final_hashes, dict) and isinstance(unsigned_ci, dict)
    expected_names = {"ios-caffeinate", "ios-caffeinated"}
    if set(source_hashes) != expected_names or set(final_hashes) != expected_names:
        raise SystemExit("ERROR: signed binary hash records do not name exactly the CLI and daemon")
    for name, ci_name in (("ios-caffeinate", "ios-caffeinate_sha256"), ("ios-caffeinated", "ios-caffeinated_sha256")):
        source_hash = require_hash(source_hashes.get(name), f"unsigned {name} SHA-256")
        final_hash = require_hash(final_hashes.get(name), f"signed {name} SHA-256")
        if source_hash != require_hash(unsigned_ci.get(ci_name), f"CI {name} SHA-256"):
            raise SystemExit(f"ERROR: signed package {name} source does not match the exact-source CI binary")
        if source_hash == final_hash:
            raise SystemExit(f"ERROR: signed package {name} hash is identical to its unsigned source")

    verification = signing.get("signature_verification")
    if verification not in ("PENDING", "SIGNATURE_VERIFIED"):
        raise SystemExit("ERROR: unsupported signature-integrity state")
    if signing.get("device_execution_verification") != "NOT_VERIFIED":
        raise SystemExit("ERROR: signed package manifest overstates device execution")
    if signing.get("device_package_acceptance") != "NOT_ACCEPTED":
        raise SystemExit("ERROR: signed package manifest overstates device package acceptance")

    validation = subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_rootful_package.py"), str(package), "--ldid", str(signer)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if validation.returncode != 0:
        raise SystemExit("ERROR: signed package validation failed: " + (validation.stderr.strip() or validation.stdout.strip()))

    output = args.output.resolve()
    if output in (ci_path, package, sidecar_path) or output.exists() or output.is_symlink():
        raise SystemExit("ERROR: refusing to overwrite an input or existing signed-candidate manifest")
    candidate = {
        "manifest_version": 1,
        "release_candidate": ci.get("release_candidate"),
        "package_version": EXPECTED_VERSION,
        "source": source,
        "target": ci.get("target"),
        "signing": {
            "profile_id": signing.get("profile_id"),
            "profile_path": signing_ci.get("profile_path"),
            "profile_sha256": signing.get("profile_sha256"),
            "signing_tool_version": signer_version,
            "signing_tool_sha256": signer_hash,
            "code_signature_requirement_profile": signing.get("code_signature_requirement_profile"),
            "code_signature_requirement_profile_sha256": signing.get("code_signature_requirement_profile_sha256"),
            "signature_integrity": verification,
            "embedded_entitlements": "EXACT_MATCH",
        },
        "artifacts": {
            "unsigned_ci_binaries": unsigned_ci,
            "unsigned_ci_package": artifacts.get("unsigned_ci_package"),
            "final_signed_binaries": {
                "ios-caffeinate_sha256": final_hashes["ios-caffeinate"],
                "ios-caffeinated_sha256": final_hashes["ios-caffeinated"],
            },
            "signed_candidate_package": {
                "path": package.name,
                "sha256": recorded_package["sha256"],
                "architecture": "iphoneos-arm",
            },
        },
        "ci": ci_state,
        "device_evidence": ci.get("device_evidence"),
        "device_execution": "NOT_VERIFIED",
        "device_package_acceptance": "NOT_ACCEPTED",
        "known_limitations": ci.get("known_limitations"),
        "release_authorization_status": "BLOCKED",
        "stable_v0_1_0_authorization_status": "BLOCKED",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"P010 signed-candidate manifest: {output}")
    print(f"source_sha={source_sha}")
    print(f"signed_package_sha256={recorded_package['sha256']}")
    print(f"signature_integrity={verification}")
    print("device_package_acceptance=NOT_ACCEPTED")
    print("release_authorization=BLOCKED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError) as error:
        sys.exit(f"ERROR: {error}")
