#!/usr/bin/env python3
"""Run Apple's host codesign verifier against the signed binaries in a .deb."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from macho_code_signature import CodeSignatureError, audit_code_signature


MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
BINARIES = {
    "ios-caffeinate": "usr/local/bin/ios-caffeinate",
    "ios-caffeinated": "usr/local/bin/ios-caffeinated",
}


class VerificationError(ValueError):
    """A candidate or receipt input is malformed or unsafe."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_ar_member(package: Path, wanted: str) -> bytes:
    if package.is_symlink() or not package.is_file():
        raise VerificationError("candidate package must be a regular, non-symlink file")
    if package.stat().st_size > MAX_PACKAGE_BYTES:
        raise VerificationError("candidate package exceeds the verification size limit")
    raw = package.read_bytes()
    if not raw.startswith(b"!<arch>\n"):
        raise VerificationError("candidate is not a Debian ar archive")
    offset = 8
    found: bytes | None = None
    while offset < len(raw):
        header = raw[offset:offset + 60]
        if len(header) != 60 or header[58:60] != b"`\n":
            raise VerificationError("Debian ar member header is malformed")
        try:
            name = header[:16].decode("ascii").strip().rstrip("/")
            size_text = header[48:58].decode("ascii").strip()
            size = int(size_text)
        except (UnicodeDecodeError, ValueError):
            raise VerificationError("Debian ar member metadata is invalid") from None
        if size < 0 or size > MAX_PACKAGE_BYTES:
            raise VerificationError("Debian ar member size is outside the supported bound")
        start = offset + 60
        end = start + size
        if end > len(raw):
            raise VerificationError("Debian ar member is truncated")
        if name == wanted:
            if found is not None:
                raise VerificationError(f"duplicate Debian ar member: {wanted}")
            found = raw[start:end]
        offset = end + (size & 1)
    if offset != len(raw) or found is None:
        raise VerificationError(f"Debian package is missing {wanted}")
    return found


def read_payload_binary(package: Path, relative_path: str) -> bytes:
    archive = read_ar_member(package, "data.tar.xz")
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as tar:
            matches = []
            for member in tar.getmembers():
                name = member.name
                while name.startswith("./"):
                    name = name[2:]
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise VerificationError("package data archive contains an unsafe path")
                if name == relative_path:
                    matches.append(member)
            if len(matches) != 1:
                raise VerificationError(f"package must contain exactly one {relative_path}")
            member = matches[0]
            if not member.isfile() or member.size < 1 or member.size > MAX_MEMBER_BYTES:
                raise VerificationError(f"package member is not a bounded regular executable: {relative_path}")
            stream = tar.extractfile(member)
            if stream is None:
                raise VerificationError(f"package member cannot be read: {relative_path}")
            data = stream.read(MAX_MEMBER_BYTES + 1)
            if len(data) != member.size:
                raise VerificationError(f"package member read was incomplete: {relative_path}")
            return data
    except (tarfile.TarError, OSError, EOFError, ValueError) as error:
        if isinstance(error, VerificationError):
            raise
        raise VerificationError("package data archive could not be inspected") from None


