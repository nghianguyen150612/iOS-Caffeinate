#!/usr/bin/env python3
"""Validate only the byte-pinned historical iOS-Caffeinate v0.1.0 package.

This module keeps the seven-record v0.1.0 checksum contract isolated from the
strict full-regular-file manifest required by current package validation.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from macho_ios import validate_ios12_arm64
from signing_profile import (
    PROFILE_ID,
    PROFILE_RELATIVE_PATH,
    SigningError,
    load_approved_profile,
    require_exact_embedded_entitlements,
    signer_identity,
    validate_signer,
)


ROOT = Path(__file__).resolve().parents[1]
TAG = "v0.1.0"
REPOSITORY = "nghianguyen150612/iOS-Caffeinate"
PACKAGE_ID = "com.ioscaffeinate.cli"
PACKAGE_VERSION = "0.1.0-1"
ARCHITECTURE = "iphoneos-arm"
PACKAGE_FILENAME = "ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb"
PACKAGE_SHA256 = "439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c"
PACKAGE_SIZE = 95572
SOURCE_COMMIT = "0cfdc645dc1d67ddc4320a00bb114763b9669b66"
SIGNER_VERSION = "2.1.5-procursus7"
SIGNER_SHA256 = "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c"
PROFILE_SHA256 = "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca"
INVENTORY_PATH = ROOT / "docs/v0.2/H002-DERIVED-INVENTORY.json"
EMBEDDED_CHECKSUM_PATH = "usr/share/ioscaffeinate/SHA256SUMS"
BUILD_MANIFEST_PATH = "usr/share/ioscaffeinate/package-build.json"
SIGNING_STATE_PATH = "usr/share/ioscaffeinate/SIGNING-STATE"
PROFILE_PATH = "usr/share/ioscaffeinate/signing/amethyst-ios12-rootful.plist"
CLI_PATH = "usr/local/bin/ios-caffeinate"
DAEMON_PATH = "usr/local/bin/ios-caffeinated"

# This is the historical v0.1.0 required checksum set from the stable-source
# validator. It is intentionally separate from the current strict validator.
HISTORICAL_CHECKSUM_PATHS = (
    CLI_PATH,
    DAEMON_PATH,
    "usr/local/libexec/ioscaffeinate-manager",
    "usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist",
    SIGNING_STATE_PATH,
    PROFILE_PATH,
    BUILD_MANIFEST_PATH,
)

HISTORICAL_DEPENDENCIES = {
    CLI_PATH: {"/usr/lib/libSystem.B.dylib"},
    DAEMON_PATH: {
        "/usr/lib/libSystem.B.dylib",
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    },
}

EXPECTED_ASSET_SHA256 = {
    PACKAGE_FILENAME: PACKAGE_SHA256,
    f"{PACKAGE_FILENAME}.sha256": "2ec6d780ffbd32d10b1c193b5c2707a0493a1006f8e181ffa4af494574cc8009",
    f"{PACKAGE_FILENAME}.files.sha256": "d215d778e89d8b642946533c917dad63a6c2276d0b09aef7d9bb3f49e3bd146a",
    f"{PACKAGE_FILENAME}.manifest.json": "66a15fc039eb4c375b1921e3f6279ec99b39e6edde885967412ebbd6e7b95f1e",
    f"{PACKAGE_FILENAME}.manifest.txt": "468e47695881e1a88dc601129d328d7a135ccb3d6ccc942a6d51e387182faf49",
    "P010-RELEASE-MANIFEST.json": "2c9ceb3c6a3e985a9f88897b4b785b67081ac589ad6fa9ac86f940e689c9834e",
    "P010-SIGNED-CANDIDATE-MANIFEST.json": "5c92fe90de9e579dfbfd010d4f36d133f0900388888d553dd7871ad1f3dadc8a",
    "signed-validation.txt": "cf1bc8687ce3dba5e0b6cf1fe6d0e8a03556c5cc6f43c55aa9a272368b66c086",
}

EXPECTED_ASSET_SIZES = {
    PACKAGE_FILENAME: 95572,
    f"{PACKAGE_FILENAME}.sha256": 130,
    f"{PACKAGE_FILENAME}.files.sha256": 766,
    f"{PACKAGE_FILENAME}.manifest.json": 1478,
    f"{PACKAGE_FILENAME}.manifest.txt": 1320,
    "P010-RELEASE-MANIFEST.json": 2898,
    "P010-SIGNED-CANDIDATE-MANIFEST.json": 3376,
    "signed-validation.txt": 501,
}

EXPECTED_SIGNING = {
    "state": "SIGNATURE_PRESENT",
    "profile_id": PROFILE_ID,
    "profile_sha256": PROFILE_SHA256,
    "signing_tool_version": SIGNER_VERSION,
    "signing_tool_sha256": SIGNER_SHA256,
    "source_binary_sha256": {
        "ios-caffeinate": "4155c7b38bcc85db3aef03eab374ee182909ec976faf0c3e9d5bd8d3f3f8a82e",
        "ios-caffeinated": "24fda4bdcd0879242155f68f98b4e09c4db102de5f6e214b780b74cb065f3c21",
    },
    "final_binary_sha256": {
        "ios-caffeinate": "a4957dfacbd2ff84fe4122578e050eee53d8db4b1b04dc89828d3b72494651fe",
        "ios-caffeinated": "a692c0daff6df9f2aafeb89bbbeabd2439f1efd163cf88fbada75f203bef5cc0",
    },
    "embedded_entitlements": "EXACT_MATCH",
    "signature_verification": "PENDING",
    "signature_integrity": {"results": [], "status": "PENDING", "tool": None},
    "device_execution_verification": "NOT_VERIFIED",
    "device_package_acceptance": "NOT_ACCEPTED",
}

EXPECTED_SIGNING_STATE = {
    "signature_state": "SIGNATURE_PRESENT",
    "profile_id": PROFILE_ID,
    "profile_sha256": PROFILE_SHA256,
    "embedded_entitlements": "EXACT_MATCH",
    "signature_verification": "PENDING",
    "device_execution": "NOT_VERIFIED",
    "device_package_acceptance": "NOT_ACCEPTED",
    "signing_tool_version": SIGNER_VERSION,
    "signing_tool_sha256": SIGNER_SHA256,
}

CONTROL_FIELDS = {
    "Package": PACKAGE_ID,
    "Version": PACKAGE_VERSION,
    "Section": "utils",
    "Priority": "optional",
    "Architecture": ARCHITECTURE,
    "Maintainer": "iOS-Caffeinate contributors <ios-caffeinate@users.noreply.github.com>",
    "Description": (
        "Bounded power assertion CLI and daemon for rootful iOS\n"
        "Native C11 command-line client and manually managed daemon for rootful\n"
        "jailbroken iOS 12. The daemon is not started or registered automatically."
    ),
}

FORBIDDEN_SCRIPT_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in (
    r"\blaunchctl\s+(?:load|bootstrap|enable|kickstart|start|restart)\b",
    r"\b(?:reboot|respring)\b",
    r"\b(?:curl|wget|nc|socat)\b",
    r"\brm\s+-rf\b",
    r"\b(?:killall|pkill)\b",
    r"\b(?:chown|chmod)\s+-R\b",
    r"\b(?:systemctl|service)\s+(?:start|restart|enable)\b",
    r"\b(?:exec|nohup)\s+(?:/usr/local/bin/)?ios-caffeinated\b",
))


class LegacyValidationError(ValueError):
    """A pinned historical artifact or its compatibility contract failed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LegacyValidationError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_json_pairs)
    except LegacyValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise LegacyValidationError(f"{label} is not valid UTF-8 JSON") from None
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def normalized_member_path(name: str) -> str:
    require("\\" not in name and "\x00" not in name, f"unsafe archive path: {name!r}")
    require(not name.startswith("/"), f"absolute archive path: {name}")
    require("//" not in name, f"non-canonical archive path: {name}")
    parts = name.split("/")
    require(".." not in parts, f"path traversal in package member: {name}")
    # Debian data archives use a single leading ./ on each member.
    if parts and parts[0] == ".":
        parts = parts[1:]
    require("." not in parts, f"non-canonical archive path: {name}")
    normalized = "/".join(part for part in parts if part)
    return normalized or "."


