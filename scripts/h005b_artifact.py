#!/usr/bin/env python3
"""Sign and verify the standalone H005B diagnostic without packaging it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from macho_code_signature import CodeSignatureError, audit_code_signature
from signing_profile import (
    ADHOC_REQUIREMENTS_PROFILE,
    ADHOC_REQUIREMENTS_PROFILE_SHA256,
    ADHOC_REQUIREMENTS_SUPERBLOB,
    EXPECTED_ENTITLEMENTS,
    PROFILE_ID,
    SigningError,
    extract_entitlements,
    load_approved_profile,
    signer_identity,
    validate_signer,
)


SIGNER_SHA256 = "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c"
SIGNER_VERSION = "2.1.5-procursus7"
SIGNER_SOURCE = "aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef"
SIGNER_TREE = "e473e8213e9821e986ac488ced802f5ee2b4bbea"
PROFILE_SHA256 = "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca"
INSPECTOR_NAME = "ios-power-preflight-inspector"
ABI_REPORT_NAME = "ABI-INSPECTION.txt"
SIGNING_REPORT_NAME = "H005B-SIGNING-REPORT.json"
APPLE_REPORT_NAME = "H005B-APPLE-VERIFICATION.json"
MANIFEST_NAME = "H005B-SIGNED-MANIFEST.json"
CODESIGN_PATH = Path("/usr/bin/codesign")
MAX_REPORT_BYTES = 1024 * 1024


class ArtifactError(ValueError):
    """The signed inspector or its evidence does not match the H005B contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
        raise ArtifactError(f"{label} is missing, unsafe, or too large")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ArtifactError(f"{label} contains a duplicate JSON key")
            value[key] = item
        return value

    try:
        result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ArtifactError(f"{label} is not valid JSON") from None
    if not isinstance(result, dict):
        raise ArtifactError(f"{label} root must be a JSON object")
    return result


