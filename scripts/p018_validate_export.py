#!/usr/bin/env python3
"""Offline validator for iOS-Caffeinate P018 export bundles.

This validator reads bundle content only. It never executes files from a bundle
and never infers physical authenticity from hashes or schema validity.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 256 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILES = 129
MAX_DIRECTORY_ENTRIES = MAX_FILES * 2
MAX_DIRECTORY_DEPTH = 16
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_CLASSES = {
    "SIMULATED", "MOCK", "CI", "DEVICE_REPORTED", "EXTERNAL_OBSERVER",
    "OPERATOR_RECORDED", "UNKNOWN",
}
SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|passphrase|secret|token|credential|private.?key|ssh.?key|auth.?key)",
    re.I,
)
SECRET_VALUE_RE = re.compile(
    r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PGP|PRIVATE) KEY-----|"
    r"\btskey-(?:auth|api)-[A-Za-z0-9_-]{8,}|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}", re.I,
)
IPV4_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
IPV6_CANDIDATE_RE = re.compile(r"(?<![A-Fa-f0-9:])(?:[A-Fa-f0-9]{0,4}:){2,7}[A-Fa-f0-9]{0,4}(?![A-Fa-f0-9:])")
MAC_RE = re.compile(r"(?<![A-Fa-f0-9])(?:[A-Fa-f0-9]{2}[:-]){5}[A-Fa-f0-9]{2}(?![A-Fa-f0-9])")
PRIVATE_PATH_RE = re.compile(r"(?:^|[\s\"'=])/(?:Users|home)/[^/\s]+|/var/mobile/Containers/Data/Application/[^/\s]+")
IDENTIFIER_KEY_RE = re.compile(r"(?:serial(?:number)?|udid|imei|meid|mac(?:_address)?|assertion.?id)", re.I)
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ExportValidationError(ValueError):
    pass


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExportValidationError("JSON contains a duplicate object key")
        result[key] = value
    return result


def reject_constant(_: str) -> None:
    raise ExportValidationError("JSON contains a non-standard numeric value")


def strict_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                          parse_constant=reject_constant)
    except ExportValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ExportValidationError(f"{label} is not valid UTF-8 JSON") from None


def safe_relative(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ExportValidationError("manifest contains an invalid path")
    if "\\" in value or "\x00" in value:
        raise ExportValidationError("manifest contains an invalid path separator")
    parts = value.split("/")
    if value.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ExportValidationError("manifest contains an absolute or traversing path")
    if not all(re.fullmatch(r"[A-Za-z0-9._-]{1,128}", part) for part in parts):
        raise ExportValidationError("manifest path contains an unsupported name")
    if parts[0] not in ("evidence", "snapshots"):
        raise ExportValidationError("manifest path is outside the allowed bundle folders")
    return PurePosixPath(*parts).as_posix()


def open_beneath(root_fd: int, relative: str) -> int:
    """Open a regular file without following any path component symlink."""
    parts = PurePosixPath(relative).parts
    current_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                              getattr(os, "O_NOFOLLOW", 0), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                       dir_fd=current_fd)
    except OSError as error:
        raise ExportValidationError("bundle path cannot be opened safely") from error
    finally:
        os.close(current_fd)


def open_bundle_directory(path: Path) -> int:
    if not path.is_absolute() or any(part in ("", ".", "..") for part in path.parts[1:]):
        raise ExportValidationError("bundle path must be an absolute normalized path")
    fd = os.open("/", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                              getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
            os.close(fd)
            fd = next_fd
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise ExportValidationError("bundle path is not a directory")
        return fd
    except Exception:
        os.close(fd)
        raise


def scan_sensitive(value: Any, key: str = "", depth: int = 0) -> None:
    if depth > 32:
        raise ExportValidationError("bundle nesting exceeds its validation limit")
    if key and SECRET_KEY_RE.search(key):
        raise ExportValidationError("bundle contains a prohibited credential-like field")
    if key and IDENTIFIER_KEY_RE.search(key):
        raise ExportValidationError("bundle contains an unnecessary device or network identifier field")
    if isinstance(value, dict):
        for child_key, child in value.items():
            scan_sensitive(child, str(child_key), depth + 1)
    elif isinstance(value, list):
        for child in value:
            scan_sensitive(child, depth=depth + 1)
    elif isinstance(value, str):
        if SECRET_VALUE_RE.search(value):
            raise ExportValidationError("bundle contains private-key or token material")
        for candidate in IPV4_RE.findall(value):
            octets = candidate.split(".")
            if all(part.isdigit() and int(part) <= 255 for part in octets):
                raise ExportValidationError("bundle contains an unredacted IPv4 address")
        for candidate in IPV6_CANDIDATE_RE.findall(value):
            try:
                ipaddress.IPv6Address(candidate)
            except ipaddress.AddressValueError:
                continue
            raise ExportValidationError("bundle contains an unredacted IPv6 address")
        if MAC_RE.search(value):
            raise ExportValidationError("bundle contains an unredacted MAC address")
        if PRIVATE_PATH_RE.search(value):
            raise ExportValidationError("bundle contains a private home or application-data path")


def file_list(root_fd: int, prefix: str = "") -> list[str]:
    found: list[str] = []
    pending: list[tuple[int, str, int]] = [(os.dup(root_fd), prefix, 0)]
    entries_seen = 0
    while pending:
        directory_fd, current_prefix, depth = pending.pop()
        try:
            with os.scandir(os.dup(directory_fd)) as entries:
                for entry in entries:
                    entries_seen += 1
                    if entries_seen > MAX_DIRECTORY_ENTRIES:
                        raise ExportValidationError("bundle contains too many directory entries")
                    name = entry.name
                    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", name):
                        raise ExportValidationError("bundle contains an unsupported file name")
                    relative = f"{current_prefix}/{name}" if current_prefix else name
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        raise ExportValidationError("bundle contains a symbolic link")
                    if stat.S_ISDIR(info.st_mode):
                        if depth >= MAX_DIRECTORY_DEPTH:
                            raise ExportValidationError("bundle directory nesting exceeds its limit")
                        child = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                        getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                        pending.append((child, relative, depth + 1))
                    elif stat.S_ISREG(info.st_mode):
                        if relative != "manifest.json":
                            found.append(safe_relative(relative))
                    else:
                        raise ExportValidationError("bundle contains a special file")
        except OSError as error:
            raise ExportValidationError("bundle directory cannot be inspected safely") from error
        finally:
            os.close(directory_fd)
    if len(found) > MAX_FILES:
        raise ExportValidationError("bundle contains too many files")
    return sorted(found)


def validate_bundle(bundle: Path) -> dict[str, Any]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise ExportValidationError("bundle path must be a real directory")
    root_fd = open_bundle_directory(bundle)
    try:
        manifest_fd = open_beneath(root_fd, "manifest.json")
        try:
            manifest_stat = os.fstat(manifest_fd)
            if not stat.S_ISREG(manifest_stat.st_mode) or manifest_stat.st_nlink != 1:
                raise ExportValidationError("manifest must be a non-linked regular file")
            if manifest_stat.st_size > MAX_MANIFEST_BYTES:
                raise ExportValidationError("manifest exceeds its size limit")
            raw_manifest = os.read(manifest_fd, MAX_MANIFEST_BYTES + 1)
        finally:
            os.close(manifest_fd)
        manifest = strict_json(raw_manifest, "manifest")
        if not isinstance(manifest, dict):
            raise ExportValidationError("manifest must be an object")
        scan_sensitive(manifest)
        if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != SCHEMA_VERSION:
            raise ExportValidationError("unsupported export schema version")
        if manifest.get("export_type") != "ioscaffeinate-diagnostic-bundle":
            raise ExportValidationError("unsupported export type")
        required_manifest_keys = {
            "schema_version", "export_type", "exported_at_utc", "package_identifier",
            "source_metadata", "files", "validation_report", "hardware_evidence_accepted",
            "privacy_notice",
        }
        if set(manifest) != required_manifest_keys:
            raise ExportValidationError("manifest has missing or unknown fields")
        timestamp = manifest.get("exported_at_utc")
        if not isinstance(timestamp, str):
            raise ExportValidationError("manifest export timestamp is missing")
        try:
            parsed_timestamp = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise ExportValidationError("manifest export timestamp is invalid") from None
        if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
            raise ExportValidationError("manifest export timestamp must include a UTC offset")
        if parsed_timestamp.utcoffset() != dt.timedelta(0):
            raise ExportValidationError("manifest export timestamp must be UTC")
        if manifest.get("package_identifier") != "com.ioscaffeinate.cli":
            raise ExportValidationError("manifest package identity is unsupported")
        metadata = manifest.get("source_metadata")
        if not isinstance(metadata, dict) or set(metadata) != {
            "package_version", "source_commit_sha", "export_tool",
        } or not all(isinstance(value, str) and value for value in metadata.values()):
            raise ExportValidationError("manifest source metadata is invalid")
        report = manifest.get("validation_report")
        if not isinstance(report, dict) or set(report) != {"status", "validator", "scope"} or \
                report.get("status") != "REQUIRES_STANDALONE_VALIDATOR" or \
                report.get("validator") != "p018_validate_export.py":
            raise ExportValidationError("manifest validation report is invalid")
        if not isinstance(manifest.get("privacy_notice"), str) or len(manifest["privacy_notice"]) > 512:
            raise ExportValidationError("manifest privacy notice is invalid")
        if manifest.get("hardware_evidence_accepted") != "NOT_ESTABLISHED":
            raise ExportValidationError("manifest overstates hardware evidence acceptance")
        records = manifest.get("files")
        if not isinstance(records, list) or len(records) > MAX_FILES:
            raise ExportValidationError("manifest file list is invalid or too large")
        seen: set[str] = set()
        total = 0
        for record in records:
            if not isinstance(record, dict):
                raise ExportValidationError("manifest file entry must be an object")
            expected_keys = {"path", "size_bytes", "sha256", "content_type",
                             "source_id", "provenance", "review_state"}
            if set(record) != expected_keys:
                raise ExportValidationError("manifest file entry has missing or unknown fields")
            relative = safe_relative(record.get("path"))
            if relative in seen:
                raise ExportValidationError("manifest contains duplicate file entries")
            seen.add(relative)
            provenance = record.get("provenance")
            if not isinstance(provenance, str) or provenance not in SOURCE_CLASSES:
                raise ExportValidationError("manifest contains an unsupported provenance label")
            if not isinstance(record.get("review_state"), str) or record["review_state"] not in (
                "UNREVIEWED", "REVIEW_REQUIRED", "REVIEWED_CLAIMED", "UNKNOWN",
            ):
                raise ExportValidationError("manifest contains an unsupported review state")
            if not isinstance(record.get("source_id"), str) or not SOURCE_ID_RE.fullmatch(record["source_id"]):
                raise ExportValidationError("manifest contains an invalid source identifier")
            suffix = PurePosixPath(relative).suffix.lower()
            expected_type = {".json": "application/json", ".txt": "text/plain",
                             ".csv": "text/csv"}.get(suffix)
            if expected_type is None or record.get("content_type") != expected_type:
                raise ExportValidationError("bundle contains an unauthorized file type")
            size = record.get("size_bytes")
            if type(size) is not int or size < 0 or size > MAX_FILE_BYTES:
                raise ExportValidationError("manifest file size is outside its bound")
            digest = record.get("sha256")
            if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
                raise ExportValidationError("manifest contains an invalid SHA-256")
            fd = open_beneath(root_fd, relative)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ExportValidationError("bundle file is not a singly linked regular file")
                if info.st_size != size or info.st_size > MAX_FILE_BYTES:
                    raise ExportValidationError("bundle file size does not match the manifest")
                chunks: list[bytes] = []
                remaining = MAX_FILE_BYTES + 1
                while remaining:
                    block = os.read(fd, min(65536, remaining))
                    if not block:
                        break
                    chunks.append(block)
                    remaining -= len(block)
                content = b"".join(chunks)
            finally:
                os.close(fd)
            total += len(content)
            if total > MAX_TOTAL_BYTES:
                raise ExportValidationError("bundle exceeds its total size limit")
            if hashlib.sha256(content).hexdigest() != digest:
                raise ExportValidationError("bundle file checksum mismatch")
            if expected_type == "application/json":
                parsed = strict_json(content, relative)
                scan_sensitive(parsed)
            else:
                try:
                    decoded = content.decode("utf-8")
                except UnicodeDecodeError:
                    raise ExportValidationError("text file is not valid UTF-8") from None
                scan_sensitive(decoded)
        actual = file_list(root_fd)
        if actual != sorted(seen):
            raise ExportValidationError("bundle file list does not exactly match its manifest")
        return {
            "schema_version": SCHEMA_VERSION,
            "validation": "VALID",
            "files_checked": len(records),
            "bytes_checked": total,
            "hardware_evidence_accepted": "NOT_ESTABLISHED",
        }
    finally:
        os.close(root_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = validate_bundle(args.bundle.absolute())
    except (ExportValidationError, OSError) as error:
        report = {
            "schema_version": SCHEMA_VERSION,
            "validation": "INVALID",
            "error": str(error),
            "hardware_evidence_accepted": "NOT_ESTABLISHED",
        }
        if args.json:
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            print("validation=INVALID")
            print(f"error={error}")
            print("hardware_evidence_accepted=NOT_ESTABLISHED")
        return 1
    if args.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        for key, value in report.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