def load_derived_inventory(path: Path = INVENTORY_PATH) -> dict[str, Any]:
    require(not path.is_symlink() and path.is_file(), "derived historical layout inventory is missing or unsafe")
    inventory = parse_json(path.read_bytes(), "derived historical layout inventory")
    require(inventory.get("schema_version") == 1, "unsupported derived inventory schema")
    require(inventory.get("inventory_kind") == "DERIVED_AFTER_PUBLICATION", "layout inventory is not labeled as post-publication derived data")
    require(inventory.get("historical_checksum_manifest", {}).get("full_payload_manifest") == "NOT_PRESENT_IN_HISTORICAL_RELEASE", "derived inventory overstates historical checksum coverage")
    source = inventory.get("source")
    require(isinstance(source, dict), "derived inventory source is malformed")
    require(source.get("tag") == TAG and source.get("package_filename") == PACKAGE_FILENAME, "derived inventory artifact identity mismatch")
    require(source.get("package_sha256") == PACKAGE_SHA256 and source.get("source_commit_sha") == SOURCE_COMMIT, "derived inventory provenance mismatch")
    checksum_metadata = inventory.get("historical_checksum_manifest")
    require(isinstance(checksum_metadata, dict), "derived historical checksum metadata is malformed")
    record_paths = checksum_metadata.get("record_paths")
    require(isinstance(record_paths, list) and len(record_paths) == 7 and set(record_paths) == set(HISTORICAL_CHECKSUM_PATHS), "derived historical checksum set differs from the fixed seven-record contract")
    members = inventory.get("members")
    require(isinstance(members, list), "derived inventory member list is malformed")
    by_path: dict[str, dict[str, Any]] = {}
    for item in members:
        require(isinstance(item, dict) and isinstance(item.get("path"), str), "derived inventory has a malformed member")
        require(item["path"] not in by_path, f"duplicate derived inventory path: {item['path']}")
        by_path[item["path"]] = item
    require(len(by_path) == len(members), "derived inventory has duplicate paths")
    counts = inventory.get("counts")
    require(isinstance(counts, dict) and counts.get("archive_members") == len(members), "derived inventory member count mismatch")
    require(counts.get("regular_files_including_checksum_manifest") == 59, "derived historical regular-file count mismatch")
    require(counts.get("uncovered_regular_members_including_checksum_manifest") == 52, "derived historical uncovered-member count mismatch")
    return inventory


