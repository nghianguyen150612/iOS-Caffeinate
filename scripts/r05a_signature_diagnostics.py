#!/usr/bin/env python3
"""Capture read-only Apple signature diagnostics for the R05A root-cause comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from macho_code_signature import CodeSignatureError, audit_code_signature
from verify_signed_candidate_macos import BINARIES, read_payload_binary


EXPECTED_SOURCE = "b2fdea8764ba08a8f60fe4d5acae2705dce7bd37"
FAILED_PACKAGE_SHA256 = "18631b8aff5c25607a88ba4fc28c945d1b8a552903950ec73dbae386d695807e"
FAILED_RECEIPT_SHA256 = "83b32e137ad903065a4d77c1968a7b9c7a0517f66506131e49bcdd3d2908ed0c"
STABLE_PACKAGE_SHA256 = "439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c"
EXPECTED_SIGNER_SHA256 = "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c"
EXPECTED_PROFILE_SHA256 = "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca"


class DiagnosticError(ValueError):
    """Diagnostic inputs do not match the authenticated R05 evidence set."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise DiagnosticError(f"{label} is missing, unsafe, or too large")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DiagnosticError(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DiagnosticError(f"{label} is not valid JSON") from None
    if not isinstance(value, dict):
        raise DiagnosticError(f"{label} root must be an object")
    return value


