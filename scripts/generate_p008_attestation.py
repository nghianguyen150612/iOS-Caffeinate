#!/usr/bin/env python3
"""Generate exact-source CI attestation and release-candidate readiness evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_SHA = "c8512508a80be5fc09d0c62b2e26877717af23df"
REQUIRED_JOBS = {
    "linux-protocol": "NEEDS_LINUX_PROTOCOL_RESULT",
    "ios-cross-build": "NEEDS_IOS_CROSS_BUILD_RESULT",
    "ios-artifact-inspection": "NEEDS_IOS_ARTIFACT_INSPECTION_RESULT",
    "ios-rootful-package": "NEEDS_IOS_ROOTFUL_PACKAGE_RESULT",
}


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"ERROR: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_count(path: Path, label: str) -> int:
    if not path.is_file():
        fail(f"missing {label} test report: {path}")
    contents = path.read_text(encoding="utf-8")
    match = re.search(r"Ran (\d+) tests? in ", contents)
    if not match or re.search(r"(?m)^OK$", contents) is None:
        fail(f"{label} test report does not contain a successful unittest result")
    return int(match.group(1))


def validate_manifest_contract(manifest: dict, schema: dict) -> None:
    required = set(schema.get("required", []))
    if set(manifest) != required:
        fail("release-candidate manifest fields do not match the versioned schema")
    if manifest.get("manifest_version") != 1:
        fail("unsupported release-candidate manifest version")
    if manifest["source"]["integration_baseline_sha"] != BASELINE_SHA:
        fail("release-candidate manifest integration baseline does not match P008")
    for digest in (
        manifest["source"]["commit_sha"],
        manifest["source"]["integration_baseline_sha"],
        manifest["artifacts"]["cli"]["sha256"],
        manifest["artifacts"]["daemon"]["sha256"],
        manifest["artifacts"]["debian_package"]["sha256"],
    ):
        if not re.fullmatch(r"[0-9a-f]{40}" if len(digest) == 40 else r"[0-9a-f]{64}", digest):
            fail("release-candidate manifest contains an invalid commit or SHA-256")
    if set(manifest["ci_jobs"]) != set(REQUIRED_JOBS) or any(
        value not in ("PASS", "FAIL", "PENDING", "BLOCKED", "NOT_APPLICABLE")
        for value in manifest["ci_jobs"].values()
    ):
        fail("release-candidate manifest CI jobs do not match the schema")
    if manifest["artifacts"]["debian_package"]["architecture"] != "iphoneos-arm":
        fail("release-candidate package architecture does not match the schema")
    if manifest["hardware_validation_status"] != "PENDING" or manifest["release_authorization_status"] != "NOT_AUTHORIZED":
        fail("CI must not pass hardware gates or authorize a release")


def main() -> int:
    dist = ROOT / "dist"
    package_dir = dist / "package"
    build_info_path = dist / "build-info.json"
    inspection_path = dist / "inspection.txt"
    validation_path = package_dir / "validation.txt"
    linux_report = dist / "linux-evidence" / "integration-report.txt"
    packaging_report = package_dir / "packaging-tests.txt"

    for path in (build_info_path, inspection_path, validation_path):
        if not path.is_file():
            fail(f"missing required build/inspection output: {path}")
    build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
    if build_info.get("target_triple") != "arm64-apple-ios12.0" or build_info.get("signing_status") != "UNSIGNED":
        fail("iOS build metadata does not match the unsigned iOS 12 ARM64 target")
    if "PASS: both unsigned iOS 12.0 ARM64 device executables inspected" not in inspection_path.read_text(encoding="utf-8"):
        fail("official iOS artifact inspection did not report PASS")
    validation = validation_path.read_text(encoding="utf-8")
    required_package_evidence = (
        "package=com.ioscaffeinate.cli",
        "version=0.1.0-1",
        "architecture=iphoneos-arm",
        "result=PASS",
        "package_installation=NOT-PERFORMED",
    )
    if any(item not in validation for item in required_package_evidence):
        fail("package inspection did not pass or claims installation was performed")

    source_sha = os.environ.get("P008_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    checked_out_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if checked_out_sha != source_sha:
        fail(f"attestation checkout {checked_out_sha} does not match source SHA {source_sha}")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    workflow = os.environ.get("GITHUB_WORKFLOW", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or not run_id or not repository or not workflow:
        fail("GitHub source or workflow identity is unavailable")

    jobs: dict[str, str] = {}
    for job, env_name in REQUIRED_JOBS.items():
        result = os.environ.get(env_name, "")
        if result != "success":
            fail(f"required CI job {job} did not succeed (result={result or 'missing'})")
        jobs[job] = "PASS"

    integration_tests = test_count(linux_report, "Linux integration")
    packaging_tests = test_count(packaging_report, "packaging")
    ios_hashes: dict[str, str] = {}
    sums = dist / "SHA256SUMS"
    for line in sums.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not match:
            fail("iOS SHA256SUMS contains an invalid line")
        ios_hashes[match.group(2)] = match.group(1)
    if set(ios_hashes) != {"ios-caffeinate", "ios-caffeinated"}:
        fail("iOS SHA256SUMS does not cover exactly the CLI and daemon")
    for name, expected in ios_hashes.items():
        if sha256(dist / name) != expected:
            fail(f"iOS artifact checksum mismatch for {name}")

    packages = sorted(package_dir.glob("*.deb"))
    if len(packages) != 1:
        fail(f"expected exactly one Debian package, found {len(packages)}")
    package = packages[0]
    package_sha = sha256(package)
    package_report = next(package_dir.glob("*.manifest.txt"), None)
    if package_report is None:
        fail("package build manifest is missing")
    package_metadata = package_report.read_text(encoding="utf-8")
    if f"artifact_sha256: {package_sha}" not in package_metadata:
        fail("package build manifest hash does not match the archive")
    if "signing: UNSIGNED-DEVICE-UNVERIFIED" not in package_metadata:
        fail("package is not accurately identified as unsigned/device-unverified")
    sidecar = Path(str(package) + ".sha256")
    if not sidecar.is_file() or f"{package_sha}  {package.name}" not in sidecar.read_text(encoding="utf-8"):
        fail("package SHA-256 sidecar is absent or inconsistent")

    package_version = (ROOT / "packaging/rootful/VERSION").read_text(encoding="utf-8").strip()
    if package_version != "0.1.0-1":
        fail(f"unexpected P008 package version: {package_version}")
    try:
        product_version = package_version.rsplit("-", 1)[0]
        int(product_version.split(".")[-1])
    except (ValueError, IndexError):
        fail("package version cannot be interpreted as a product version")

    workflow_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repository}/actions/runs/{run_id}"
    manifest = {
        "manifest_version": 1,
        "product": {"name": "iOS-Caffeinate", "version": product_version},
        "package_version": package_version,
        "source": {
            "repository": repository,
            "commit_sha": source_sha,
            "integration_baseline_sha": BASELINE_SHA,
        },
        "build": {
            "workflow_name": workflow,
            "workflow_id": run_id,
            "workflow_url": workflow_url,
            "toolchain": {
                "xcode": build_info["xcode"],
                "sdk": build_info["sdk"],
                "clang": build_info["clang"],
            },
            "target_platform": build_info["target_platform"],
            "device_executable_architecture": build_info["target_triple"],
            "minimum_ios_version": build_info["minimum_ios_version"],
        },
        "artifacts": {
            "cli": {"name": "ios-caffeinate", "sha256": ios_hashes["ios-caffeinate"]},
            "daemon": {"name": "ios-caffeinated", "sha256": ios_hashes["ios-caffeinated"]},
            "debian_package": {
                "name": package.name,
                "sha256": package_sha,
                "architecture": "iphoneos-arm",
            },
        },
        "signing_status": "UNSIGNED / DEVICE-UNVERIFIED",
        "ci_validation_status": "PASS",
        "ci_jobs": jobs,
        "test_counts": {"linux_integration": integration_tests, "packaging": packaging_tests},
        "hardware_validation_status": "PENDING",
        "outstanding_safety_gates": [
            "iOS binary execution on the target device",
            "code-signature acceptance by the target jailbreak",
            "IOKit assertion acquisition and release",
            "bounded trial expiry and STOP/SIGTERM cleanup",
            "display-locked LAN SSH observation",
            "display-locked Tailscale SSH observation",
            "battery and thermal observation",
            "physical recovery access",
            "package installation and rollback",
            "scheduled wake remains UNVERIFIED",
        ],
        "release_authorization_status": "NOT_AUTHORIZED",
    }

    (package_dir / "release-candidate.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    schema_path = ROOT / "docs/schemas/p008-release-candidate-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validate_manifest_contract(manifest, schema)

    report_lines = [
        "# P008 Exact-SHA CI Attestation",
        "",
        f"Source SHA: `{source_sha}`",
        f"Integration baseline: `{BASELINE_SHA}`",
        f"Workflow: [{workflow} run {run_id}]({workflow_url})",
        "",
        "## Job results",
        "",
        "| Job | Result |",
        "|---|---|",
    ]
    report_lines.extend(f"| `{job}` | {result} |" for job, result in jobs.items())
    report_lines.extend([
        "",
        "## Regression and artifacts",
        "",
        f"- Linux integration tests: {integration_tests} passed.",
        f"- Packaging tests: {packaging_tests} passed.",
        f"- CLI SHA-256: `{ios_hashes['ios-caffeinate']}`",
        f"- Daemon SHA-256: `{ios_hashes['ios-caffeinated']}`",
        f"- Debian package SHA-256: `{package_sha}`",
        "- Signing: UNSIGNED / DEVICE-UNVERIFIED.",
        "- Hardware validation: PENDING; no device acceptance is inferred from CI.",
        "- Release authorization: NOT AUTHORIZED.",
        "",
    ])
    (package_dir / "P008-CI-ATTESTATION.md").write_text("\n".join(report_lines), encoding="utf-8")

    readiness = [
        "# P008 Release Readiness Matrix",
        "",
        f"Evidence source: [{source_sha[:12]} / workflow {run_id}]({workflow_url})",
        "",
        "## Engineering",
        "",
        "| Gate | Status | Evidence |",
        "|---|---|---|",
        "| Source integration and audit | PASS | P008 audit at this source SHA |",
        "| CLI/daemon contracts and C11 Linux regression | PASS | Linux protocol job; see test count |",
        "| iOS ARM64 cross-build and inspection | PASS | Official iPhoneOS SDK and artifact inspection jobs |",
        "| Rootful package and archive inspection | PASS | Package job; unsigned, device-unverified |",
        "| Security regression | PASS | Source-level and deterministic mock checks only |",
        "| Documentation and release manifest | PASS | Repository docs plus this attestation |",
        "",
        "## Device",
        "",
        "| Gate | Status |",
        "|---|---|",
        "| iOS 12.5.7 binary execution | PENDING |",
        "| Code-signature acceptance | PENDING |",
        "| IOKit assertion acquisition | PENDING |",
        "| IOKit assertion release | PENDING |",
        "| Bounded trial expiry | PENDING |",
        "| STOP/SIGTERM cleanup | PENDING |",
        "| Display-locked LAN SSH | PENDING |",
        "| Display-locked Tailscale SSH | PENDING |",
        "| Battery observation | PENDING |",
        "| Thermal observation | PENDING |",
        "| Physical recovery | PENDING |",
        "| Installation and rollback | PENDING |",
        "| Scheduled wake | PENDING | UNVERIFIED capability |",
        "",
        "Release authorization: BLOCKED pending physical device acceptance. No production release is authorized.",
        "",
    ]
    (package_dir / "P008-RELEASE-READINESS.md").write_text("\n".join(readiness), encoding="utf-8")
    print(f"P008 manifest: {package_dir / 'release-candidate.json'}")
    print(f"P008 exact-SHA attestation: {package_dir / 'P008-CI-ATTESTATION.md'}")
    print(f"P008 readiness matrix: {package_dir / 'P008-RELEASE-READINESS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