def _member_type(member: tarfile.TarInfo) -> str:
    if member.isfile():
        return "regular"
    if member.isdir():
        return "directory"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    return "special"


def validate_member_table(
    members: list[tarfile.TarInfo],
    inventory: dict[str, Any],
    read_member: Any,
) -> tuple[dict[str, tarfile.TarInfo], dict[str, bytes]]:
    expected = {item["path"]: item for item in inventory["members"]}
    entries: dict[str, tarfile.TarInfo] = {}
    data: dict[str, bytes] = {}
    for member in members:
        path = normalized_member_path(member.name)
        require(path not in entries, f"duplicate package member path: {path}")
        require(member.uid == 0 and member.gid == 0, f"package member is not root-owned: {path}")
        kind = _member_type(member)
        require(kind in ("regular", "directory", "symlink"), f"unsupported hardlink or special member: {path}")
        if kind == "symlink":
            require(path == "usr/local/bin/ic" and member.linkname == "ios-caffeinate", f"unsafe or unexpected package symlink: {path} -> {member.linkname}")
            require(not member.linkname.startswith("/") and ".." not in PurePosixPath(member.linkname).parts, f"unsafe symlink target: {path} -> {member.linkname}")
        expected_member = expected.get(path)
        require(expected_member is not None, f"unexpected package member: {path}")
        require(kind == expected_member.get("type"), f"wrong member type for {path}: {kind}")
        require((member.mode & 0o777) == expected_member.get("mode"), f"unsafe or incorrect permissions for {path}")
        require(member.uid == expected_member.get("uid") and member.gid == expected_member.get("gid"), f"incorrect owner for {path}")
        require(member.size == expected_member.get("size"), f"incorrect member size for {path}")
        if kind == "symlink":
            require(member.linkname == expected_member.get("link_target"), f"unexpected symlink target for {path}")
        if kind == "regular":
            contents = read_member(member)
            require(isinstance(contents, bytes), f"could not read regular package member: {path}")
            require(sha256_bytes(contents) == expected_member.get("derived_sha256"), f"derived after-publication content digest mismatch for {path}")
            data[path] = contents
        entries[path] = member
    missing = sorted(set(expected) - set(entries))
    require(not missing, "historical package layout is missing required member(s): " + ", ".join(missing))
    return entries, data


