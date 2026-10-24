#!/usr/bin/env python3
"""Validate and describe one signed, exact-source v0.2.0 release candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from signing_profile import ADHOC_REQUIREMENTS_PROFILE, ADHOC_REQUIREMENTS_PROFILE_SHA256


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/v0.2/P020-SIGNED-CANDIDATE-MANIFEST.schema.json"
EXPECTED_SOURCE = "nghianguyen150612/iOS-Caffeinate"
EXPECTED_VERSION = "0.2.0~rc1-1"
EXPECTED_PACKAGE = "com.ioscaffeinate.cli"
EXPECTED_ARCH = "iphoneos-arm"
EXPECTED_PROFILE = "amethyst-ios12-rootful"
EXPECTED_PROFILE_SHA256 = "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca"
EXPECTED_SIGNER_VERSION = "2.1.5-procursus7"
EXPECTED_SIGNER_SHA256 = "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c"


class ManifestError(ValueError):
    """Candidate evidence failed an exact identity or readiness invariant."""


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ManifestError(f"expected regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ManifestError(f"{label} is missing, unsafe, or too large")
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ManifestError(f"{label} has a duplicate JSON key")
            out[key] = value
        return out
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ManifestError(f"{label} is not valid JSON") from None
    if not isinstance(value, dict):
        raise ManifestError(f"{label} root must be an object")
    return value


def source_tree_sha(source_sha: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", f"{source_sha}^{{tree}}"],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", result.stdout.strip()) is None:
        raise ManifestError("exact source tree SHA could not be resolved")
    return result.stdout.strip()


def validate_build_provenance(path: Path, build: dict[str, Any], source_sha: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/p020_build_provenance.py"), "validate", "--manifest", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise ManifestError("P020 build provenance validation failed: " + (result.stderr.strip() or result.stdout.strip()))
    source = build.get("source")
    build_cfg = build.get("build_configuration")
    toolchain = build.get("toolchain")
    artifacts = build.get("artifacts")
    repro = build.get("reproducibility")
    ci = build.get("ci")
    if not all(isinstance(item, dict) for item in (source, build_cfg, toolchain, artifacts, repro, ci)):
        raise ManifestError("P020 build provenance is missing required records")
    if (source.get("repository") != EXPECTED_SOURCE or source.get("commit_sha") != source_sha or
        source.get("tree_sha") != source_tree_sha(source_sha) or source.get("worktree_clean") is not True):
        raise ManifestError("P020 build source identity differs from the selected source SHA")
    if (build.get("candidate_state") != "UNSIGNED_DEVELOPMENT" or
        build_cfg.get("target_triple") != "arm64-apple-ios12.0" or
        build_cfg.get("deployment_target") != "12.0" or
        toolchain.get("sdk_name") != "iPhoneOS" or
        repro.get("status") != "REPRODUCIBLE" or repro.get("independent_builds") != 2 or
        repro.get("artifact_hashes_match") is not True or ci.get("source_sha_verified") is not True):
        raise ManifestError("P020 exact-source native build or reproducibility gates did not pass")
    return build


def assemble_manifest(*, build_path: Path, release_path: Path, assessment_path: Path,
                      package: Path, package_manifest_path: Path, signer_path: Path,
                      signature_receipt_path: Path, finalization_path: Path,
                      validation_path: Path, source_sha: str, workflow_run_id: str,
                      workflow_run_attempt: str, workflow_run_url: str, workflow_branch: str) -> dict[str, Any]:
    root = build_path.parent.resolve(strict=True)
    build = read_json(build_path, "P020 build provenance")
    validate_build_provenance(build_path, build, source_sha)
    release = read_json(release_path, "P020 release manifest")
    assessment = read_json(assessment_path, "P020 release assessment")
    package_record = read_json(package_manifest_path, "signed package sidecar")
    signer = read_json(signer_path, "H003 signer provenance")
    receipt = read_json(signature_receipt_path, "macOS signature-integrity receipt")
    finalization = read_json(finalization_path, "candidate finalization provenance")

    package_sha = sha256(package)
    signing = package_record.get("signing")
    package_identity = package_record.get("package")
    build_source = build.get("source")
    release_source = release.get("source")
    release_identity = release.get("release")
    if not all(isinstance(item, dict) for item in (signing, package_identity, build_source, release_source, release_identity)):
        raise ManifestError("candidate package or P020 release manifest is missing identity records")
    if (release_identity.get("version") != "v0.2.0" or
        release_identity.get("package_identifier") != EXPECTED_PACKAGE or
        release_identity.get("package_version") != EXPECTED_VERSION or
        release_identity.get("architecture") != EXPECTED_ARCH or
        release_source.get("commit_sha") != source_sha or build_source.get("commit_sha") != source_sha):
        raise ManifestError("P020 release/build manifest source or package identity is unexpected")
    if (package_record.get("source_commit_sha") != source_sha or
        package_record.get("package_identifier") != EXPECTED_PACKAGE or
        package_record.get("package_version") != EXPECTED_VERSION or
        package_record.get("architecture") != EXPECTED_ARCH or
        package_record.get("source_tree_clean") is not True or
        package_identity.get("file") != package.name or package_identity.get("sha256") != package_sha):
        raise ManifestError("signed Debian package metadata differs from exact source or requested identity")
    if (signing.get("state") != "SIGNATURE_PRESENT" or signing.get("profile_id") != EXPECTED_PROFILE or
        signing.get("profile_sha256") != EXPECTED_PROFILE_SHA256 or
        signing.get("signing_tool_version") != EXPECTED_SIGNER_VERSION or
        signing.get("signing_tool_sha256") != EXPECTED_SIGNER_SHA256 or
        signing.get("code_signature_kind") != "ADHOC" or
        signing.get("code_signature_requirement_profile") != ADHOC_REQUIREMENTS_PROFILE or
        signing.get("code_signature_requirement_profile_sha256") != ADHOC_REQUIREMENTS_PROFILE_SHA256 or
        signing.get("embedded_entitlements") != "EXACT_MATCH" or
        signing.get("signature_verification") != "SIGNATURE_VERIFIED" or
        signing.get("device_execution_verification") != "NOT_VERIFIED" or
        signing.get("device_package_acceptance") != "NOT_ACCEPTED"):
        raise ManifestError("signed candidate metadata does not satisfy the approved signer/profile contract")

    signer_identity = signer.get("executable")
    signer_repro = signer.get("reproducibility")
    if (signer.get("result") != "VERIFIED" or not isinstance(signer_identity, dict) or
        signer_identity.get("version") != EXPECTED_SIGNER_VERSION or
        signer_identity.get("sha256") != EXPECTED_SIGNER_SHA256 or
        not isinstance(signer_repro, dict) or signer_repro.get("outcome") != "EXACT_MATCH"):
        raise ManifestError("H003 signer provenance is not verified against the pinned executable")

    receipt_sha = sha256(signature_receipt_path)
    result_items = receipt.get("binary_results")
    if (receipt.get("schema_version") != 2 or receipt.get("status") != "VERIFIED" or receipt.get("source_commit_sha") != source_sha or
        receipt.get("host") != "macOS" or receipt.get("tool") != "/usr/bin/codesign" or
        receipt.get("method") != "codesign --verify --strict --verbose=4" or
        receipt.get("workflow_run_id") != workflow_run_id or
        receipt.get("workflow_run_attempt") != finalization.get("workflow_run_attempt") or
        receipt.get("package_sha256") != finalization.get("input_package_sha256") or
        not isinstance(receipt.get("codesign_version"), dict) or
        receipt["codesign_version"].get("command") != ["/usr/bin/codesign", "--version"] or
        not isinstance(receipt["codesign_version"].get("exit_code"), int) or
        not isinstance(receipt.get("macos_version"), dict) or receipt["macos_version"].get("exit_code") != 0 or
        finalization.get("source_commit_sha") != source_sha or
        finalization.get("workflow_run_id") != workflow_run_id or
        finalization.get("workflow_run_attempt") != receipt.get("workflow_run_attempt") or
        finalization.get("final_package_sha256") != package_sha or
        finalization.get("macos_receipt_sha256") != receipt_sha or
        finalization.get("apple_codesign") != "VERIFIED" or
        finalization.get("independent_code_directory") != "VERIFIED" or
        finalization.get("entitlements_exact_match") != "EXACT_MATCH" or
        finalization.get("code_signature_requirement_profile") != ADHOC_REQUIREMENTS_PROFILE or
        finalization.get("code_signature_requirement_profile_sha256") != ADHOC_REQUIREMENTS_PROFILE_SHA256 or
        finalization.get("device_signature_acceptance") != "PENDING" or
        finalization.get("repackaging") != "SIGNING_METADATA_ONLY_BINARIES_UNCHANGED" or
        finalization.get("final_package_validation") != "PASS" or not isinstance(result_items, list)):
        raise ManifestError("host signature verification or signed package finalization failed")
    expected_final_hashes = signing.get("final_binary_sha256")
    if not isinstance(expected_final_hashes, dict) or set(expected_final_hashes) != {"ios-caffeinate", "ios-caffeinated"}:
        raise ManifestError("final signed executable hashes are missing")
    if len(result_items) != 2:
        raise ManifestError("macOS signature receipt must cover exactly two binaries")
    observed = {item.get("name"): item.get("binary_sha256") for item in result_items if isinstance(item, dict)}
    if observed != expected_final_hashes or finalization.get("binary_sha256") != expected_final_hashes:
        raise ManifestError("macOS signature receipt does not cover the exact final package binaries")
    if any(not isinstance(item, dict) or item.get("exit_code") != 0 or item.get("apple_codesign_verified") is not True or
           not isinstance(item.get("independent_signature_audit"), dict) or
           item["independent_signature_audit"].get("independent_code_directory_verified") is not True or
           item["independent_signature_audit"].get("entitlements_exact_match") is not True or
           item["independent_signature_audit"].get("adhoc_flag_present") is not True or
           item["independent_signature_audit"].get("requirements") != {"count": 0, "types": []}
           for item in result_items):
        raise ManifestError("receipt does not preserve successful Apple and independent checks for both binaries")

    if (assessment.get("decision") != "RELEASE_BLOCKED" or
        assessment.get("publication_authorized") is not False):
        raise ManifestError("P020 assessment must keep this candidate blocked from publication")
    hardware = assessment.get("hardware_gates")
    if not isinstance(hardware, dict) or not hardware:
        raise ManifestError("P020 assessment omits required physical gates")
    if any(not isinstance(item, dict) or item.get("status") != "PENDING" for item in hardware.values()):
        raise ManifestError("P020 candidate cannot claim physical gates from cloud evidence")

    if (validation_path.is_symlink() or not validation_path.is_file() or
        validation_path.stat().st_size > 1024 * 1024):
        raise ManifestError("final signed package validation report is missing or unsafe")
    validation_text = validation_path.read_text(encoding="utf-8")
    for required_line in (
        "package=com.ioscaffeinate.cli",
        "version=0.2.0~rc1-1",
        "architecture=iphoneos-arm",
        "signing_state=SIGNATURE_PRESENT",
        "embedded_entitlements=EXACT_MATCH",
        "signature_verification=SIGNATURE_VERIFIED",
        "device_execution=NOT_VERIFIED",
        "device_package_acceptance=NOT_ACCEPTED",
    ):
        if required_line not in validation_text.splitlines():
            raise ManifestError("final package validator did not record the required candidate state")

    sums_path = package.parent / f"{package.name}.sha256"
    files_path = package.parent / f"{package.name}.files.sha256"
    if (sums_path.is_symlink() or not sums_path.is_file() or
        sums_path.read_text(encoding="utf-8") != f"{package_sha}  {package.name}\n"):
        raise ManifestError("signed package SHA-256 sidecar is missing or mismatched")
    if files_path.is_symlink() or not files_path.is_file():
        raise ManifestError("signed package full payload checksum sidecar is missing")

    def record(path: Path) -> dict[str, str]:
        try:
            relative = path.resolve(strict=True).relative_to(root)
        except ValueError:
            raise ManifestError(f"evidence file is outside candidate directory: {path}") from None
        return {"path": relative.as_posix(), "sha256": sha256(path)}

    build_toolchain = build["toolchain"]
    manifest = {
        "schema_version": 1,
        "candidate_state": "SIGNED_RC_DEVICE_UNVERIFIED",
        "release_candidate": "v0.2.0-rc1",
        "source": {
            "repository": EXPECTED_SOURCE,
            "branch": workflow_branch,
            "commit_sha": source_sha,
            "tree_sha": build_source["tree_sha"],
            "worktree_clean": True,
        },
        "package": {
            "identifier": EXPECTED_PACKAGE,
            "version": EXPECTED_VERSION,
            "architecture": EXPECTED_ARCH,
            "filename": package.name,
            "sha256": package_sha,
            "payload_inventory": record(files_path),
            "sha256_sidecar": record(sums_path),
        },
        "build": {
            "provenance": record(build_path),
            "release_manifest": record(release_path),
            "release_assessment": record(assessment_path),
            "reproducibility": build["reproducibility"]["status"],
            "independent_builds": build["reproducibility"]["independent_builds"],
            "target_triple": build["build_configuration"]["target_triple"],
            "minimum_ios_version": build["build_configuration"]["deployment_target"],
            "sdk_name": build_toolchain["sdk_name"],
            "sdk_version": build_toolchain["sdk_version"],
            "xcode_version": build_toolchain["xcode_version"],
            "compiler_version": build_toolchain["compiler_version"],
            "ci_run_id": build["ci"]["run_id"],
            "ci_run_url": build["ci"]["run_url"],
        },
        "signing": {
            "state": "SIGNATURE_PRESENT",
            "profile_id": EXPECTED_PROFILE,
            "profile_sha256": EXPECTED_PROFILE_SHA256,
            "entitlements": {"com.apple.private.security.no-container": True},
            "embedded_entitlements": "EXACT_MATCH",
            "code_signature_kind": "ADHOC",
            "code_signature_requirement_profile": ADHOC_REQUIREMENTS_PROFILE,
            "code_signature_requirement_profile_sha256": ADHOC_REQUIREMENTS_PROFILE_SHA256,
            "independent_code_directory_verification": "VERIFIED",
            "signer_version": EXPECTED_SIGNER_VERSION,
            "signer_sha256": EXPECTED_SIGNER_SHA256,
            "signer_provenance": record(signer_path),
            "signature_integrity": "SIGNATURE_VERIFIED",
            "signature_integrity_receipt": record(signature_receipt_path),
            "finalization_provenance": record(finalization_path),
        },
        "validation": {
            "package_validation": "PASS",
            "package_validation_report": record(validation_path),
            "native_build_source_match": "PASS",
            "apple_codesign": "VERIFIED",
            "independent_code_directory": "VERIFIED",
            "entitlements_exact_match": "EXACT_MATCH",
            "host_signature_integrity": "VERIFIED",
            "device_signature_acceptance": "PENDING",
            "device_execution": "NOT_VERIFIED",
            "device_package_acceptance": "NOT_ACCEPTED",
            "physical_gates": "PENDING",
            "release_readiness": "RELEASE_BLOCKED",
            "publication_authorized": False,
        },
        "candidate_workflow": {
            "run_id": workflow_run_id,
            "run_attempt": workflow_run_attempt,
            "run_url": workflow_run_url,
        },
    }
    schema = read_json(SCHEMA_PATH, "signed candidate manifest schema")
    try:
        import p012_common
        issues = p012_common.validate_json_schema(manifest, schema)
    except (ImportError, OSError):
        sys.path.insert(0, str(ROOT / "scripts"))
        import p012_common  # type: ignore[no-redef]
        issues = p012_common.validate_json_schema(manifest, schema)
    if issues:
        raise ManifestError("signed candidate manifest does not match schema: " + "; ".join(issues))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-provenance", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--release-assessment", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-manifest", type=Path, required=True)
    parser.add_argument("--signer-provenance", type=Path, required=True)
    parser.add_argument("--signature-receipt", type=Path, required=True)
    parser.add_argument("--finalization-provenance", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--workflow-run-url", required=True)
    parser.add_argument("--workflow-branch", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit("ERROR: refusing to overwrite the signed-candidate manifest")
    try:
        manifest = assemble_manifest(
            build_path=args.build_provenance, release_path=args.release_manifest,
            assessment_path=args.release_assessment, package=args.package,
            package_manifest_path=args.package_manifest, signer_path=args.signer_provenance,
            signature_receipt_path=args.signature_receipt, finalization_path=args.finalization_provenance,
            validation_path=args.validation_report, source_sha=args.source_sha,
            workflow_run_id=args.workflow_run_id, workflow_run_attempt=args.workflow_run_attempt,
            workflow_run_url=args.workflow_run_url,
            workflow_branch=args.workflow_branch,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, sort_keys=True, indent=2)
            stream.write("\n")
    except (ManifestError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"source_sha={manifest['source']['commit_sha']}")
    print(f"signed_package_sha256={manifest['package']['sha256']}")
    print("signature_integrity=SIGNATURE_VERIFIED")
    print("release_readiness=RELEASE_BLOCKED")
    print("publication_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
