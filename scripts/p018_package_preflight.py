#!/usr/bin/env python3
"""Read-only inspection of an iOS-Caffeinate Debian artifact.

The program reads Debian control fields and streams the data archive in memory.
It does not extract files, execute maintainer scripts, install, remove, or
restore packages. Metadata consistency is not device signature acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


EXPECTED_PACKAGE = "com.ioscaffeinate.cli"
EXPECTED_ARCH = "iphoneos-arm"
EXPECTED_PROFILE = "amethyst-ios12-rootful"
EXPECTED_ENTITLEMENTS = {"com.apple.private.security.no-container": True}
MAX_DEB_SIZE = 128 * 1024 * 1024
MAX_FILE_SIZE = 32 * 1024 * 1024
MAX_TOTAL_SIZE = 64 * 1024 * 1024
MAX_MEMBERS = 1024
EXPECTED_P010_JOBS = {
    "linux-protocol", "ios-cross-build", "ios-artifact-inspection",
    "ios-rootful-package", "p009-evidence-validation",
    "p010-signing-release-gate", "p008-release-attestation",
}
EXPECTED_P010_CI_JOBS = EXPECTED_P010_JOBS - {
    "p008-release-attestation", "p010-signing-release-gate",
}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z.+:~_-]{1,128}$")
SIGNER_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_~-]{0,127}$")


class PreflightError(ValueError):
    pass


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreflightError("metadata contains duplicate JSON keys")
        result[key] = value
    return result


def read_regular(path: Path, limit: int) -> bytes:
    if not path.is_absolute():
        raise PreflightError("artifact path must be absolute")
    parts = path.parts[1:]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise PreflightError("artifact path contains traversal")
    fd = os.open("/", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                              getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
            os.close(fd)
            fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            os.close(file_fd)
            raise PreflightError("artifact or metadata sidecar is not a singly linked regular file")
        if info.st_size < 0 or info.st_size > limit:
            os.close(file_fd)
            raise PreflightError("artifact or metadata sidecar exceeds its size limit")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(file_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(file_fd)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ) or sum(map(len, chunks)) != info.st_size:
            raise PreflightError("artifact changed while being read")
        return b"".join(chunks)
    finally:
        try: os.close(file_fd)
        except (OSError, UnboundLocalError): pass
        os.close(fd)


def parse_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                           parse_constant=lambda _value: (_ for _ in ()).throw(PreflightError("JSON contains a non-standard numeric value")))
    except PreflightError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise PreflightError(f"{label} is not valid UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise PreflightError(f"{label} must be a JSON object")
    return value


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def dpkg_field(package: Path, field: str, pass_fds: tuple[int, ...] = ()) -> str:
    try:
        result = subprocess.run(["dpkg-deb", "-f", str(package), field],
                                capture_output=True, text=True, timeout=8, check=False,
                                pass_fds=pass_fds)
    except (OSError, subprocess.TimeoutExpired):
        raise PreflightError("dpkg-deb is unavailable or timed out") from None
    if result.returncode != 0:
        raise PreflightError("Debian control metadata could not be read")
    value = result.stdout.strip()
    if not value or "\n" in value or "\r" in value:
        raise PreflightError("Debian control metadata field is empty or malformed")
    return value


def safe_archive_path(value: str) -> str:
    if "\\" in value or "\x00" in value or value.startswith("/"):
        raise PreflightError("package archive contains an absolute or malformed path")
    normalized = value[2:] if value.startswith("./") else value
    normalized = normalized.rstrip("/")
    parts = normalized.split("/")
    if not normalized or any(part in ("", ".", "..") for part in parts):
        raise PreflightError("package archive contains path traversal")
    if not all(re.fullmatch(r"[A-Za-z0-9._+~-]{1,128}", part) for part in parts):
        raise PreflightError("package archive path contains unsupported characters")
    allowed = (
        "usr/local/bin/", "usr/local/libexec/", "usr/share/ioscaffeinate/",
        "usr/share/doc/ioscaffeinate/", "var/lib/ioscaffeinate/",
        "var/log/ioscaffeinate/",
    )
    allowed_dirs = {"usr", "usr/local", "usr/local/bin", "usr/local/libexec", "usr/share",
                    "usr/share/ioscaffeinate", "usr/share/ioscaffeinate/launchd",
                    "usr/share/ioscaffeinate/signing", "usr/share/doc",
                    "usr/share/doc/ioscaffeinate", "var", "var/lib",
                    "var/lib/ioscaffeinate", "var/log", "var/log/ioscaffeinate"}
    if normalized not in allowed_dirs and not any(normalized.startswith(prefix) for prefix in allowed):
        raise PreflightError("package archive contains a path outside the rootful payload allowlist")
    return normalized


def stream_archive(package: Path, pass_fds: tuple[int, ...] = ()) -> dict[str, bytes | None]:
    try:
        process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(package)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   pass_fds=pass_fds)
    except OSError:
        raise PreflightError("dpkg-deb archive reader is unavailable") from None
    assert process.stdout is not None
    members: dict[str, bytes | None] = {}
    total = 0
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for count, member in enumerate(archive, 1):
                if count > MAX_MEMBERS:
                    raise PreflightError("package archive contains too many entries")
                if member.name in (".", "./"):
                    if not member.isdir() or member.uid != 0 or member.gid != 0:
                        raise PreflightError("package archive root entry has unsafe metadata")
                    continue
                name = safe_archive_path(member.name)
                if name in members:
                    raise PreflightError("package archive contains duplicate paths")
                if member.uid != 0 or member.gid != 0:
                    raise PreflightError("package archive contains non-root-owned payload metadata")
                if member.isdir():
                    members[name] = None
                    continue
                if member.issym():
                    if name != "usr/local/bin/ic" or member.linkname != "ios-caffeinate":
                        raise PreflightError("package archive contains an unexpected symbolic link")
                    members[name] = None
                    continue
                if member.islnk() or not member.isfile():
                    raise PreflightError("package archive contains a hard link or special file")
                if member.size < 0 or member.size > MAX_FILE_SIZE:
                    raise PreflightError("package payload file exceeds its size limit")
                total += member.size
                if total > MAX_TOTAL_SIZE:
                    raise PreflightError("package payload exceeds its total size limit")
                source = archive.extractfile(member)
                if source is None:
                    raise PreflightError("package archive entry cannot be read")
                data = source.read(member.size + 1)
                if len(data) != member.size:
                    raise PreflightError("package archive entry size is inconsistent")
                members[name] = data
    except BaseException as error:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: pass
        if isinstance(error, (tarfile.TarError, OSError)):
            raise PreflightError(f"package data archive is invalid: {error}") from None
        raise
    finally:
        process.stdout.close()
    if process.wait(timeout=4) != 0:
        raise PreflightError("dpkg-deb could not finish reading the archive")
    return members


def verify_package_checksums(members: dict[str, bytes | None]) -> None:
    manifest_data = members.get("usr/share/ioscaffeinate/SHA256SUMS")
    if not isinstance(manifest_data, bytes):
        raise PreflightError("package SHA256SUMS is missing")
    records: dict[str, str] = {}
    try:
        lines = manifest_data.decode("ascii").splitlines()
    except UnicodeDecodeError:
        raise PreflightError("package SHA256SUMS is not ASCII") from None
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._+~/-]+)", line)
        if not match:
            raise PreflightError("package SHA256SUMS contains a malformed entry")
        digest, name = match.groups()
        if name in records or name not in members or not isinstance(members[name], bytes):
            raise PreflightError("package SHA256SUMS contains a duplicate or missing payload path")
        records[name] = digest
        if sha256(members[name]) != digest:
            raise PreflightError("package payload SHA-256 mismatch")
    expected = {name for name, value in members.items()
                if isinstance(value, bytes) and name != "usr/share/ioscaffeinate/SHA256SUMS"}
    if set(records) != expected:
        raise PreflightError("package SHA256SUMS does not cover every regular payload file")


def validate_p010_provenance(package: Path, artifact_hash: str,
                             package_record: dict[str, Any],
                             signing: dict[str, Any]) -> tuple[str, str]:
    candidate_path = Path(str(package) + ".P010-SIGNED-CANDIDATE-MANIFEST.json")
    if not candidate_path.exists():
        candidate_path = package.parent / "P010-SIGNED-CANDIDATE-MANIFEST.json"
    if not candidate_path.exists() or candidate_path.is_symlink():
        return "MISSING", "EXACT_P010_SIGNER_PROVENANCE_MISSING"
    try:
        candidate = parse_json(read_regular(candidate_path, 2 * 1024 * 1024), "P010 signed-candidate manifest")
    except (OSError, PreflightError):
        return "INVALID", "P010_SIGNER_PROVENANCE_INVALID"
    if candidate.get("manifest_version") != 1:
        return "INVALID", "P010_SIGNER_PROVENANCE_SCHEMA_UNSUPPORTED"
    source = candidate.get("source")
    signing_record = candidate.get("signing")
    artifacts = candidate.get("artifacts")
    ci = candidate.get("ci")
    package_artifact = artifacts.get("signed_candidate_package") if isinstance(artifacts, dict) else None
    if not all(isinstance(value, dict) for value in (source, signing_record, artifacts, ci, package_artifact)):
        return "INVALID", "P010_SIGNER_PROVENANCE_FIELDS_MISSING"
    assert isinstance(source, dict) and isinstance(signing_record, dict) and isinstance(ci, dict)
    assert isinstance(package_artifact, dict)
    signer_hash = signing.get("signing_tool_sha256")
    signer_version = signing.get("signing_tool_version")
    commit_sha = package_record.get("source_commit_sha")
    workflow_url = source.get("workflow_url")
    if (candidate.get("package_version") != package_record.get("package_version") or
        not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_sha) or
        source.get("commit_sha") != commit_sha or
        not isinstance(workflow_url, str) or
        not re.fullmatch(r"https://github\.com/nghianguyen150612/iOS-Caffeinate/actions/runs/[0-9]+", workflow_url) or
        ci.get("source_sha_pinned") is not True or
        package_artifact.get("sha256") != artifact_hash or
        package_artifact.get("path") != package.name or
        signing_record.get("profile_id") != EXPECTED_PROFILE or
        signing_record.get("profile_sha256") != signing.get("profile_sha256") or
        signing_record.get("signing_tool_version") != signer_version or
        signing_record.get("signing_tool_sha256") != signer_hash or
        candidate.get("device_execution") != "NOT_VERIFIED" or
        candidate.get("device_package_acceptance") != "NOT_ACCEPTED" or
        candidate.get("release_authorization_status") != "BLOCKED"):
        return "INVALID", "P010_SIGNER_PROVENANCE_MISMATCH"
    jobs = ci.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != EXPECTED_P010_JOBS or any(
        value not in ("success", "PASS", "SKIPPED_EXPECTED_BRANCH_GUARD") for value in jobs.values()
    ):
        return "INVALID", "P010_EXACT_SOURCE_CI_PROVENANCE_INVALID"
    if (any(jobs[name] != "success" for name in EXPECTED_P010_CI_JOBS) or
        jobs["p010-signing-release-gate"] != "PASS" or
        jobs["p008-release-attestation"] != "SKIPPED_EXPECTED_BRANCH_GUARD"):
        return "INVALID", "P010_EXACT_SOURCE_CI_RESULTS_INVALID"
    integrity = signing_record.get("signature_integrity")
    if integrity != "SIGNATURE_VERIFIED":
        return "UNVERIFIED", "HOST_SIGNATURE_INTEGRITY_NOT_VERIFIED"
    return "VALID", "EXACT_P010_PROVENANCE_MATCHED"


def check_collisions(members: dict[str, bytes | None]) -> list[str]:
    blockers: list[str] = []
    for name, value in members.items():
        if value is None or name.startswith("var/lib/ioscaffeinate") or name.startswith("var/log/ioscaffeinate"):
            continue
        path = Path("/") / name
        cursor = Path("/")
        for part in PurePosixPath(name).parts[:-1]:
            cursor = cursor / part
            try:
                info = cursor.lstat()
            except FileNotFoundError:
                break
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                blockers.append("PACKAGE_PATH_PARENT_UNSAFE")
                break
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        expected_alias = name == "usr/local/bin/ic" and stat.S_ISLNK(info.st_mode) and os.readlink(path) == "ios-caffeinate"
        if (stat.S_ISLNK(info.st_mode) and not expected_alias) or (not stat.S_ISLNK(info.st_mode) and not stat.S_ISREG(info.st_mode)):
            blockers.append("PACKAGE_PATH_COLLISION_UNSAFE")
            continue
        try:
            result = subprocess.run(["dpkg-query", "-S", str(path)], capture_output=True,
                                    text=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            blockers.append("PACKAGE_OWNERSHIP_TOOL_UNAVAILABLE")
            continue
        if result.returncode != 0 or not any(line.startswith(EXPECTED_PACKAGE + ": ")
                                              for line in result.stdout.splitlines()):
            blockers.append("PACKAGE_PATH_COLLISION_UNOWNED")
    return sorted(set(blockers))


def validate_artifact(package: Path, installed_version: str | None,
                      rollback_for_current_version: bool = False) -> dict[str, Any]:
    if not package.is_absolute():
        raise PreflightError("package path must be absolute")
    raw = read_regular(package, MAX_DEB_SIZE)
    artifact_hash = sha256(raw)
    sidecar_path = Path(str(package) + ".sha256")
    sidecar = read_regular(sidecar_path, 4096).decode("ascii")
    expected_sidecar = f"{artifact_hash}  {package.name}\n"
    if sidecar != expected_sidecar:
        raise PreflightError("package SHA-256 sidecar is missing or mismatched")
    package_record_path = Path(str(package) + ".manifest.json")
    package_record = parse_json(read_regular(package_record_path, 1024 * 1024), "package build manifest")
    # Give dpkg-deb a private, unlinked snapshot through an inherited descriptor.
    # This prevents a path replacement between hashing and metadata/archive reads.
    with tempfile.TemporaryFile(prefix="ioscaffeinate-p018-") as package_snapshot:
        package_snapshot.write(raw)
        package_snapshot.flush()
        package_snapshot.seek(0)
        package_fd = package_snapshot.fileno()
        dpkg_package = Path(f"/dev/fd/{package_fd}")
        package_id = dpkg_field(dpkg_package, "Package", (package_fd,))
        version = dpkg_field(dpkg_package, "Version", (package_fd,))
        arch = dpkg_field(dpkg_package, "Architecture", (package_fd,))
        if package_id != EXPECTED_PACKAGE:
            raise PreflightError("Debian package identity is incompatible")
        if not VERSION_RE.fullmatch(version):
            raise PreflightError("Debian package version is malformed")
        if arch != EXPECTED_ARCH:
            raise PreflightError("Debian package architecture is incompatible")
        members = stream_archive(dpkg_package, (package_fd,))
    if package_id != EXPECTED_PACKAGE:
        raise PreflightError("Debian package identity is incompatible")
    if not VERSION_RE.fullmatch(version):
        raise PreflightError("Debian package version is malformed")
    if arch != EXPECTED_ARCH:
        raise PreflightError("Debian package architecture is incompatible")
    recorded_package = package_record.get("package")
    if not isinstance(recorded_package, dict):
        raise PreflightError("package checksum sidecar is malformed")
    if (package_record.get("package_identifier") != EXPECTED_PACKAGE or
        package_record.get("package_version") != version or
        package_record.get("architecture") != EXPECTED_ARCH or
        recorded_package.get("file") != package.name or
        recorded_package.get("sha256") != artifact_hash or
        package_record.get("source_tree_clean") is not True):
        raise PreflightError("package build metadata does not match this exact artifact")
    if installed_version:
        if not VERSION_RE.fullmatch(installed_version):
            raise PreflightError("installed package version is malformed")
        try:
            relation = "lt" if rollback_for_current_version else "gt"
            comparison = subprocess.run(["dpkg", "--compare-versions", version, relation, installed_version],
                                        capture_output=True, timeout=4, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise PreflightError("Debian version comparison tool is unavailable") from None
        if comparison.returncode != 0:
            raise PreflightError("rollback package is not older than the installed version" if rollback_for_current_version
                                 else "candidate package version is not newer than the installed version")
    verify_package_checksums(members)
    embedded_record_data = members.get("usr/share/ioscaffeinate/package-build.json")
    signing_state_data = members.get("usr/share/ioscaffeinate/SIGNING-STATE")
    if not isinstance(embedded_record_data, bytes) or not isinstance(signing_state_data, bytes):
        raise PreflightError("signed-package metadata is missing from the archive")
    embedded_record = parse_json(embedded_record_data, "embedded package build record")
    if embedded_record != {key: value for key, value in package_record.items() if key != "package"}:
        raise PreflightError("embedded package metadata differs from its sidecar")
    signing = package_record.get("signing")
    if not isinstance(signing, dict):
        raise PreflightError("signed-package metadata has no signing record")
    profile_data = members.get("usr/share/ioscaffeinate/signing/amethyst-ios12-rootful.plist")
    if signing.get("state") != "SIGNATURE_PRESENT" or not isinstance(profile_data, bytes):
        raise PreflightError("package is unsigned or does not include the approved entitlement profile")
    try:
        entitlements = plistlib.loads(profile_data)
    except (plistlib.InvalidFileException, ValueError):
        raise PreflightError("approved entitlement profile is malformed") from None
    profile_hash = sha256(profile_data)
    if (entitlements != EXPECTED_ENTITLEMENTS or signing.get("profile_id") != EXPECTED_PROFILE or
        signing.get("profile_sha256") != profile_hash or signing.get("embedded_entitlements") != "EXACT_MATCH"):
        raise PreflightError("approved entitlement profile metadata does not match the package")
    try:
        state_text = signing_state_data.decode("utf-8")
    except UnicodeDecodeError:
        raise PreflightError("SIGNING-STATE is not UTF-8") from None
    if (f"signature_state=SIGNATURE_PRESENT" not in state_text or
        f"profile_id={EXPECTED_PROFILE}" not in state_text or
        f"profile_sha256={profile_hash}" not in state_text or
        "embedded_entitlements=EXACT_MATCH" not in state_text):
        raise PreflightError("SIGNING-STATE does not match the embedded profile")
    provenance, provenance_reason = validate_p010_provenance(package, artifact_hash,
                                                              package_record, signing)
    collision_blockers = check_collisions(members)
    blockers = list(collision_blockers)
    if provenance in ("MISSING", "INVALID"):
        blockers.append(provenance_reason)
    elif provenance == "UNVERIFIED":
        blockers.append(provenance_reason)
    if collision_blockers:
        decision = "BLOCKED"
    elif provenance == "INVALID":
        decision = "BLOCKED"
    elif provenance in ("MISSING", "UNVERIFIED"):
        decision = "UNVERIFIED"
    elif blockers:
        decision = "INCOMPLETE"
    else:
        decision = "READY_FOR_OPERATOR_REVIEW"
    return {
        "schema_version": 1,
        "package_identifier": package_id,
        "version": version,
        "architecture": arch,
        "sha256": artifact_hash,
        "package_metadata": "VALID",
        "sidecar": "VALID",
        "payload_manifest": "VALID",
        "signature_metadata": "PRESENT_EXACT_PROFILE",
        "signer_provenance": provenance,
        "signer_provenance_reason": provenance_reason,
        "path_collisions": "CLEAR" if not collision_blockers else "BLOCKED",
        "blockers": sorted(set(blockers)),
        "decision": decision,
        "hardware_acceptance": "NOT_ESTABLISHED",
        "maintainer_scripts_executed": "no",
        "package_installed": "no",
        "archive_extracted": "no",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--installed-version")
    parser.add_argument("--rollback-for-current-version", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.rollback_for_current_version and not args.installed_version:
            raise PreflightError("rollback preflight requires the current installed package version")
        result = validate_artifact(args.package, args.installed_version,
                                   args.rollback_for_current_version)
        code = 0 if result["decision"] == "READY_FOR_OPERATOR_REVIEW" else 1
    except (OSError, PreflightError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        reason = str(error)
        if "architecture" in reason:
            blocker = "INCOMPATIBLE_ARCHITECTURE"
        elif "identity" in reason:
            blocker = "INCOMPATIBLE_PACKAGE_IDENTITY"
        elif "signer" in reason or "signing" in reason or "signature" in reason:
            blocker = "SIGNER_PROVENANCE_OR_SIGNATURE_METADATA_INVALID"
        elif "SHA-256" in reason or "checksum" in reason or "hash" in reason:
            blocker = "INTEGRITY_FAILED"
        elif "symlink" in reason or "hard link" in reason or "traversal" in reason or "collision" in reason:
            blocker = "UNSAFE_PACKAGE_PATH"
        else:
            blocker = "PACKAGE_PREFLIGHT_INCOMPLETE"
        result = {
            "schema_version": 1,
            "decision": "BLOCKED" if blocker in ("INTEGRITY_FAILED", "UNSAFE_PACKAGE_PATH",
                                                       "INCOMPATIBLE_ARCHITECTURE", "INCOMPATIBLE_PACKAGE_IDENTITY") else "INCOMPLETE",
            "blockers": [blocker],
            "reason": reason,
            "hardware_acceptance": "NOT_ESTABLISHED",
            "maintainer_scripts_executed": "no",
            "package_installed": "no",
            "archive_extracted": "no",
        }
        code = 1
    if result.get("decision") != "READY_FOR_OPERATOR_REVIEW":
        blockers = result.get("blockers", [])
        first_blocker = blockers[0] if blockers and isinstance(blockers[0], str) else None
        reason = result.get("reason") or first_blocker or "PACKAGE_PREFLIGHT_NOT_READY"
        if result.get("decision") == "UNVERIFIED" or result.get("decision") == "INCOMPLETE":
            error_code = "EVIDENCE_PENDING"
        elif first_blocker == "UNSAFE_PACKAGE_PATH":
            error_code = "UNSAFE_STATE"
        elif first_blocker in ("INCOMPATIBLE_ARCHITECTURE", "INCOMPATIBLE_PACKAGE_IDENTITY"):
            error_code = "UNSUPPORTED"
        else:
            error_code = "INTEGRITY_FAILED"
        result.update({
            "operation": "package_rollback_check" if args.rollback_for_current_version
                         else "package_upgrade_check",
            "error_code": error_code,
            "error_reason": str(reason),
            "changed": "no",
            "cleanup": "not_applicable",
            "next_safe_step": "inspect_package_metadata_and_signer_provenance",
        })
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        for key in ("schema_version", "package_identifier", "version", "architecture", "sha256",
                    "package_metadata", "sidecar", "payload_manifest", "signature_metadata",
                    "signer_provenance", "signer_provenance_reason", "path_collisions", "decision",
                    "hardware_acceptance", "maintainer_scripts_executed", "package_installed", "archive_extracted"):
            if key in result:
                print(f"package.{key}={result[key]}")
        for blocker in result.get("blockers", []):
            print(f"blocker={blocker}")
        if "error_code" in result:
            print(f"error.operation={result['operation']}")
            print(f"error.code={result['error_code']}")
            print(f"error.reason={result['error_reason']}")
            print(f"changed={result['changed']}")
            print(f"cleanup={result['cleanup']}")
            print(f"next_safe_step={result['next_safe_step']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