def validate_historical_checksum_records(
    raw: bytes,
    file_data: dict[str, bytes],
    inventory: dict[str, Any],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise LegacyValidationError("historical SHA256SUMS is not ASCII") from None
    require(text.endswith("\n"), "historical SHA256SUMS must end with one newline")
    lines = text[:-1].split("\n")
    require(len(lines) == len(HISTORICAL_CHECKSUM_PATHS), "historical SHA256SUMS must contain exactly seven records")
    records: dict[str, str] = {}
    for number, line in enumerate(lines, 1):
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)", line)
        require(match is not None, f"invalid historical checksum record at line {number}")
        assert match is not None
        digest, path = match.groups()
        require(path not in records, f"duplicate historical checksum record: {path}")
        records[path] = digest
    require(set(records) == set(HISTORICAL_CHECKSUM_PATHS), "historical SHA256SUMS does not match the fixed seven-record contract")
    for path, expected_digest in records.items():
        require(path in file_data, f"historical checksum target is missing or not regular: {path}")
        require(sha256_bytes(file_data[path]) == expected_digest, f"historical package checksum mismatch: {path}")
    inventory_by_path = {item["path"]: item for item in inventory["members"]}
    uncovered = []
    for path in sorted(set(file_data) - set(records)):
        member = inventory_by_path[path]
        purpose = member.get("purpose") or "Uncovered regular payload member in the post-publication derived inventory."
        uncovered.append({"path": path, "type": member["type"], "purpose": purpose})
    return records, uncovered