def verify_package(package: Path, source_sha: str, output: Path, *, platform_name: str | None = None,
                   expected_package_sha256: str | None = None, package_manifest: Path | None = None,
                   workflow_run_id: str | None = None, workflow_run_attempt: str | None = None) -> dict[str, Any]:
    platform_name = sys.platform if platform_name is None else platform_name
    if platform_name != "darwin":
        raise VerificationError("Apple codesign verification must run on macOS")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise VerificationError("source commit SHA must be 40 lowercase hexadecimal characters")
    if output.exists() or output.is_symlink():
        raise VerificationError("refusing to overwrite an existing verification receipt")
    if package.is_symlink() or not package.is_file() or package.stat().st_size > MAX_PACKAGE_BYTES:
        raise VerificationError("candidate package must be a bounded regular, non-symlink file")
    package_sha = sha256_file(package)
    if expected_package_sha256 is not None and package_sha != expected_package_sha256:
        raise VerificationError("signed package SHA-256 differs from the expected candidate digest")
    package_record: dict[str, Any] | None = None
    if package_manifest is not None:
        if package_manifest.is_symlink() or not package_manifest.is_file() or package_manifest.stat().st_size > 4 * 1024 * 1024:
            raise VerificationError("signed package manifest is missing, unsafe, or too large")
        try:
            package_record = json.loads(package_manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise VerificationError("signed package manifest is malformed") from None
        if not isinstance(package_record, dict):
            raise VerificationError("signed package manifest root must be an object")
        identity = package_record.get("package") if isinstance(package_record, dict) else None
        signing = package_record.get("signing") if isinstance(package_record, dict) else None
        if (package_record.get("source_commit_sha") != source_sha or package_record.get("source_tree_clean") is not True or
            package_record.get("package_identifier") != "com.ioscaffeinate.cli" or
            package_record.get("package_version") != "0.2.0~rc1-1" or
            package_record.get("architecture") != "iphoneos-arm" or
            not isinstance(identity, dict) or identity.get("file") != package.name or identity.get("sha256") != package_sha or
            not isinstance(signing, dict) or signing.get("state") != "SIGNATURE_PRESENT" or
            signing.get("signature_verification") != "PENDING" or
            signing.get("profile_id") != "amethyst-ios12-rootful" or
            signing.get("profile_sha256") != "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca" or
            signing.get("signing_tool_version") != "2.1.5-procursus7" or
            signing.get("signing_tool_sha256") != "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c" or
            signing.get("embedded_entitlements") != "EXACT_MATCH" or
            signing.get("code_signature_kind") != "ADHOC"):
            raise VerificationError("signed package manifest does not bind the exact source, package, signer, and profile")
    codesign = Path("/usr/bin/codesign")
    if not codesign.is_file() or not os.access(codesign, os.X_OK):
        raise VerificationError("Apple codesign is unavailable at /usr/bin/codesign")
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ioscaffeinate-codesign-") as temporary:
        temp_root = Path(temporary)
        for name, relative in BINARIES.items():
            binary = read_payload_binary(package, relative)
            binary_path = temp_root / name
            with binary_path.open("xb") as stream:
                stream.write(binary)
            binary_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            independent: dict[str, Any]
            try:
                independent = audit_code_signature(binary, expected_identifier=name)
                if package_record is not None:
                    expected_binary_hashes = package_record["signing"].get("final_binary_sha256")
                    if not isinstance(expected_binary_hashes, dict) or expected_binary_hashes.get(name) != sha256_bytes(binary):
                        raise CodeSignatureError("binary SHA-256 differs from the signed package manifest")
            except (CodeSignatureError, KeyError, TypeError) as error:
                independent = {
                    "independent_code_directory_verified": False,
                    "entitlements_exact_match": False,
                    "adhoc_flag_present": False,
                    "signature_kind": "INVALID_OR_UNSUPPORTED",
                    "device_signature_acceptance": "PENDING",
                    "error": str(error),
                }
            command = [str(codesign), "--verify", "--strict", "--verbose=4", str(binary_path)]
            try:
                result = subprocess.run(command, capture_output=True, text=True, check=False)
            except OSError as error:
                raise VerificationError(f"codesign could not be executed for {name}: {error}") from None
            results.append({
                "name": name,
                "package_path": relative,
                "binary_sha256": sha256_bytes(binary),
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "apple_codesign_verified": result.returncode == 0,
                "independent_signature_audit": independent,
            })

    binaries_verified = all(
        result["exit_code"] == 0 and
        result["independent_signature_audit"].get("independent_code_directory_verified") is True and
        result["independent_signature_audit"].get("entitlements_exact_match") is True and
        result["independent_signature_audit"].get("adhoc_flag_present") is True
        for result in results
    )
    version_result = subprocess.run([str(codesign), "--version"], capture_output=True, text=True, check=False)
    os_result = subprocess.run(["/usr/bin/sw_vers", "-productVersion"], capture_output=True, text=True, check=False)
    # codesign's --version probe is not a portable successful query across
    # Apple tool versions. Its output is evidence; strict per-binary checks gate.
    status = "VERIFIED" if binaries_verified and os_result.returncode == 0 else "FAILED"
    run_id = workflow_run_id if workflow_run_id is not None else os.environ.get("GITHUB_RUN_ID", "LOCAL_DIAGNOSTIC")
    run_attempt = workflow_run_attempt if workflow_run_attempt is not None else os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    receipt = {
        "schema_version": 2,
        "status": status,
        "source_commit_sha": source_sha,
        "package_file": package.name,
        "package_sha256": package_sha,
        "host": "macOS",
        "tool": str(codesign),
        "method": "codesign --verify --strict --verbose=4",
        "codesign_version": {
            "command": [str(codesign), "--version"],
            "exit_code": version_result.returncode,
            "stdout": version_result.stdout,
            "stderr": version_result.stderr,
        },
        "macos_version": {"exit_code": os_result.returncode, "stdout": os_result.stdout, "stderr": os_result.stderr},
        "workflow_run_id": str(run_id),
        "workflow_run_attempt": str(run_attempt),
        "binary_results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--expected-package-sha256")
    parser.add_argument("--package-manifest", type=Path)
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--workflow-run-attempt")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = verify_package(
            args.package.absolute(), args.source_sha, args.output.absolute(),
            expected_package_sha256=args.expected_package_sha256,
            package_manifest=args.package_manifest.absolute() if args.package_manifest else None,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
        )
    except (VerificationError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"host_signature_integrity={receipt['status']}")
    print(f"package_sha256={receipt['package_sha256']}")
    for result in receipt["binary_results"]:
        print(f"{result['name']}_codesign_exit={result['exit_code']}")
    return 0 if receipt["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
