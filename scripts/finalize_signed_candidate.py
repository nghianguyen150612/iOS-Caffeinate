#!/usr/bin/env python3
"""Bind a successful macOS codesign receipt into a signed Debian candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.2.0~rc1-1"
EXPECTED_PACKAGE = "com.ioscaffeinate.cli"
EXPECTED_ARCH = "iphoneos-arm"
EXPECTED_PROFILE = "amethyst-ios12-rootful"
EXPECTED_PROFILE_SHA256 = "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca"
BINARIES = {
    "ios-caffeinate": "usr/local/bin/ios-caffeinate",
    "ios-caffeinated": "usr/local/bin/ios-caffeinated",
}


class FinalizationError(ValueError):
    """The signed package or host verification receipt is not safe to finalize."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise FinalizationError(f"{label} must be a bounded regular file")
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise FinalizationError(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise FinalizationError(f"{label} is not valid JSON") from None
    if not isinstance(value, dict):
        raise FinalizationError(f"{label} root must be an object")
    return value


def require_regular(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if PurePosixPath(relative).is_absolute() or not parts or ".." in parts:
        raise FinalizationError("package metadata path is unsafe")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise FinalizationError(f"refusing a symlink in package metadata path: {relative}")
    if not current.is_file():
        raise FinalizationError(f"package metadata file is missing: {relative}")
    return current


def validate_receipt(package: Path, package_record: dict[str, Any], receipt: dict[str, Any], source_sha: str) -> tuple[str, dict[str, str]]:
    package_sha = sha256(package)
    signing = package_record.get("signing")
    package_identity = package_record.get("package")
    if not isinstance(signing, dict) or not isinstance(package_identity, dict):
        raise FinalizationError("signed package manifest is missing package/signing records")
    if (package_record.get("source_commit_sha") != source_sha or
        package_record.get("source_tree_clean") is not True or
        package_identity.get("file") != package.name or package_identity.get("sha256") != package_sha or
        package_record.get("package_identifier") != EXPECTED_PACKAGE or
        package_record.get("package_version") != EXPECTED_VERSION or
        package_record.get("architecture") != EXPECTED_ARCH):
        raise FinalizationError("signed package identity, source, or hash does not match the exact candidate")
    if (signing.get("state") != "SIGNATURE_PRESENT" or signing.get("profile_id") != EXPECTED_PROFILE or
        signing.get("profile_sha256") != EXPECTED_PROFILE_SHA256 or
        signing.get("signing_tool_version") != "2.1.5-procursus7" or
        signing.get("signing_tool_sha256") != "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c" or
        signing.get("embedded_entitlements") != "EXACT_MATCH" or
        signing.get("signature_verification") != "PENDING"):
        raise FinalizationError("input candidate is not the expected signed, entitlement-checked package awaiting host verification")
    if (receipt.get("schema_version") != 1 or receipt.get("status") != "VERIFIED" or
        receipt.get("source_commit_sha") != source_sha or receipt.get("package_file") != package.name or
        receipt.get("package_sha256") != package_sha or receipt.get("host") != "macOS" or
        receipt.get("tool") != "/usr/bin/codesign" or
        receipt.get("method") != "codesign --verify --strict --verbose=2"):
        raise FinalizationError("macOS signature-integrity receipt does not match the signed package")
    results = receipt.get("binary_results")
    if not isinstance(results, list) or len(results) != 2:
        raise FinalizationError("macOS signature-integrity receipt must cover both package executables")
    by_name = {item.get("name"): item for item in results if isinstance(item, dict)}
    if set(by_name) != set(BINARIES):
        raise FinalizationError("macOS signature-integrity receipt names unexpected executables")
    final_hashes = signing.get("final_binary_sha256")
    if not isinstance(final_hashes, dict) or set(final_hashes) != set(BINARIES):
        raise FinalizationError("signed package executable hashes are missing")
    verified: dict[str, str] = {}
    for name, relative in BINARIES.items():
        item = by_name[name]
        if (item.get("package_path") != relative or item.get("exit_code") != 0 or
            item.get("binary_sha256") != final_hashes.get(name) or
            item.get("command", [])[:4] != ["/usr/bin/codesign", "--verify", "--strict", "--verbose=2"]):
            raise FinalizationError(f"macOS signature-integrity result is invalid for {name}")
        verified[name] = item["binary_sha256"]
    return package_sha, verified


def update_payload_metadata(root: Path, receipt: dict[str, Any], receipt_sha: str,
                            source_sha: str, original_package_sha: str,
                            expected_binary_hashes: dict[str, str]) -> None:
    for name, relative in BINARIES.items():
        binary = require_regular(root, relative)
        if sha256(binary) != expected_binary_hashes[name]:
            raise FinalizationError(f"signed executable changed after macOS verification: {name}")

    build_path = require_regular(root, "usr/share/ioscaffeinate/package-build.json")
    build = read_json(build_path, "embedded package-build record")
    signing = build.get("signing")
    if (build.get("source_commit_sha") != source_sha or not isinstance(signing, dict) or
        signing.get("signature_verification") != "PENDING" or
        signing.get("profile_id") != EXPECTED_PROFILE or
        signing.get("profile_sha256") != EXPECTED_PROFILE_SHA256):
        raise FinalizationError("embedded package-build record is not the expected Linux-signed candidate")
    final_hashes = signing.get("final_binary_sha256")
    if final_hashes != expected_binary_hashes:
        raise FinalizationError("embedded executable hashes differ from the macOS verification receipt")
    signing["signature_integrity"] = {
        "status": "VERIFIED",
        "tool": receipt["tool"],
        "method": receipt["method"],
        "receipt_sha256": receipt_sha,
        "verified_input_package_sha256": original_package_sha,
        "binary_sha256": expected_binary_hashes,
        "metadata_only_repackaging": True,
    }
    signing["signature_verification"] = "SIGNATURE_VERIFIED"
    build_path.write_text(json.dumps(build, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    state_path = require_regular(root, "usr/share/ioscaffeinate/SIGNING-STATE")
    lines = state_path.read_text(encoding="utf-8").splitlines()
    matches = [index for index, line in enumerate(lines) if line.startswith("signature_verification=")]
    if len(matches) != 1 or lines[matches[0]] != "signature_verification=PENDING":
        raise FinalizationError("embedded signing-state record is not pending macOS verification")
    lines[matches[0]] = "signature_verification=SIGNATURE_VERIFIED"
    state_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    sums_path = require_regular(root, "usr/share/ioscaffeinate/SHA256SUMS")
    listed: list[str] = []
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"[0-9a-f]{64}  ([A-Za-z0-9_./+-]+)", line)
        if match is None:
            raise FinalizationError("embedded payload checksum manifest is malformed")
        relative = match.group(1)
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or relative == "usr/share/ioscaffeinate/SHA256SUMS":
            raise FinalizationError("embedded payload checksum path is unsafe")
        listed.append(relative)
    if len(listed) != len(set(listed)):
        raise FinalizationError("embedded payload checksum manifest has duplicate paths")
    required = {"usr/share/ioscaffeinate/package-build.json", "usr/share/ioscaffeinate/SIGNING-STATE"}
    if not required.issubset(set(listed)):
        raise FinalizationError("embedded payload checksum manifest omits signing metadata")
    records = []
    for relative in sorted(listed):
        path = require_regular(root, relative)
        records.append(f"{sha256(path)}  {relative}")
    sums_path.write_text("\n".join(records) + "\n", encoding="utf-8")


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    package = args.package.absolute()
    receipt_path = args.signature_receipt.absolute()
    signer = args.ldid.absolute()
    output_dir = args.output_dir.absolute()
    if package.is_symlink() or not package.is_file():
        raise FinalizationError("input signed package must be a regular, non-symlink file")
    if not signer.is_file() or signer.is_symlink() or not os.access(signer, os.X_OK):
        raise FinalizationError("pinned H003 signer must be a regular executable")
    if output_dir.is_symlink():
        raise FinalizationError("final output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise FinalizationError("final output directory must be empty")

    package_manifest_path = package.parent / f"{package.name}.manifest.json"
    package_text_path = package.parent / f"{package.name}.manifest.txt"
    package_sums_path = package.parent / f"{package.name}.files.sha256"
    package_hash_path = package.parent / f"{package.name}.sha256"
    expected_filename = "ioscaffeinate_0.2.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb"
    if package.name != expected_filename:
        raise FinalizationError("input package filename is not the requested v0.2.0-rc1 candidate")
    for path, label in ((package_text_path, "input text manifest"),
                        (package_sums_path, "input payload inventory"),
                        (package_hash_path, "input package SHA-256 sidecar")):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise FinalizationError(f"{label} is missing, unsafe, or too large")
    package_record = read_json(package_manifest_path, "signed package manifest")
    receipt = read_json(receipt_path, "macOS signature-integrity receipt")
    original_sha, binary_hashes = validate_receipt(package, package_record, receipt, args.source_sha)
    if package_hash_path.read_text(encoding="utf-8") != f"{original_sha}  {package.name}\n":
        raise FinalizationError("input package SHA-256 sidecar does not match the signed candidate")
    receipt_sha = sha256(receipt_path)
    validation_script = ROOT / "scripts/validate_rootful_package.py"
    initial_validation = subprocess.run(
        [sys.executable, str(validation_script), str(package), "--expected-version", EXPECTED_VERSION,
         "--ldid", str(signer)], capture_output=True, text=True, check=False,
    )
    if initial_validation.returncode != 0:
        raise FinalizationError("input package failed pinned-signer validation: " + (initial_validation.stderr.strip() or initial_validation.stdout.strip()))

    epoch_match = re.search(r"(?m)^source_date_epoch: ([0-9]+)$", package_text_path.read_text(encoding="utf-8"))
    if epoch_match is None:
        raise FinalizationError("input package manifest is missing SOURCE_DATE_EPOCH")
    source_epoch = epoch_match.group(1)

    with tempfile.TemporaryDirectory(prefix="ioscaffeinate-finalize-") as temporary:
        root = Path(temporary) / "root"
        extract = subprocess.run(
            ["dpkg-deb", "--raw-extract", str(package), str(root)],
            capture_output=True, text=True, check=False,
        )
        if extract.returncode != 0:
            raise FinalizationError("dpkg-deb could not safely extract the signed candidate")
        embedded_sums = require_regular(root, "usr/share/ioscaffeinate/SHA256SUMS")
        if package_sums_path.read_text(encoding="utf-8") != embedded_sums.read_text(encoding="utf-8"):
            raise FinalizationError("input payload checksum sidecar differs from the embedded manifest")
        update_payload_metadata(root, receipt, receipt_sha, args.source_sha, original_sha, binary_hashes)
        for path in root.rglob("*"):
            if path.is_symlink():
                continue
            if path.is_file():
                os.utime(path, (int(source_epoch), int(source_epoch)))
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_dir() and not path.is_symlink():
                os.utime(path, (int(source_epoch), int(source_epoch)))
        os.utime(root, (int(source_epoch), int(source_epoch)))

        final_package = output_dir / package.name
        if final_package.exists() or final_package.is_symlink():
            raise FinalizationError("refusing to overwrite an existing final candidate")
        env = os.environ.copy()
        env["SOURCE_DATE_EPOCH"] = source_epoch
        build = subprocess.run(
            ["dpkg-deb", "--build", "--root-owner-group", "-Zxz", "-z9", "--uniform-compression", str(root), str(final_package)],
            env=env, capture_output=True, text=True, check=False,
        )
        if build.returncode != 0:
            raise FinalizationError("final signed package rebuild failed: " + (build.stderr.strip() or build.stdout.strip()))
        payload_sums_text = (root / "usr/share/ioscaffeinate/SHA256SUMS").read_text(encoding="utf-8")

    final_sha = sha256(final_package)
    shutil.copyfile(receipt_path, output_dir / "signature-integrity-verification.json")
    updated_record = package_record
    updated_signing = updated_record["signing"]
    updated_signing["signature_integrity"] = {
        "status": "VERIFIED",
        "tool": receipt["tool"],
        "method": receipt["method"],
        "receipt_sha256": receipt_sha,
        "verified_input_package_sha256": original_sha,
        "binary_sha256": binary_hashes,
        "metadata_only_repackaging": True,
    }
    updated_signing["signature_verification"] = "SIGNATURE_VERIFIED"
    updated_record["package"] = {"file": package.name, "sha256": final_sha}
    (output_dir / f"{package.name}.manifest.json").write_text(
        json.dumps(updated_record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    files_manifest = require_regular_after_rebuild(final_package, output_dir, f"{package.name}.files.sha256")
    files_manifest.write_text(payload_sums_text, encoding="utf-8")
    (output_dir / f"{package.name}.sha256").write_text(f"{final_sha}  {package.name}\n", encoding="utf-8")
    text_manifest = package_text_path.read_text(encoding="utf-8")
    text_manifest = re.sub(r"(?m)^artifact_sha256: [0-9a-f]{64}$", f"artifact_sha256: {final_sha}", text_manifest)
    text_manifest = re.sub(r"(?m)^signature_verification: PENDING$", "signature_verification: SIGNATURE_VERIFIED", text_manifest)
    if "signature_verification: SIGNATURE_VERIFIED" not in text_manifest:
        raise FinalizationError("package text manifest could not be updated to the verified signature state")
    (output_dir / f"{package.name}.manifest.txt").write_text(text_manifest, encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="ioscaffeinate-final-check-") as check_dir:
        report_path = Path(check_dir) / "signed-validation.txt"
        validation = subprocess.run(
            [sys.executable, str(validation_script), str(final_package), "--expected-version", EXPECTED_VERSION,
             "--ldid", str(signer), "--report", str(report_path)],
            capture_output=True, text=True, check=False,
        )
        if validation.returncode != 0:
            raise FinalizationError("final signed package validation failed: " + (validation.stderr.strip() or validation.stdout.strip()))
        shutil.copyfile(report_path, output_dir / "signed-validation.txt")

    finalization = {
        "schema_version": 1,
        "source_commit_sha": args.source_sha,
        "input_package_file": package.name,
        "input_package_sha256": original_sha,
        "final_package_sha256": final_sha,
        "macos_receipt_sha256": receipt_sha,
        "binary_sha256": binary_hashes,
        "repackaging": "SIGNING_METADATA_ONLY_BINARIES_UNCHANGED",
        "final_package_validation": "PASS",
    }
    (output_dir / "finalization-provenance.json").write_text(
        json.dumps(finalization, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return finalization


def require_regular_after_rebuild(package: Path, root: Path, filename: str) -> Path:
    del package
    path = root / filename
    if path.exists() or path.is_symlink():
        raise FinalizationError(f"refusing to overwrite final sidecar: {filename}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--signature-receipt", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--ldid", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(args)
    except (FinalizationError, OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"signed_candidate_sha256={result['final_package_sha256']}")
    print(f"host_signature_integrity=VERIFIED")
    print("package_validation=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
