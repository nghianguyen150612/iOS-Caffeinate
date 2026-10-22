"""Strict P020 release-gate fixtures. None represents physical evidence."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import p020_release_gate as gate  # noqa: E402


def write_json(path: Path, value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def release_manifest(directory: Path, *, source_sha: str, base_sha: str) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    chain = []
    for milestone, pr, branch, head, base_branch, milestone_base_sha, merge_sha in gate.EXPECTED_CHAIN:
        chain.append({
            "milestone": milestone, "pr": pr, "branch": branch, "head_sha": head,
            "base_branch": base_branch, "base_sha": milestone_base_sha, "merge_sha": merge_sha,
            "state": "MERGED", "mergeability": "UNKNOWN", "review_state": "NONE", "exact_head_ci": "PASS",
        })
    gate_names = [
        "source_integration", "native_build", "ios_cross_build", "macho_inspection",
        "rootful_packaging", "signing_metadata", "security_analysis", "regression_ci",
        "evidence_schema_compatibility", "build_provenance",
    ]
    attestation = {
        "source_sha": source_sha,
        "gate_results": {name: "PASS" for name in gate_names},
        "workflow_run_id": "100",
        "p008_attestation": "SKIPPED_EXPECTED_BRANCH_GUARD",
    }
    digest = write_json(directory / "ci-attestation.json", attestation)
    cloud = {name: {"status": "PASS", "evidence": [{"path": "ci-attestation.json", "sha256": digest, "evidence_class": "CI"}]} for name in gate_names}
    artifact_bytes = {
        "candidate/first-cli": b"unsigned fixture cli",
        "candidate/first-daemon": b"unsigned fixture daemon",
        "candidate/first-package.deb": b"unsigned fixture deb",
        "candidate/second-cli": b"unsigned fixture cli",
        "candidate/second-daemon": b"unsigned fixture daemon",
        "candidate/second-package.deb": b"unsigned fixture deb",
    }
    artifact_records = {}
    for name, payload in artifact_bytes.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        artifact_records[name] = {"path": name, "sha256": hashlib.sha256(payload).hexdigest()}
    tree_sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", f"{source_sha}^{{tree}}"], check=True, capture_output=True, text=True).stdout.strip()
    source_epoch = int(subprocess.run(["git", "-C", str(ROOT), "show", "-s", "--format=%ct", source_sha], check=True, capture_output=True, text=True).stdout.strip())
    provenance = {
        "schema_version": 1,
        "candidate_state": "UNSIGNED_DEVELOPMENT",
        "source": {"repository": "nghianguyen150612/iOS-Caffeinate", "branch": "release/p020-v02-integration", "commit_sha": source_sha, "tree_sha": tree_sha, "worktree_clean": True},
        "build_configuration": {"compiler_flags": ["-std=c11", "-O2", "-target arm64-apple-ios12.0"], "target_triple": "arm64-apple-ios12.0", "deployment_target": "12.0", "build_kind": "DEVELOPMENT", "release_channel": "PRE_RELEASE", "source_date_epoch": source_epoch},
        "toolchain": {"compiler": "Apple Clang", "compiler_version": "Apple clang fixture", "sdk_name": "iPhoneOS", "sdk_version": "18.0", "xcode_version": "Xcode fixture", "package_tool": "dpkg-deb", "package_tool_version": "dpkg-deb fixture"},
        "target": {"device": "iPad mini 2 A1489 (iPad4,4)", "cpu": "Apple A7 ARM64", "ios": "12.5.7", "bootstrap": "Amethyst/Procursus rootful", "debian_architecture": "iphoneos-arm", "binary_architecture": "arm64 Mach-O", "minimum_ios_version": "12.0"},
        "dependencies": ["/usr/lib/libSystem.B.dylib", "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"],
        "package": {"identifier": "com.ioscaffeinate.cli", "version": "0.2.0~rc1-1", "architecture": "iphoneos-arm"},
        "artifacts": {"cli": artifact_records["candidate/first-cli"], "daemon": artifact_records["candidate/first-daemon"], "package": artifact_records["candidate/first-package.deb"], "second_build_cli": artifact_records["candidate/second-cli"], "second_build_daemon": artifact_records["candidate/second-daemon"], "second_build_package": artifact_records["candidate/second-package.deb"]},
        "signing": {"state": "UNSIGNED", "profile_id": "amethyst-ios12-rootful", "profile_sha256": gate.EXPECTED_PROFILE_SHA256, "signing_tool_version": None, "signing_tool_sha256": None, "provenance_status": "SIGNER_PROVENANCE_BLOCKED"},
        "reproducibility": {"status": "REPRODUCIBLE", "independent_builds": 2, "inputs_match": True, "artifact_hashes_match": True, "analysis": "Synthetic unit-test fixture only; no real build is represented."},
        "ci": {"workflow": "iOS-Caffeinate CI / p020-release-readiness-validation", "run_id": "100", "run_url": "https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/100", "event": "pull_request", "source_sha_verified": True},
        "validation": {"macho_inspection": "PASS", "package_inspection": "PASS", "payload_hashes": "PASS", "maintainer_scripts": "PASS", "persistent_state_seeded": False, "device_installation": "NOT_PERFORMED", "release_authorization": "BLOCKED"},
    }
    provenance_digest = write_json(directory / "build-provenance.json", provenance)
    cloud["build_provenance"] = {"status": "PASS", "evidence": [{"path": "build-provenance.json", "sha256": provenance_digest, "evidence_class": "BUILD_PROVENANCE"}]}
    hardware = {name: {"evidence": []} for name in gate.HARDWARE_REQUIREMENTS}
    manifest = {
        "schema_version": 1,
        "release": {"version": "v0.2.0", "package_identifier": "com.ioscaffeinate.cli", "package_version": "0.2.0~rc1-1", "architecture": "iphoneos-arm"},
        "source": {
            "repository": "nghianguyen150612/iOS-Caffeinate", "branch": "release/p020-v02-integration",
            "commit_sha": source_sha,
            "tree_sha": tree_sha,
            "p020_base_branch": "main",
            "p020_base_sha": base_sha, "current_pr": None,
            "milestone_chain": chain,
        },
        "cloud_gates": cloud,
        "hardware_gates": hardware,
        "scope": {"out_of_scope_features": ["automatic_restart", "unattended_schedule_execution", "scheduled_deep_sleep_wake"]},
        "authorization": {
            "release_critical_issues_resolved": None, "operator_acceptance_review": None,
            "limitations_disclosed": None, "rollback_plan_review": None,
            "human_release_approval": None, "publication_authorization": None,
        },
        "reproducibility": "REPRODUCIBLE",
    }
    return manifest