def parse_debian_control(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise LegacyValidationError("Debian control metadata is not UTF-8") from None
    fields: dict[str, str] = {}
    current: str | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.startswith((" ", "\t")):
            require(current is not None, f"orphan Debian control continuation at line {line_number}")
            fields[current] += "\n" + line[1:]
            continue
        require(":" in line, f"malformed Debian control field at line {line_number}")
        key, value = line.split(":", 1)
        require(key and key not in fields, f"duplicate or empty Debian control field: {key}")
        require(re.fullmatch(r"[A-Za-z0-9-]+", key) is not None, f"invalid Debian control field name: {key}")
        fields[key] = value.lstrip(" ")
        current = key
    require(set(fields) == set(CONTROL_FIELDS), "unexpected or missing Debian control field")
    for key, expected in CONTROL_FIELDS.items():
        require(fields.get(key) == expected, f"unexpected Debian control value: {key}")
    return fields


def validate_script_text(name: str, raw: bytes) -> str:
    try:
        script = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise LegacyValidationError(f"maintainer script is not UTF-8: {name}") from None
    require(script.startswith("#!/bin/sh\n"), f"maintainer script has an unexpected interpreter: {name}")
    for pattern in FORBIDDEN_SCRIPT_PATTERNS:
        require(not pattern.search(script), f"unsafe maintainer script command in {name}: {pattern.pattern}")
    checked = subprocess.run(["sh", "-n", "-c", script], text=True, capture_output=True, check=False)
    require(checked.returncode == 0, f"maintainer script syntax error in {name}: {checked.stderr.strip()}")
    return script


def validate_control_archive(raw: bytes, incoming_paths: set[str]) -> tuple[dict[str, str], dict[str, str]]:
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
            members = archive.getmembers()
            entries: dict[str, tarfile.TarInfo] = {}
            data: dict[str, bytes] = {}
            for member in members:
                path = normalized_member_path(member.name)
                require(path not in entries, f"duplicate Debian control path: {path}")
                if path == ".":
                    require(member.isdir() and member.uid == 0 and member.gid == 0 and (member.mode & 0o777) == 0o755, "unsafe Debian control archive root")
                    entries[path] = member
                    continue
                require(member.isfile(), f"unsupported Debian control member type: {path}")
                require(member.uid == 0 and member.gid == 0, f"Debian control member is not root-owned: {path}")
                expected_mode = 0o644 if path == "control" else 0o755
                require((member.mode & 0o777) == expected_mode, f"unsafe Debian control member permissions: {path}")
                entries[path] = member
                stream = archive.extractfile(member)
                require(stream is not None, f"could not read Debian control member: {path}")
                data[path] = stream.read()
    except tarfile.TarError as error:
        raise LegacyValidationError(f"invalid Debian control archive: {error}") from None
    require(set(entries) - {"."} == {"control", "preinst", "prerm"}, "package must contain only control, preinst, and prerm")
    fields = parse_debian_control(data["control"])
    preinst = validate_script_text("preinst", data["preinst"])
    prerm = validate_script_text("prerm", data["prerm"])
    checked_paths = set(re.findall(r"check_owned_or_absent '([^']+)'", preinst))
    require(incoming_paths <= checked_paths, "preinst does not guard every incoming package file against collisions")
    require("launchctl" not in preinst.lower() and "launchctl" not in prerm.lower(), "maintainer scripts must not control launchd")
    return fields, {"preinst": preinst, "prerm": prerm}


def validate_package_build_metadata(build: dict[str, Any]) -> None:
    require(set(build) == {"architecture", "package_identifier", "package_version", "schema_version", "signing", "source_commit_sha", "source_tree_clean"}, "package build metadata has missing or unexpected fields")
    require(build.get("schema_version") == 1, "unsupported historical package build metadata version")
    require(build.get("package_identifier") == PACKAGE_ID, "historical package build identifier mismatch")
    require(build.get("package_version") == PACKAGE_VERSION, "historical package build version mismatch")
    require(build.get("architecture") == ARCHITECTURE, "historical package build architecture mismatch")
    require(build.get("source_commit_sha") == SOURCE_COMMIT and build.get("source_tree_clean") is True, "historical package source provenance mismatch")
    signing = build.get("signing")
    require(isinstance(signing, dict), "historical signing metadata is malformed")
    require(set(signing) == set(EXPECTED_SIGNING), "historical signing metadata has missing or unexpected fields")
    require(signing == EXPECTED_SIGNING, "historical signing metadata differs from the published P010 identity")


def validate_pinned_signer_identity(version: str, digest: str) -> None:
    require(version == SIGNER_VERSION, "pinned H001 signer version mismatch")
    require(digest == SIGNER_SHA256, "pinned H001 signer SHA-256 mismatch")


def validate_embedded_profile(raw: bytes) -> dict[str, bool]:
    try:
        embedded_profile = plistlib.loads(raw)
    except Exception as error:
        raise LegacyValidationError(f"embedded entitlement profile is malformed: {type(error).__name__}") from None
    require(embedded_profile == {"com.apple.private.security.no-container": True}, "embedded historical entitlement profile is unexpected")
    require(sha256_bytes(raw) == PROFILE_SHA256, "embedded historical entitlement profile digest mismatch")
    approved_profile, approved_digest = load_approved_profile(ROOT / PROFILE_RELATIVE_PATH)
    require(approved_profile == embedded_profile and approved_digest == PROFILE_SHA256, "repository profile differs from the pinned historical profile")
    return embedded_profile


def parse_signing_state(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise LegacyValidationError("historical signing state is not UTF-8") from None
    result: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        require("=" in line, f"malformed signing state at line {number}")
        key, value = line.split("=", 1)
        require(key and key not in result, f"duplicate or empty signing state key at line {number}")
        result[key] = value
    require(result == EXPECTED_SIGNING_STATE, "historical signing state differs from the published P010 identity")
    return result


def verify_published_assets(asset_dir: Path, package_path: Path, package_build: dict[str, Any], sums_raw: bytes) -> None:
    require(not asset_dir.is_symlink() and asset_dir.is_dir(), "official release asset directory is missing or unsafe")
    require(package_path.parent.resolve() == asset_dir.resolve(), "package and release sidecars must be adjacent")
    for name, digest in EXPECTED_ASSET_SHA256.items():
        verify_published_asset(asset_dir, name)
    package_sum = asset_dir / f"{PACKAGE_FILENAME}.sha256"
    require(package_sum.read_bytes() == f"{PACKAGE_SHA256}  {PACKAGE_FILENAME}\n".encode(), "published package checksum sidecar differs from the pinned identity")
    require((asset_dir / f"{PACKAGE_FILENAME}.files.sha256").read_bytes() == sums_raw, "published files sidecar differs from embedded historical SHA256SUMS")
    sidecar = parse_json((asset_dir / f"{PACKAGE_FILENAME}.manifest.json").read_bytes(), "published package metadata sidecar")
    expected_sidecar = dict(package_build)
    expected_sidecar["package"] = {"file": PACKAGE_FILENAME, "sha256": PACKAGE_SHA256}
    require(sidecar == expected_sidecar, "published package metadata sidecar differs from embedded build metadata")


def verify_published_asset(asset_dir: Path, name: str) -> Path:
    require(name in EXPECTED_ASSET_SHA256, f"unexpected published release sidecar: {name}")
    path = asset_dir / name
    require(not path.is_symlink() and path.is_file(), f"published release sidecar is missing or unsafe: {name}")
    require(path.stat().st_size == EXPECTED_ASSET_SIZES[name], f"published release sidecar size mismatch: {name}")
    require(sha256_file(path) == EXPECTED_ASSET_SHA256[name], f"published release sidecar SHA-256 mismatch: {name}")
    return path


def verify_official_archive_identity(package_path: Path) -> str:
    # This is deliberately the first compatibility gate. No legacy parsing is
    # reached until the exact released archive digest has matched.
    require(package_path.name == PACKAGE_FILENAME, "legacy compatibility is restricted to the exact published v0.1.0 filename")
    require(not package_path.is_symlink() and package_path.is_file(), "published package must be a regular non-symlink file")
    require(package_path.stat().st_size == PACKAGE_SIZE, "published package size differs from the pinned v0.1.0 artifact")
    digest = sha256_file(package_path)
    require(digest == PACKAGE_SHA256, "published package SHA-256 differs from the pinned v0.1.0 artifact")
    return digest


def _validate_official_archive_contents(package_path: Path, asset_dir: Path, ldid: Path | None) -> dict[str, Any]:
    if shutil.which("dpkg-deb") is None:
        raise LegacyValidationError("dpkg-deb is required for historical package inspection")
    inventory = load_derived_inventory()
    data_result = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(package_path)], capture_output=True, check=False)
    require(data_result.returncode == 0, "could not read Debian package payload archive")
    try:
        with tarfile.open(fileobj=io.BytesIO(data_result.stdout), mode="r:*") as archive:
            tar_members = archive.getmembers()
            entries, file_data = validate_member_table(tar_members, inventory, lambda member: archive.extractfile(member).read())
    except tarfile.TarError as error:
        raise LegacyValidationError(f"invalid historical package data archive: {error}") from None

    checksum_records, uncovered = validate_historical_checksum_records(file_data[EMBEDDED_CHECKSUM_PATH], file_data, inventory)
    require(len(checksum_records) == 7, "historical checksum record count mismatch")
    require(len(uncovered) == 52, "derived historical uncovered-member count mismatch")

    build = parse_json(file_data[BUILD_MANIFEST_PATH], "embedded package build metadata")
    validate_package_build_metadata(build)
    signing_state = parse_signing_state(file_data[SIGNING_STATE_PATH])
    require(signing_state["signature_state"] == "SIGNATURE_PRESENT", "historical package is not the signed release artifact")

    validate_embedded_profile(file_data[PROFILE_PATH])

    control_result = subprocess.run(["dpkg-deb", "--ctrl-tarfile", str(package_path)], capture_output=True, check=False)
    require(control_result.returncode == 0, "could not read Debian control archive")
    incoming_paths = {"/" + path for path, member in entries.items() if member.isfile() or member.issym()}
    fields, scripts = validate_control_archive(control_result.stdout, incoming_paths)
    require(fields["Package"] == PACKAGE_ID and fields["Version"] == PACKAGE_VERSION and fields["Architecture"] == ARCHITECTURE, "Debian package identity mismatch")

    macho_results: dict[str, Any] = {}
    signer: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="ioscaffeinate-p011-legacy-") as temporary:
            scratch = Path(temporary)
            binaries = {CLI_PATH: scratch / "ios-caffeinate", DAEMON_PATH: scratch / "ios-caffeinated"}
            for package_member, local_path in binaries.items():
                local_path.write_bytes(file_data[package_member])
                local_path.chmod(0o755)
                info = validate_ios12_arm64(local_path, allow_signature=True, expected_dependencies=HISTORICAL_DEPENDENCIES[package_member])
                require(info.architecture == "arm64" and info.platform == "iOS" and info.minimum_os == (12, 0, 0), f"historical binary properties are unexpected: {package_member}")
                require(info.has_code_signature, f"historical signed binary has no Mach-O code signature: {package_member}")
                binary_name = "ios-caffeinate" if package_member == CLI_PATH else "ios-caffeinated"
                require(sha256_bytes(file_data[package_member]) == EXPECTED_SIGNING["final_binary_sha256"][binary_name], f"signed binary hash differs from original build metadata: {binary_name}")
                macho_results[binary_name] = {
                    "architecture": info.architecture,
                    "platform": info.platform,
                    "minimum_os": ".".join(str(value) for value in info.minimum_os),
                    "code_signature_present": info.has_code_signature,
                }
            if ldid is not None:
                require(ldid.is_absolute() and not ldid.is_symlink() and ldid.is_file(), "--ldid must name an absolute regular executable")
                signer = validate_signer(ldid)
                version, digest = signer_identity(signer)
                validate_pinned_signer_identity(version, digest)
                for local_path in binaries.values():
                    require_exact_embedded_entitlements(signer, local_path)
    except SigningError as error:
        raise LegacyValidationError(f"pinned signer or entitlement validation failed: {error}") from None
    except ValueError as error:
        raise LegacyValidationError(str(error)) from None

    verify_published_assets(asset_dir, package_path, build, file_data[EMBEDDED_CHECKSUM_PATH])
    missing_inputs = [] if signer is not None else ["verified H001 ldid executable at the recorded version and SHA-256"]
    entitlements = "EXACT_MATCH" if signer is not None else "PENDING_PINNED_LDID"
    status = "PASS" if signer is not None else "BLOCKED_MISSING_PINNED_SIGNER"
    return {
        "schema_version": 1,
        "validator": "p011_legacy_package_validator",
        "validation_status": status,
        "artifact_scope": "EXACT_PUBLISHED_V0_1_0",
        "artifact": {
            "repository": REPOSITORY,
            "tag": TAG,
            "filename": PACKAGE_FILENAME,
            "package_identifier": PACKAGE_ID,
            "package_version": PACKAGE_VERSION,
            "architecture": ARCHITECTURE,
            "archive_sha256": PACKAGE_SHA256,
            "source_commit_sha": SOURCE_COMMIT,
        },
        "integrity_levels": {
            "archive_sha256": "VERIFIED",
            "publisher_release_identity": "PINNED_GITHUB_RELEASE_ASSET_DIGESTS_MATCH",
            "published_checksum_scope": "LEGACY_REQUIRED_SET",
            "published_checksum_entries": len(checksum_records),
            "full_payload_manifest": "NOT_PRESENT_IN_HISTORICAL_RELEASE",
            "derived_payload_inventory": "AVAILABLE_AFTER_PUBLICATION",
            "derived_uncovered_regular_members": len(uncovered),
            "signer_provenance": "VERIFIED" if signer is not None else "PUBLISHED_METADATA_MATCHED_PINNED_H001_IDENTITY_EXECUTABLE_MISSING",
            "embedded_entitlements": entitlements,
            "signature_integrity": "PENDING",
            "device_execution": "UNVERIFIED",
            "device_package_acceptance": "PENDING",
        },
        "package_structure": "VERIFIED",
        "debian_control": fields,
        "mach_o": macho_results,
        "maintainer_scripts": {name: "SYNTAX_AND_SAFETY_VERIFIED" for name in scripts},
        "historical_checksum_records": checksum_records,
        "uncovered_members": uncovered,
        "missing_verification_inputs": missing_inputs,
        "claims": {
            "signature_integrity": "PENDING",
            "device_execution": "UNVERIFIED",
            "device_package_acceptance": "PENDING",
            "release_authorization": "BLOCKED",
        },
    }