def run(command: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return {
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except OSError as error:
        return {"command": command, "exit_code": None, "stdout": "", "stderr": "", "error": str(error)}


def signature_audit(binary: bytes, name: str) -> dict[str, Any]:
    try:
        return audit_code_signature(binary, expected_identifier=name)
    except CodeSignatureError as error:
        return {
            "independent_code_directory_verified": False,
            "entitlements_exact_match": False,
            "adhoc_flag_present": False,
            "signature_kind": "UNSIGNED_OR_UNSUPPORTED",
            "device_signature_acceptance": "PENDING",
            "error": str(error),
        }


def _check_package_manifest(package: Path, source_sha: str, expected_sha: str) -> dict[str, Any]:
    if sha256_file(package) != expected_sha:
        raise DiagnosticError("failed R05 signed-input package SHA-256 differs from the recorded diagnostic input")
    manifest = read_json(Path(str(package) + ".manifest.json"), "failed signed-input package manifest")
    signing = manifest.get("signing")
    identity = manifest.get("package")
    if (manifest.get("source_commit_sha") != source_sha or manifest.get("source_tree_clean") is not True or
        not isinstance(signing, dict) or not isinstance(identity, dict) or
        identity.get("file") != package.name or identity.get("sha256") != expected_sha or
        signing.get("state") != "SIGNATURE_PRESENT" or signing.get("signature_verification") != "PENDING" or
        signing.get("profile_id") != "amethyst-ios12-rootful" or
        signing.get("profile_sha256") != EXPECTED_PROFILE_SHA256 or
        signing.get("signing_tool_version") != "2.1.5-procursus7" or
        signing.get("signing_tool_sha256") != EXPECTED_SIGNER_SHA256 or
        signing.get("embedded_entitlements") != "EXACT_MATCH"):
        raise DiagnosticError("failed signed-input manifest does not match exact R05 source, signer, and profile")
    return manifest


def _verify_failed_receipt(receipt_path: Path, package: Path, package_sha: str,
                           manifest: dict[str, Any], expected_receipt_sha: str) -> dict[str, Any]:
    receipt_sha = sha256_file(receipt_path)
    if receipt_sha != expected_receipt_sha:
        raise DiagnosticError("authentic R05 failure receipt SHA-256 does not match the recorded receipt")
    receipt = read_json(receipt_path, "R05 Apple signature failure receipt")
    expected_binaries = manifest["signing"]["final_binary_sha256"]
    results = receipt.get("binary_results")
    if (receipt.get("schema_version") != 1 or receipt.get("status") != "FAILED" or
        receipt.get("source_commit_sha") != EXPECTED_SOURCE or receipt.get("package_file") != package.name or
        receipt.get("package_sha256") != package_sha or receipt.get("host") != "macOS" or
        receipt.get("tool") != "/usr/bin/codesign" or
        not isinstance(results, list) or len(results) != 2):
        raise DiagnosticError("R05 failure receipt does not describe the authentic failed Apple run")
    by_name = {item.get("name"): item for item in results if isinstance(item, dict)}
    if set(by_name) != set(BINARIES):
        raise DiagnosticError("R05 failure receipt does not cover exactly the two candidate binaries")
    for name in BINARIES:
        item = by_name[name]
        text = (item.get("stdout", "") + item.get("stderr", "")).lower()
        if (item.get("binary_sha256") != expected_binaries.get(name) or item.get("exit_code") != 1 or
            item.get("command", [])[:4] != ["/usr/bin/codesign", "--verify", "--strict", "--verbose=2"] or
            "code object is not signed at all" not in text):
            raise DiagnosticError(f"R05 failure evidence is incomplete or mismatched for {name}")
    return receipt


def _collect_cases(unsigned_dir: Path, failed_package: Path, failed_manifest: dict[str, Any],
                   stable_package: Path, stable_sha: str) -> dict[str, dict[str, bytes]]:
    build_info = read_json(unsigned_dir / "build-info.json", "exact-source unsigned build record")
    if (build_info.get("source_commit_sha") != EXPECTED_SOURCE or build_info.get("source_tree_clean") is not True or
        build_info.get("signing_status") != "UNSIGNED"):
        raise DiagnosticError("unsigned control is not the authentic exact-source P020 build")
    unsigned: dict[str, bytes] = {}
    failed: dict[str, bytes] = {}
    stable: dict[str, bytes] = {}
    for name, relative in BINARIES.items():
        path = unsigned_dir / name
        if path.is_symlink() or not path.is_file():
            raise DiagnosticError(f"unsigned exact-source binary is missing or unsafe: {name}")
        unsigned[name] = path.read_bytes()
        failed[name] = read_payload_binary(failed_package, relative)
        stable[name] = read_payload_binary(stable_package, relative)
        if sha256_bytes(unsigned[name]) != failed_manifest["signing"]["source_binary_sha256"].get(name):
            raise DiagnosticError(f"unsigned build binary hash differs from the failed signed package source: {name}")
        if sha256_bytes(failed[name]) != failed_manifest["signing"]["final_binary_sha256"].get(name):
            raise DiagnosticError(f"failed package signed binary hash differs from its manifest: {name}")
    if sha256_file(stable_package) != stable_sha:
        raise DiagnosticError("historical v0.1.0 package SHA-256 does not match the stable release pin")
    return {
        "unsigned_exact_source": unsigned,
        "h003_ldid_signed_failed_candidate": failed,
        "v0.1.0_stable_historical_control": stable,
    }


def collect_diagnostics(*, failed_package: Path, failed_receipt: Path, unsigned_dir: Path,
                        stable_package: Path, output_dir: Path,
                        expected_source_sha: str = EXPECTED_SOURCE,
                        expected_package_sha: str = FAILED_PACKAGE_SHA256,
                        expected_receipt_sha: str = FAILED_RECEIPT_SHA256,
                        stable_package_sha: str = STABLE_PACKAGE_SHA256) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise DiagnosticError("R05A Apple tools diagnostics must run on macOS")
    if expected_source_sha != EXPECTED_SOURCE:
        raise DiagnosticError("source SHA must remain the authentic R05 baseline commit")
    if output_dir.exists() or output_dir.is_symlink():
        raise DiagnosticError("refusing to overwrite the R05A diagnostic output directory")
    output_dir.mkdir(parents=True, mode=0o700)

    failed_manifest = _check_package_manifest(failed_package, expected_source_sha, expected_package_sha)
    failure_receipt = _verify_failed_receipt(
        failed_receipt, failed_package, expected_package_sha, failed_manifest, expected_receipt_sha
    )
    cases = _collect_cases(unsigned_dir, failed_package, failed_manifest, stable_package, stable_package_sha)
    tools = {
        "codesign_version": run(["/usr/bin/codesign", "--version"]),
        "macos_version": run(["/usr/bin/sw_vers", "-productVersion"]),
        "xcode_version": run(["/usr/bin/xcodebuild", "-version"]),
        "otool_version": run(["/usr/bin/otool", "-V"]),
        "host_uname": platform.platform(),
    }
    for tool_name in ("codesign_version", "macos_version", "xcode_version", "otool_version"):
        if tools[tool_name]["exit_code"] != 0:
            raise DiagnosticError(f"required Apple diagnostic tool is unavailable: {tool_name}")

    cases_output: dict[str, Any] = {}
    binary_output: dict[tuple[str, str], Path] = {}
    for case_name, binaries in cases.items():
        cases_output[case_name] = {"binaries": {}}
        case_dir = output_dir / case_name
        case_dir.mkdir(mode=0o700)
        for name, binary in binaries.items():
            target = case_dir / name
            target.write_bytes(binary)
            target.chmod(0o700)
            binary_output[(case_name, name)] = target
            cases_output[case_name]["binaries"][name] = {
                "binary_sha256": sha256_file(target),
                "independent_signature_audit": signature_audit(binary, name),
                "commands": {},
            }

    # This ad hoc copy is a controlled comparison only; the original input bytes remain untouched.
    adhoc_case = "apple_native_adhoc_diagnostic_only"
    adhoc_dir = output_dir / adhoc_case
    adhoc_dir.mkdir(mode=0o700)
    profile = Path(__file__).resolve().parents[1] / "packaging/signing/profiles/amethyst-ios12-rootful.plist"
    if profile.is_symlink() or not profile.is_file() or sha256_file(profile) != EXPECTED_PROFILE_SHA256:
        raise DiagnosticError("the versioned approved profile is not the expected diagnostic profile")
    adhoc_binaries: dict[str, Path] = {}
    cases_output[adhoc_case] = {"purpose": "DIAGNOSTIC_ONLY_NO_RC_APPROVAL", "binaries": {}}
    for name, data in cases["unsigned_exact_source"].items():
        target = adhoc_dir / name
        target.write_bytes(data)
        target.chmod(0o700)
        sign_result = run([
            "/usr/bin/codesign", "--force", "--sign", "-", "--entitlements", str(profile), str(target),
        ])
        adhoc_binaries[name] = target
        cases_output[adhoc_case]["binaries"][name] = {
            "unsigned_source_sha256": sha256_bytes(data),
            "diagnostic_copy_sha256_after_signing": sha256_file(target),
            "apple_native_adhoc_signing": sign_result,
            "independent_signature_audit": signature_audit(target.read_bytes(), name),
            "commands": {},
        }

    for case_name, binaries in cases.items():
        for name, _data in binaries.items():
            path = binary_output[(case_name, name)]
            target = cases_output[case_name]["binaries"][name]
            target["commands"] = {
                "codesign_display": run(["/usr/bin/codesign", "-d", "--verbose=4", str(path)]),
                "codesign_verify": run(["/usr/bin/codesign", "--verify", "--strict", "--verbose=4", str(path)]),
                "otool_load_commands": run(["/usr/bin/otool", "-l", str(path)]),
                "file": run(["/usr/bin/file", str(path)]),
            }
    for name, path in adhoc_binaries.items():
        target = cases_output[adhoc_case]["binaries"][name]
        target["commands"] = {
            "codesign_display": run(["/usr/bin/codesign", "-d", "--verbose=4", str(path)]),
            "codesign_verify": run(["/usr/bin/codesign", "--verify", "--strict", "--verbose=4", str(path)]),
            "otool_load_commands": run(["/usr/bin/otool", "-l", str(path)]),
            "file": run(["/usr/bin/file", str(path)]),
        }

    receipt = {
        "schema_version": 1,
        "status": "R05A_DIAGNOSTIC_ONLY_NO_RC_APPROVAL",
        "source_commit_sha": expected_source_sha,
        "failed_input_package_sha256": expected_package_sha,
        "failed_input_receipt_sha256": expected_receipt_sha,
        "historical_v0_1_package_sha256": stable_package_sha,
        "signer": {
            "identity": "ProcursusTeam/ldid 2.1.5-procursus7",
            "sha256": EXPECTED_SIGNER_SHA256,
            "profile_id": "amethyst-ios12-rootful",
            "profile_sha256": EXPECTED_PROFILE_SHA256,
        },
        "evidence": {
            "failure_receipt_status": failure_receipt["status"],
            "failure_receipt_binary_results": failure_receipt["binary_results"],
            "case_results": cases_output,
            "tools": tools,
        },
        "physical_device_actions": "NONE",
        "release_candidate_approval": "NONE",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
    }
    receipt_path = output_dir / "R05A-APPLE-SIGNATURE-DIAGNOSTICS.json"
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failed-package", type=Path, required=True)
    parser.add_argument("--failed-receipt", type=Path, required=True)
    parser.add_argument("--unsigned-dir", type=Path, required=True)
    parser.add_argument("--stable-package", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-sha", default=EXPECTED_SOURCE)
    parser.add_argument("--failed-package-sha256", default=FAILED_PACKAGE_SHA256)
    parser.add_argument("--failed-receipt-sha256", default=FAILED_RECEIPT_SHA256)
    parser.add_argument("--stable-package-sha256", default=STABLE_PACKAGE_SHA256)
    args = parser.parse_args(argv)
    try:
        receipt = collect_diagnostics(
            failed_package=args.failed_package.absolute(), failed_receipt=args.failed_receipt.absolute(),
            unsigned_dir=args.unsigned_dir.absolute(), stable_package=args.stable_package.absolute(),
            output_dir=args.output_dir.absolute(), expected_source_sha=args.source_sha,
            expected_package_sha=args.failed_package_sha256,
            expected_receipt_sha=args.failed_receipt_sha256,
            stable_package_sha=args.stable_package_sha256,
        )
    except (DiagnosticError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"diagnostic_status={receipt['status']}")
    print(f"failed_input_package_sha256={receipt['failed_input_package_sha256']}")
    print(f"diagnostic_receipt={args.output_dir / 'R05A-APPLE-SIGNATURE-DIAGNOSTICS.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