def write_json_new(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ArtifactError(f"refusing to overwrite existing evidence: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def parse_abi_report(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
        raise ArtifactError("ABI inspection report is missing, unsafe, or too large")
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in fields:
            raise ArtifactError(f"ABI inspection report repeats {key}")
        fields[key] = value
    required = {
        "target": "arm64-apple-ios12.0",
        "platform_load_command": "IOS",
        "minimum_os": "12.0",
        "linked_frameworks": "IOKit,CoreFoundation",
        "IOPMCopyAssertionsByProcess": "runtime_dlsym_only",
        "IOPMCopyAssertionsStatus": "runtime_dlsym_only",
        "assertion_mutation_imports": "NONE",
        "execution_timeout_seconds": "15",
        "runtime_behavior": "UNVERIFIED_ON_IOS_12.5.7",
        "device_transfer": "NOT_PERFORMED",
    }
    if not path.read_text(encoding="utf-8").startswith("H005_MACHO_ABI_INSPECTION_PASS\n"):
        raise ArtifactError("ABI report is not a passing H005 cross-build inspection")
    if any(fields.get(key) != value for key, value in required.items()):
        raise ArtifactError("ABI report does not match the required ARM64 iOS 12 read-only target")
    for key in ("iphoneos_sdk", "xcode", "clang"):
        if not fields.get(key):
            raise ArtifactError(f"ABI report is missing {key} toolchain identity")
    return fields


def validate_signer_provenance(path: Path) -> dict[str, Any]:
    receipt = read_json(path, "pinned H003 signer provenance")
    source = receipt.get("source")
    executable = receipt.get("executable")
    reproducibility = receipt.get("reproducibility")
    environment = receipt.get("build_environment")
    dependencies = receipt.get("dependencies")
    toolchain = receipt.get("toolchain")
    if not all(isinstance(item, dict) for item in (
        source, executable, reproducibility, environment, dependencies, toolchain,
    )):
        raise ArtifactError("H003 signer provenance is missing source, build, dependency, or toolchain data")
    assert all(isinstance(item, dict) for item in (
        source, executable, reproducibility, environment, dependencies, toolchain,
    ))
    if (receipt.get("result") != "VERIFIED" or
        source.get("commit") != SIGNER_SOURCE or source.get("tree") != SIGNER_TREE or
        source.get("independent_build_commit") != SIGNER_SOURCE or
        source.get("independent_build_tree") != SIGNER_TREE or
        executable.get("sha256") != SIGNER_SHA256 or
        executable.get("version") != SIGNER_VERSION or
        reproducibility.get("outcome") != "EXACT_MATCH" or
        reproducibility.get("build_1_sha256") != SIGNER_SHA256 or
        reproducibility.get("build_2_sha256") != SIGNER_SHA256):
        raise ArtifactError("H003 signer receipt does not bind the exact pinned reproducible Procursus ldid")
    return receipt


def validate_signature_audit(audit: dict[str, Any]) -> None:
    if (audit.get("independent_code_directory_verified") is not True or
        audit.get("entitlements_exact_match") is not True or
        audit.get("adhoc_flag_present") is not True or
        audit.get("signature_kind") != "ADHOC" or
        audit.get("requirements") != {"count": 0, "types": []}):
        raise ArtifactError("independent Mach-O audit failed exact H005B signature, entitlement, or requirement checks")


def sign_candidate(*, binary: Path, abi_report: Path, signer: Path,
                   signer_provenance: Path, source_sha: str, source_tree: str,
                   output_dir: Path) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or not re.fullmatch(r"[0-9a-f]{40}", source_tree):
        raise ArtifactError("source commit and tree must be full lowercase Git identities")
    if binary.is_symlink() or not binary.is_file() or binary.stat().st_size > 32 * 1024 * 1024:
        raise ArtifactError("cross-built inspector must be a bounded regular file")
    abi = parse_abi_report(abi_report)
    provenance = validate_signer_provenance(signer_provenance)
    if output_dir.is_symlink():
        raise ArtifactError("signed artifact output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ArtifactError("signed artifact output directory must be empty")

    profile = Path(__file__).resolve().parents[1] / "packaging/signing/profiles/amethyst-ios12-rootful.plist"
    try:
        entitlements, profile_hash = load_approved_profile(profile)
        ldid = validate_signer(signer.absolute())
        version, signer_hash = signer_identity(ldid, SIGNER_SHA256)
    except SigningError as error:
        raise ArtifactError(str(error)) from None
    if profile_hash != PROFILE_SHA256 or entitlements != EXPECTED_ENTITLEMENTS:
        raise ArtifactError("approved H005B entitlement profile bytes or value changed")
    if version != SIGNER_VERSION or signer_hash != SIGNER_SHA256:
        raise ArtifactError("H005B signer identity differs from the exact R05A pin")

    requirements_path = output_dir / "H005B-empty-requirements.superblob"
    requirements_path.write_bytes(ADHOC_REQUIREMENTS_SUPERBLOB)
    if sha256_file(requirements_path) != ADHOC_REQUIREMENTS_PROFILE_SHA256:
        raise ArtifactError("empty Requirements SuperBlob bytes differ from the reviewed R05A profile")
    candidate = output_dir / INSPECTOR_NAME
    shutil.copyfile(binary, candidate)
    candidate.chmod(0o700)
    command = [str(ldid), "-Cadhoc", f"-Q{requirements_path}", f"-S{profile}", str(candidate)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        raise ArtifactError(f"pinned ldid could not be executed: {type(error).__name__}") from None
    if result.returncode != 0:
        raise ArtifactError(f"pinned ldid signing failed with exit {result.returncode}")

    signed = candidate.read_bytes()
    try:
        audit = audit_code_signature(signed, expected_identifier=INSPECTOR_NAME)
        extracted = extract_entitlements(ldid, candidate)
    except (CodeSignatureError, SigningError) as error:
        raise ArtifactError(str(error)) from None
    validate_signature_audit(audit)
    if extracted != EXPECTED_ENTITLEMENTS:
        raise ArtifactError("pinned ldid entitlement extraction differs from the exact approved profile")

    shutil.copyfile(abi_report, output_dir / ABI_REPORT_NAME)
    shutil.copyfile(signer_provenance, output_dir / "H003-SIGNER-PROVENANCE.json")
    (output_dir / "source-commit.txt").write_text(source_sha + "\n", encoding="ascii")
    (output_dir / "source-tree.txt").write_text(source_tree + "\n", encoding="ascii")
    report = {
        "schema": "ioscaffeinate.h005b.signing-report.v1",
        "status": "SIGNED_PENDING_APPLE_VERIFICATION",
        "source": {"commit_sha": source_sha, "tree_sha": source_tree,
                   "unsigned_binary_sha256": sha256_file(binary)},
        "signed_binary": {"file": INSPECTOR_NAME, "sha256": sha256_bytes(signed)},
        "signing": {
            "tool": "ProcursusTeam ldid", "version": version, "sha256": signer_hash,
            "signer_source_commit": SIGNER_SOURCE, "signer_source_tree": SIGNER_TREE,
            "signer_provenance_sha256": sha256_file(signer_provenance),
            "signer_provenance": {
                key: provenance[key] for key in (
                    "source", "build_environment", "dependencies", "toolchain", "reproducibility",
                ) if key in provenance
            },
            "profile_id": PROFILE_ID, "profile_sha256": profile_hash,
            "entitlements": EXPECTED_ENTITLEMENTS,
            "requirements_profile": ADHOC_REQUIREMENTS_PROFILE,
            "requirements_sha256": ADHOC_REQUIREMENTS_PROFILE_SHA256,
            "command": ["ldid", "-Cadhoc", "-Q<empty-requirements>",
                        "-S<amethyst-ios12-rootful>", INSPECTOR_NAME],
            "exit_code": result.returncode,
            "stdout": result.stdout[-4096:], "stderr": result.stderr[-4096:],
            "independent_signature_audit": audit,
            "ldid_entitlement_extraction": "EXACT_MATCH",
        },
        "build": {key: abi[key] for key in (
            "iphoneos_sdk", "xcode", "clang", "target", "platform_load_command", "minimum_os",
            "IOPMCopyAssertionsByProcess", "IOPMCopyAssertionsStatus", "assertion_mutation_imports",
            "execution_timeout_seconds",
        )},
        "scope": {
            "package_included": False, "daemon_required": False,
            "device_transfer": "NOT_PERFORMED", "device_execution": "NOT_PERFORMED",
            "device_acceptance": "PENDING_SEPARATE_AUTHORIZATION",
        },
    }
    write_json_new(output_dir / SIGNING_REPORT_NAME, report)
    requirements_path.unlink()
    return report


def _safe_output(text: str, binary: Path) -> str:
    return text.replace(str(binary), "<signed-candidate>")[-4096:]


def verify_candidate(*, candidate_dir: Path, source_sha: str, source_tree: str,
                     output_dir: Path) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise ArtifactError("Apple strict signature verification must run on macOS")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or not re.fullmatch(r"[0-9a-f]{40}", source_tree):
        raise ArtifactError("source commit and tree must be full lowercase Git identities")
    if candidate_dir.is_symlink() or not candidate_dir.is_dir():
        raise ArtifactError("pre-Apple candidate directory is missing or unsafe")
    source_commit_path = candidate_dir / "source-commit.txt"
    source_tree_path = candidate_dir / "source-tree.txt"
    for path, expected, label in (
        (source_commit_path, source_sha, "source commit"),
        (source_tree_path, source_tree, "source tree"),
    ):
        if path.is_symlink() or not path.is_file() or path.read_text(encoding="ascii").strip() != expected:
            raise ArtifactError(f"H005B artifact {label} identity does not match the reviewed source")
    candidate = candidate_dir / INSPECTOR_NAME
    if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 32 * 1024 * 1024:
        raise ArtifactError("signed inspector candidate is missing, unsafe, or too large")
    signing_path = candidate_dir / SIGNING_REPORT_NAME
    signing = read_json(signing_path, "H005B signing report")
    if (signing.get("status") != "SIGNED_PENDING_APPLE_VERIFICATION" or
        signing.get("schema") != "ioscaffeinate.h005b.signing-report.v1"):
        raise ArtifactError("H005B signing report is not pending Apple verification")
    source = signing.get("source")
    binary_record = signing.get("signed_binary")
    if (not isinstance(source, dict) or not isinstance(binary_record, dict) or
        source.get("commit_sha") != source_sha or source.get("tree_sha") != source_tree or
        binary_record.get("file") != INSPECTOR_NAME or
        binary_record.get("sha256") != sha256_file(candidate)):
        raise ArtifactError("signed candidate hash or source identity does not match its signing report")
    abi_path = candidate_dir / ABI_REPORT_NAME
    abi = parse_abi_report(abi_path)
    provenance_path = candidate_dir / "H003-SIGNER-PROVENANCE.json"
    provenance = validate_signer_provenance(provenance_path)
    signing_fields = signing.get("signing")
    if not isinstance(signing_fields, dict):
        raise ArtifactError("H005B signing report is missing signing inputs")
    if (signing_fields.get("version") != SIGNER_VERSION or
        signing_fields.get("sha256") != SIGNER_SHA256 or
        signing_fields.get("profile_id") != PROFILE_ID or
        signing_fields.get("profile_sha256") != PROFILE_SHA256 or
        signing_fields.get("entitlements") != EXPECTED_ENTITLEMENTS or
        signing_fields.get("requirements_profile") != ADHOC_REQUIREMENTS_PROFILE or
        signing_fields.get("requirements_sha256") != ADHOC_REQUIREMENTS_PROFILE_SHA256 or
        signing_fields.get("signer_provenance_sha256") != sha256_file(provenance_path) or
        provenance.get("executable", {}).get("sha256") != SIGNER_SHA256):
        raise ArtifactError("signing report differs from the approved R05A signer/profile contract")

    if output_dir.is_symlink():
        raise ArtifactError("final artifact directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ArtifactError("final artifact directory must be empty")
    final_binary = output_dir / INSPECTOR_NAME
    shutil.copyfile(candidate, final_binary)
    final_binary.chmod(0o700)
    codesign = CODESIGN_PATH
    if not codesign.is_file() or not os.access(codesign, os.X_OK):
        raise ArtifactError("Apple codesign is unavailable at /usr/bin/codesign")
    command = [str(codesign), "--verify", "--strict", "--verbose=4", str(final_binary)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        raise ArtifactError(f"Apple codesign could not be executed: {type(error).__name__}") from None
    apple_record = {
        "schema": "ioscaffeinate.h005b.apple-verification.v1",
        "command": [str(codesign), "--verify", "--strict", "--verbose=4", "<signed-candidate>"],
        "exit_code": result.returncode,
        "stdout": _safe_output(result.stdout, final_binary),
        "stderr": _safe_output(result.stderr, final_binary),
        "status": "VERIFIED" if result.returncode == 0 else "FAILED",
        "binary_sha256": sha256_file(final_binary),
    }
    write_json_new(output_dir / APPLE_REPORT_NAME, apple_record)
    if result.returncode != 0:
        raise ArtifactError(f"Apple strict codesign verification failed with exit {result.returncode}")

    try:
        independent = audit_code_signature(final_binary.read_bytes(),
                                            expected_identifier=INSPECTOR_NAME)
    except CodeSignatureError as error:
        raise ArtifactError(f"independent Mach-O signature inspection failed: {error}") from None
    validate_signature_audit(independent)
    signing_record = {
        **signing_fields,
        "independent_signature_audit": independent,
        "apple_strict_verification": "VERIFIED",
        "apple_codesign_exit_code": result.returncode,
    }
    manifest = {
        "schema": "ioscaffeinate.h005b.signed-inspector-manifest.v1",
        "artifact_name": "H005B-SIGNED-DEVICE-UNVERIFIED",
        "artifact_file": INSPECTOR_NAME,
        "artifact_sha256": sha256_file(final_binary),
        "source": {
            "repository": "https://github.com/nghianguyen150612/iOS-Caffeinate",
            "commit_sha": source_sha, "tree_sha": source_tree,
            "unsigned_binary_sha256": source.get("unsigned_binary_sha256"),
        },
        "build": {key: abi[key] for key in (
            "iphoneos_sdk", "xcode", "clang", "target", "platform_load_command", "minimum_os",
            "IOPMCopyAssertionsByProcess", "IOPMCopyAssertionsStatus", "assertion_mutation_imports",
            "execution_timeout_seconds",
        )},
        "signing": {
            "tool": "ProcursusTeam ldid", "version": SIGNER_VERSION,
            "sha256": SIGNER_SHA256, "signer_source_commit": SIGNER_SOURCE,
            "signer_source_tree": SIGNER_TREE,
            "signer_provenance_sha256": sha256_file(provenance_path),
            "signer_provenance": {
                key: provenance[key] for key in (
                    "source", "build_environment", "dependencies", "toolchain", "reproducibility",
                ) if key in provenance
            },
            "profile_id": PROFILE_ID, "profile_sha256": PROFILE_SHA256,
            "entitlements": EXPECTED_ENTITLEMENTS,
            "requirements_profile": ADHOC_REQUIREMENTS_PROFILE,
            "requirements_sha256": ADHOC_REQUIREMENTS_PROFILE_SHA256,
            "independent_signature_audit": independent,
            "ldid_entitlement_extraction": "EXACT_MATCH",
        },
        "verification": {
            "apple_codesign": apple_record,
            "independent_macho_audit": "PASS",
            "device_signature_acceptance": "NOT_VERIFIED",
        },
        "scope": {
            "package_included": False, "daemon_required": False,
            "device_transfer": "NOT_PERFORMED", "device_execution": "NOT_PERFORMED",
            "device_acceptance": "PENDING_SEPARATE_AUTHORIZATION",
        },
        "files": {
            ABI_REPORT_NAME: sha256_file(abi_path),
            SIGNING_REPORT_NAME: sha256_file(signing_path),
            "H003-SIGNER-PROVENANCE.json": sha256_file(provenance_path),
            APPLE_REPORT_NAME: sha256_file(output_dir / APPLE_REPORT_NAME),
            "source-commit.txt": sha256_file(source_commit_path),
            "source-tree.txt": sha256_file(source_tree_path),
        },
    }
    write_json_new(output_dir / MANIFEST_NAME, manifest)
    shutil.copyfile(abi_path, output_dir / ABI_REPORT_NAME)
    shutil.copyfile(signing_path, output_dir / SIGNING_REPORT_NAME)
    shutil.copyfile(provenance_path, output_dir / "H003-SIGNER-PROVENANCE.json")
    shutil.copyfile(source_commit_path, output_dir / "source-commit.txt")
    shutil.copyfile(source_tree_path, output_dir / "source-tree.txt")
    sums = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            sums.append(f"{sha256_file(path)}  {path.name}")
    (output_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    sign = subparsers.add_parser("sign")
    sign.add_argument("--binary", required=True, type=Path)
    sign.add_argument("--abi-report", required=True, type=Path)
    sign.add_argument("--signer", required=True, type=Path)
    sign.add_argument("--signer-provenance", required=True, type=Path)
    sign.add_argument("--source-sha", required=True)
    sign.add_argument("--source-tree", required=True)
    sign.add_argument("--output-dir", required=True, type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--candidate-dir", required=True, type=Path)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--source-tree", required=True)
    verify.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "sign":
            report = sign_candidate(
                binary=args.binary.absolute(), abi_report=args.abi_report.absolute(),
                signer=args.signer.absolute(), signer_provenance=args.signer_provenance.absolute(),
                source_sha=args.source_sha, source_tree=args.source_tree,
                output_dir=args.output_dir.absolute(),
            )
            print(f"H005B_SIGNED_PENDING_APPLE_VERIFICATION {report['signed_binary']['sha256']}")
        else:
            manifest = verify_candidate(
                candidate_dir=args.candidate_dir.absolute(), source_sha=args.source_sha,
                source_tree=args.source_tree, output_dir=args.output_dir.absolute(),
            )
            print(f"H005B_SIGNED_ARTIFACT_VERIFIED {manifest['artifact_sha256']}")
    except (ArtifactError, OSError, CodeSignatureError, SigningError, subprocess.SubprocessError) as error:
        print(f"H005B_ARTIFACT_FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