def inspect_official_package(package_path: Path, asset_dir: Path, ldid: Path | None = None) -> dict[str, Any]:
    digest = verify_official_archive_identity(package_path)
    result = _validate_official_archive_contents(package_path, asset_dir, ldid)
    require(result["artifact"]["archive_sha256"] == digest, "legacy validation digest changed after preflight")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="exact published v0.1.0 package")
    parser.add_argument("--asset-dir", type=Path, help="directory containing every pinned official release sidecar")
    parser.add_argument("--ldid", type=Path, help="verified H001 Procursus ldid 2.1.5-procursus7 executable")
    parser.add_argument("--json", action="store_true", help="write the versioned validation result as JSON")
    args = parser.parse_args(argv)
    package = args.package.absolute()
    asset_dir = args.asset_dir.absolute() if args.asset_dir else package.parent
    try:
        report = inspect_official_package(package, asset_dir, args.ldid.absolute() if args.ldid else None)
    except (LegacyValidationError, SigningError, OSError, subprocess.SubprocessError, tarfile.TarError, ValueError) as error:
        report = {
            "schema_version": 1,
            "validator": "p011_legacy_package_validator",
            "validation_status": "FAIL",
            "error": str(error),
            "device_execution": "UNVERIFIED",
            "device_package_acceptance": "PENDING",
        }
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else _human_report(report))
    return 0 if report.get("validation_status") == "PASS" else 1


def _human_report(report: dict[str, Any]) -> str:
    lines = [
        "P011 historical v0.1.0 package validation",
        f"validation_status={report.get('validation_status')}",
    ]
    levels = report.get("integrity_levels", {})
    for key in (
        "archive_sha256", "published_checksum_scope", "published_checksum_entries",
        "full_payload_manifest", "derived_payload_inventory", "signer_provenance",
        "embedded_entitlements", "signature_integrity", "device_package_acceptance",
    ):
        if key in levels:
            lines.append(f"{key}={levels[key]}")
    if report.get("error"):
        lines.append(f"error={report['error']}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
