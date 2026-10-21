#!/usr/bin/env python3
"""Safe P018 evidence inventory and explicit diagnostic export tooling.

The source discovery list is intentionally fixed. It does not walk /var or
include arbitrary logs, credentials, network addresses, or user files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import signal
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import p018_validate_export


SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 256 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILES = 129
SOURCE_CLASSES = {
    "SIMULATED", "MOCK", "CI", "DEVICE_REPORTED", "EXTERNAL_OBSERVER",
    "OPERATOR_RECORDED", "UNKNOWN",
}
SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|passphrase|secret|token|credential|private.?key|ssh.?key|auth.?key)", re.I,
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
DATA_ROOT_DEFAULT = Path("/var/lib/ioscaffeinate/evidence")
DOC_ROOT = Path(__file__).resolve().parents[1]
P009_VALIDATOR = Path(__file__).resolve().with_name("p009_evidence.py")
CLI_PATH = Path("/usr/local/bin/ios-caffeinate")


class EvidenceError(ValueError):
    pass


class ExportInterrupted(InterruptedError):
    pass


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise EvidenceError("JSON contains a non-standard numeric value")


def parse_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates,
                          parse_constant=_reject_constant)
    except EvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise EvidenceError(f"{label} is not valid UTF-8 JSON") from None


def safe_parts(path: Path) -> tuple[str, ...]:
    if not path.is_absolute():
        raise EvidenceError("source and output paths must be absolute")
    parts = path.parts[1:]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise EvidenceError("path contains a traversal component")
    return parts


def open_absolute(path: Path, *, directory: bool = False,
                  require_root: bool = False) -> tuple[int, os.stat_result]:
    """Open an absolute path while rejecting symlinks in every component."""
    parts = safe_parts(path)
    fd = os.open("/", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        for part in parts[:-1] if not directory else parts:
            parent_info = os.fstat(fd)
            if parent_info.st_mode & 0o022 and not (
                parent_info.st_uid == 0 and parent_info.st_mode & stat.S_ISVTX
            ):
                raise EvidenceError("path traverses a group- or world-writable directory")
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                              getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
            os.close(fd)
            fd = next_fd
        if directory:
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):
                raise EvidenceError("expected a real directory")
            if info.st_mode & 0o022 and not (
                info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            ):
                raise EvidenceError("evidence directory is group- or world-writable")
            if require_root and info.st_uid != 0:
                raise EvidenceError("export directory is not root-owned")
            return fd, info
        parent_info = os.fstat(fd)
        if parent_info.st_mode & 0o022 and not (
            parent_info.st_uid == 0 and parent_info.st_mode & stat.S_ISVTX
        ):
            raise EvidenceError("evidence parent directory is group- or world-writable")
        if require_root and parent_info.st_uid != 0:
            raise EvidenceError("export source directory is not root-owned")
        leaf = parts[-1]
        file_fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
        info = os.fstat(file_fd)
        os.close(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(file_fd)
            raise EvidenceError("evidence path is not a regular file")
        if info.st_nlink != 1:
            os.close(file_fd)
            raise EvidenceError("evidence file has unsafe hard links")
        return file_fd, info
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def read_source(path: Path, *, require_root: bool = False) -> tuple[bytes, os.stat_result]:
    fd, before = open_absolute(path, require_root=require_root)
    try:
        if before.st_size < 0 or before.st_size > MAX_FILE_BYTES:
            raise EvidenceError("evidence file exceeds its size limit")
        if require_root and before.st_uid != 0:
            raise EvidenceError("export source is not root-owned")
        data = bytearray()
        while len(data) <= MAX_FILE_BYTES:
            chunk = os.read(fd, min(65536, MAX_FILE_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ) or len(data) != before.st_size:
            raise EvidenceError("evidence file changed while being read")
        return bytes(data), after
    finally:
        os.close(fd)


def scan_sensitive(value: Any, key: str = "", depth: int = 0) -> None:
    if depth > 32:
        raise EvidenceError("evidence nesting exceeds its validation limit")
    if key and SECRET_KEY_RE.search(key):
        raise EvidenceError("evidence contains a prohibited credential-like field")
    if key and IDENTIFIER_KEY_RE.search(key):
        raise EvidenceError("evidence contains an unnecessary device or network identifier field")
    if isinstance(value, dict):
        for child_key, child in value.items():
            scan_sensitive(child, str(child_key), depth + 1)
    elif isinstance(value, list):
        for child in value:
            scan_sensitive(child, depth=depth + 1)
    elif isinstance(value, str):
        if SECRET_VALUE_RE.search(value):
            raise EvidenceError("evidence contains key or token material")
        for candidate in IPV4_RE.findall(value):
            if all(int(part) <= 255 for part in candidate.split(".")):
                raise EvidenceError("evidence contains an unredacted IPv4 address")
        for candidate in IPV6_CANDIDATE_RE.findall(value):
            try:
                ipaddress.IPv6Address(candidate)
            except ipaddress.AddressValueError:
                continue
            raise EvidenceError("evidence contains an unredacted IPv6 address")
        if MAC_RE.search(value):
            raise EvidenceError("evidence contains an unredacted MAC address")
        if PRIVATE_PATH_RE.search(value):
            raise EvidenceError("evidence contains a private home or application-data path")


def source_catalog(data_root: Path) -> list[dict[str, Any]]:
    fixed = [
        ("p009-session", data_root / "p009/session.json", "application/json", "P009", "evidence/p009/session.json"),
        ("p009-manifest", data_root / "p009/manifest.json", "application/json", "P009", "evidence/p009/manifest.json"),
        ("p011-package-acceptance", data_root / "p011/package-acceptance.json", "application/json", "P011", "evidence/p011/package-acceptance.json"),
        ("p012-trial-record", data_root / "p012/trial-record.json", "application/json", "P012", "evidence/p012/trial-record.json"),
        ("p013-launchd-observation", data_root / "p013/launchd-observation.json", "application/json", "P013", "evidence/p013/launchd-observation.json"),
        ("p014-recovery-observation", data_root / "p014/recovery-observation.json", "application/json", "P014", "evidence/p014/recovery-observation.json"),
        ("p015-policy-observation", data_root / "p015/policy-observation.json", "application/json", "P015", "evidence/p015/policy-observation.json"),
        ("p016-health-observation", data_root / "p016/health-observation.json", "application/json", "P016", "evidence/p016-health-observation.json"),
        ("p017-schedule-observation", data_root / "p017/schedule-observation.json", "application/json", "P017", "evidence/p017-schedule-observation.json"),
        ("p010-operator-reported", DOC_ROOT / "docs/evidence/P010-OPERATOR-REPORTED.json",
         "application/json", "P010", "evidence/p010/operator-reported.json"),
    ]
    return [{"source_id": ident, "path": path, "content_type": kind,
             "milestone": milestone, "export_path": export_path,
             "export_default": ident != "p010-operator-reported"}
            for ident, path, kind, milestone, export_path in fixed]


def classify_json(source_id: str, raw: bytes) -> tuple[str, str, str]:
    value = parse_json(raw, source_id)
    if not isinstance(value, dict):
        return "UNKNOWN", "UNREVIEWED", "INVALID_RECORD_SHAPE"
    origin = value.get("evidence_origin", value.get("source_class", "UNKNOWN"))
    if origin not in SOURCE_CLASSES:
        origin = "UNKNOWN"
    claimed_review = value.get("review_status")
    if claimed_review == "REVIEWED":
        review = "REVIEWED_CLAIMED"
    elif claimed_review == "REVIEW_REQUIRED":
        review = "REVIEW_REQUIRED"
    else:
        review = "UNREVIEWED"
    return origin, review, "PARSED_NOT_ACCEPTED"


def p009_validation(directory: Path, *, require_root: bool = False) -> tuple[str, list[str]]:
    if not P009_VALIDATOR.is_file() or P009_VALIDATOR.is_symlink():
        return "UNAVAILABLE", []
    try:
        directory_fd, directory_stat = open_absolute(directory, directory=True,
                                                     require_root=require_root)
        os.close(directory_fd)
        if not stat.S_ISDIR(directory_stat.st_mode) or stat.S_ISLNK(directory.lstat().st_mode):
            return "INVALID", []
    except (OSError, EvidenceError):
        return "INVALID", []
    try:
        result = subprocess.run(
            [sys.executable, str(P009_VALIDATOR), "validate", str(directory), "--json"],
            capture_output=True, text=True, timeout=10, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONNOUSERSITE": "1"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return "UNAVAILABLE", []
    if result.returncode != 0:
        return "INVALID", []
    try:
        report = json.loads(result.stdout, object_pairs_hook=_pairs_no_duplicates)
    except (json.JSONDecodeError, EvidenceError):
        return "INVALID", []
    if not isinstance(report, dict) or report.get("structural_validation") != "PASS":
        return "INVALID", []
    try:
        manifest_raw, _ = read_source(directory / "manifest.json",
                                      require_root=require_root)
        manifest = parse_json(manifest_raw, "P009 manifest")
    except (OSError, EvidenceError):
        return "INVALID", []
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        return "INVALID", []
    paths = [entry.get("path") for entry in files if isinstance(entry, dict)]
    if len(paths) != len(files) or not all(isinstance(path, str) for path in paths):
        return "INVALID", []
    return "VALID", sorted(set(paths))


def collect_inventory(data_root: Path, *, require_root: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    export_sources: list[dict[str, Any]] = []
    total = 0
    p009_dir = data_root / "p009"
    p009_state = "MISSING"
    p009_attachments: list[str] = []
    if p009_dir.exists() or p009_dir.is_symlink():
        p009_state, p009_attachments = p009_validation(p009_dir, require_root=require_root)
    for source in source_catalog(data_root):
        path: Path = source["path"]
        record: dict[str, Any] = {
            "source_id": source["source_id"],
            "milestone": source["milestone"],
            "state": "MISSING",
            "content_type": source["content_type"],
            "provenance": "UNKNOWN",
            "review_state": "UNREVIEWED",
            "acceptance": "NOT_INFERRED",
        }
        if not source["export_default"]:
            record["export_status"] = "OPT_IN_REQUIRED"
        try:
            raw, info = read_source(path, require_root=require_root)
            if source["content_type"] == "application/json":
                parsed = parse_json(raw, source["source_id"])
                if source["export_default"]:
                    scan_sensitive(parsed)
                provenance, review_state, validation_state = classify_json(source["source_id"], raw)
                record["provenance"] = provenance
                record["review_state"] = review_state
            else:
                raw.decode("utf-8")
                scan_sensitive(raw.decode("utf-8"))
                validation_state = "PARSED_NOT_ACCEPTED"
            total += len(raw)
            record["state"] = "PRESENT"
            record["size_bytes"] = len(raw)
            record["validation_state"] = "P009_" + p009_state if source["milestone"] == "P009" else validation_state
            if total > MAX_TOTAL_BYTES:
                record["state"] = "INVALID"
                record["validation_state"] = "TOTAL_SIZE_LIMIT"
            elif source["export_default"] and (source["milestone"] != "P009" or p009_state == "VALID"):
                export_sources.append({**source, "record": record, "stat": info,
                                       "raw": raw, "source_relative": None})
        except FileNotFoundError:
            pass
        except (OSError, UnicodeDecodeError, EvidenceError) as error:
            record["state"] = "INVALID"
            record["validation_state"] = safe_error_code(str(error))
        items.append(record)

    if p009_dir.exists() or p009_dir.is_symlink():
        try:
            state, attachment_paths = p009_state, p009_attachments
            for item in items:
                if item["source_id"] in ("p009-session", "p009-manifest"):
                    if item["state"] == "PRESENT":
                        item["validation_state"] = "P009_" + state
            if state == "VALID":
                existing = {item["source_id"] for item in items}
                for rel in attachment_paths:
                    normalized = PurePosixPath(rel)
                    if normalized.is_absolute() or any(part in ("", ".", "..") for part in normalized.parts):
                        raise EvidenceError("P009 manifest path is unsafe")
                    suffix = normalized.suffix.lower()
                    content_type = {".json": "application/json", ".txt": "text/plain",
                                    ".csv": "text/csv"}.get(suffix)
                    if content_type is None:
                        raise EvidenceError("P009 attachment file type is unsupported for export")
                    source_id = "p009-attachment-" + hashlib.sha256(rel.encode()).hexdigest()[:12]
                    raw, info = read_source(p009_dir / rel, require_root=require_root)
                    if content_type in ("application/json", "text/plain", "text/csv"):
                        decoded = raw.decode("utf-8")
                        if content_type == "application/json": scan_sensitive(parse_json(raw, rel))
                        else: scan_sensitive(decoded)
                    export_sources.append({
                        "source_id": source_id, "path": p009_dir / rel,
                        "content_type": content_type, "milestone": "P009",
                        "record": {"provenance": "UNKNOWN", "review_state": "UNREVIEWED"},
                        "stat": info, "raw": raw,
                        "source_relative": "evidence/p009/evidence/" + rel,
                    })
        except (OSError, EvidenceError) as error:
            export_sources = [source for source in export_sources if source["milestone"] != "P009"]
            for item in items:
                if item["source_id"] in ("p009-session", "p009-manifest") and item["state"] == "PRESENT":
                    item["validation_state"] = safe_error_code(str(error))
    items.sort(key=lambda item: item["source_id"])
    export_sources.sort(key=lambda source: source["source_id"])
    return items, export_sources


def safe_error_code(message: str) -> str:
    lowered = message.lower()
    if "symbolic" in lowered or "symlink" in lowered: return "SYMLINK_BLOCKED"
    if "hard link" in lowered: return "HARDLINK_BLOCKED"
    if "credential" in lowered or "key or token" in lowered: return "SECRET_MATERIAL_BLOCKED"
    if "address" in lowered: return "NETWORK_ADDRESS_BLOCKED"
    if "size" in lowered: return "SIZE_LIMIT"
    if "utf-8" in lowered: return "INVALID_ENCODING"
    if "root-owned" in lowered: return "OWNER_NOT_ROOT"
    if "duplicate" in lowered: return "DUPLICATE_JSON_KEY"
    return "INVALID_SOURCE"


def inventory_report(data_root: Path, *, require_root: bool = False) -> dict[str, Any]:
    items, _ = collect_inventory(data_root, require_root=require_root)
    present = sum(item["state"] == "PRESENT" for item in items)
    invalid = sum(item["state"] == "INVALID" for item in items)
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "evidence.inventory",
        "inventory_status": "INVALID" if invalid else "AVAILABLE" if present else "EMPTY",
        "present_count": present,
        "invalid_count": invalid,
        "items": items,
        "hardware_evidence_accepted": "NOT_ESTABLISHED",
    }


def emit_report(report: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return
    for key in ("schema_version", "command", "inventory_status", "present_count",
                "invalid_count", "hardware_evidence_accepted", "export_status",
                "validation_status", "export_directory", "export_created"):
        if key in report:
            print(f"{key}={report[key]}")
    for item in report.get("items", []):
        prefix = "evidence." + item["source_id"]
        for key in ("milestone", "state", "provenance", "review_state", "acceptance", "validation_state", "export_status"):
            if key in item:
                print(f"{prefix}.{key}={item[key]}")
        if "size_bytes" in item:
            print(f"{prefix}.size_bytes={item['size_bytes']}")
    for source in report.get("would_export", []):
        print(f"would_export={source}")
    if "error_code" in report:
        operation = str(report.get("operation", report.get("command", "evidence")))
        print(f"error.operation={operation}")
        print(f"error.code={report['error_code']}")
        print(f"error.reason={report.get('error_reason', 'UNKNOWN')}")
        print(f"changed={report.get('changed', 'no')}")
        print(f"cleanup={report.get('cleanup', 'not_applicable')}")
        print(f"next_safe_step={report.get('next_safe_step', 'inspect_evidence_status')}")


def doctor_snapshot() -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    if CLI_PATH.is_file() and not CLI_PATH.is_symlink():
        try:
            result = subprocess.run([str(CLI_PATH), "doctor", "--json"], capture_output=True,
                                    timeout=12, check=False,
                                    env={"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"})
            if result.returncode == 0:
                value = parse_json(result.stdout, "doctor output")
                if isinstance(value, dict) and value.get("schema_version") == 1 and isinstance(value.get("checks"), list):
                    for check in value["checks"]:
                        if isinstance(check, dict) and all(isinstance(check.get(key), str)
                            for key in ("component", "status", "next_safe_step")):
                            checks.append({key: check[key] for key in ("component", "status", "next_safe_step")})
        except (OSError, subprocess.TimeoutExpired, EvidenceError):
            checks = []
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_status": "AVAILABLE" if checks else "UNAVAILABLE",
        "checks": checks,
        "source_class": "UNKNOWN",
        "hardware_evidence_accepted": "NOT_ESTABLISHED",
    }


def export_path(path: Path) -> tuple[int, str, int]:
    parts = safe_parts(path)
    parent_path = Path("/").joinpath(*parts[:-1])
    if not parent_path.is_dir():
        raise EvidenceError("export destination parent must already exist")
    parent_fd, parent_info = open_absolute(parent_path, directory=True)
    try:
        if parent_info.st_uid != 0:
            raise EvidenceError("export parent is not root-owned")
        if parent_info.st_mode & 0o022 and not (parent_info.st_mode & stat.S_ISVTX):
            raise EvidenceError("export parent is writable by group or other users")
        os.mkdir(parts[-1], 0o700, dir_fd=parent_fd)
        destination_fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                 getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        info = os.fstat(destination_fd)
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            os.close(destination_fd)
            os.rmdir(parts[-1], dir_fd=parent_fd)
            raise EvidenceError("export directory ownership or permissions are unsafe")
        return destination_fd, parts[-1], parent_fd
    except Exception:
        os.close(parent_fd)
        raise


def write_new_file(directory_fd: int, relative: str, data: bytes,
                   created: list[tuple[int, str]],
                   created_dirs: list[tuple[int, str]]) -> os.stat_result:
    parts = PurePosixPath(relative).parts
    current_fd = os.dup(directory_fd)
    try:
        for part in parts[:-1]:
            made = False
            try:
                os.mkdir(part, 0o700, dir_fd=current_fd)
                made = True
            except FileExistsError:
                pass
            if made:
                created_dirs.append((os.dup(current_fd), part))
            next_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                              getattr(os, "O_NOFOLLOW", 0), dir_fd=current_fd)
            current_info = os.fstat(next_fd)
            if current_info.st_uid != 0 or stat.S_IMODE(current_info.st_mode) != 0o700:
                os.close(next_fd)
                raise EvidenceError("export subdirectory ownership or permissions are unsafe")
            os.close(current_fd)
            current_fd = next_fd
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=current_fd)
        created.append((os.dup(current_fd), parts[-1]))
        try:
            os.fchown(fd, 0, 0)
            os.fchmod(fd, 0o600)
            view = memoryview(data)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise OSError("short write while creating export file")
                view = view[count:]
            os.fsync(fd)
            info = os.fstat(fd)
            if info.st_uid != 0 or info.st_nlink != 1 or info.st_size != len(data):
                raise EvidenceError("export file ownership or final size is unsafe")
            return info
        finally:
            os.close(fd)
    finally:
        os.close(current_fd)


def cleanup_export(directory_fd: int, parent_fd: int, name: str,
                   created: list[tuple[int, str]],
                   created_dirs: list[tuple[int, str]], manifest_tmp: str | None,
                   manifest_written: bool) -> None:
    if manifest_tmp:
        try: os.unlink(manifest_tmp, dir_fd=directory_fd)
        except OSError: pass
    if manifest_written:
        try: os.unlink("manifest.json", dir_fd=directory_fd)
        except OSError: pass
    for directory_fd_item, file_name in reversed(created):
        try: os.unlink(file_name, dir_fd=directory_fd_item)
        except OSError: pass
        try: os.close(directory_fd_item)
        except OSError: pass
    for parent_fd_item, directory_name in reversed(created_dirs):
        try: os.rmdir(directory_name, dir_fd=parent_fd_item)
        except OSError: pass
        try: os.close(parent_fd_item)
        except OSError: pass
    try: os.close(directory_fd)
    except OSError: pass
    try: os.rmdir(name, dir_fd=parent_fd)
    except OSError: pass
    try: os.close(parent_fd)
    except OSError: pass


def operator_file_source(path: Path) -> dict[str, Any]:
    if not path.is_absolute():
        raise EvidenceError("operator evidence file path must be absolute")
    suffix = path.suffix.lower()
    content_type = {".json": "application/json", ".txt": "text/plain",
                    ".csv": "text/csv"}.get(suffix)
    if content_type is None:
        raise EvidenceError("operator evidence file type must be JSON, UTF-8 text, or CSV")
    raw, info = read_source(path, require_root=True)
    if content_type == "application/json":
        scan_sensitive(parse_json(raw, "operator evidence file"))
    else:
        scan_sensitive(raw.decode("utf-8"))
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "source_id": "operator-file-" + digest[:16],
        "path": path,
        "content_type": content_type,
        "milestone": "OPERATOR",
        "export_path": "evidence/operator/" + digest + suffix,
        "record": {"provenance": "UNKNOWN", "review_state": "UNREVIEWED",
                   "validation_state": "VALIDATED_NOT_ACCEPTED"},
        "stat": info,
        "raw": raw,
        "source_relative": None,
    }


def export_bundle(destination: Path, data_root: Path,
                  operator_files: list[Path] | None = None) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise EvidenceError("explicit export requires root on the rootful device")
    items, sources = collect_inventory(data_root, require_root=True)
    safe_sources = [source for source in sources if source["record"].get("validation_state", "PARSED_NOT_ACCEPTED") != "INVALID_RECORD_SHAPE"]
    for path in operator_files or []:
        safe_sources.append(operator_file_source(path))
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    destination_fd, name, parent_fd = export_path(destination)
    created: list[tuple[int, str]] = []
    created_dirs: list[tuple[int, str]] = []
    manifest_tmp: str | None = None
    manifest_written = False
    try:
        inventory_bytes = (json.dumps(inventory_report(data_root, require_root=True), sort_keys=True,
                                      separators=(",", ":")) + "\n").encode()
        doctor_bytes = (json.dumps(doctor_snapshot(), sort_keys=True,
                                   separators=(",", ":")) + "\n").encode()
        prepared: list[tuple[str, bytes, str, str, str, str]] = [
            ("snapshots/inventory.json", inventory_bytes, "application/json",
             "diagnostic-inventory", "UNKNOWN", "UNREVIEWED"),
            ("snapshots/doctor.json", doctor_bytes, "application/json",
             "read-only-doctor", "UNKNOWN", "UNREVIEWED"),
        ]
        total = len(inventory_bytes) + len(doctor_bytes)
        for source in safe_sources:
            raw, current_info = read_source(source["path"], require_root=True)
            original_info = source["stat"]
            if raw != source["raw"] or (current_info.st_dev, current_info.st_ino,
                    current_info.st_size, current_info.st_mtime_ns) != (
                    original_info.st_dev, original_info.st_ino,
                    original_info.st_size, original_info.st_mtime_ns):
                raise EvidenceError("evidence source changed before it was copied")
            if len(raw) > MAX_FILE_BYTES:
                raise EvidenceError("source evidence exceeds the export file limit")
            total += len(raw)
            if total > MAX_TOTAL_BYTES or len(prepared) >= MAX_FILES:
                raise EvidenceError("export exceeds the bounded file or total-size limit")
            relative = source.get("source_relative") or source.get("export_path")
            if not relative:
                path = source["path"]
                relative = "evidence/" + source["milestone"].lower() + "/" + source["source_id"] + "." + PurePosixPath(path.name).suffix.lstrip(".")
            relative = PurePosixPath(relative)
            if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
                raise EvidenceError("source mapping generated an unsafe export path")
            prepared.append((relative.as_posix(), raw, source["content_type"],
                             source["source_id"], source["record"].get("provenance", "UNKNOWN"),
                             source["record"].get("review_state", "UNREVIEWED")))
        prepared.sort(key=lambda item: item[0])
        if len({item[0] for item in prepared}) != len(prepared):
            raise EvidenceError("two allowlisted source records map to the same export path")
        manifest_files: list[dict[str, Any]] = []
        for relative, content, content_type, source_id, provenance, review_state in prepared:
            if content_type not in ("application/json", "text/plain", "text/csv", "image/jpeg", "image/png", "application/octet-stream"):
                raise EvidenceError("source content type is not allowed")
            if provenance not in SOURCE_CLASSES:
                provenance = "UNKNOWN"
            if content_type == "application/json":
                scan_sensitive(parse_json(content, relative))
            elif content_type in ("text/plain", "text/csv"):
                scan_sensitive(content.decode("utf-8"))
            file_info = write_new_file(destination_fd, relative, content, created,
                                       created_dirs)
            if file_info.st_size != len(content):
                raise EvidenceError("export file changed before its checksum was finalized")
            manifest_files.append({
                "path": relative,
                "size_bytes": file_info.st_size,
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_type": content_type,
                "source_id": source_id,
                "provenance": provenance,
                "review_state": review_state if review_state in (
                    "UNREVIEWED", "REVIEW_REQUIRED", "REVIEWED_CLAIMED", "UNKNOWN"
                ) else "UNKNOWN",
            })
        if len(manifest_files) > MAX_FILES:
            raise EvidenceError("export contains too many files")
        package_version = "UNAVAILABLE"
        source_commit = "UNAVAILABLE"
        try:
            build_record, _ = read_source(Path("/usr/share/ioscaffeinate/package-build.json"), require_root=True)
            metadata = parse_json(build_record, "installed package build metadata")
            if isinstance(metadata.get("package_version"), str):
                package_version = metadata["package_version"]
            if isinstance(metadata.get("source_commit_sha"), str):
                source_commit = metadata["source_commit_sha"]
        except (OSError, EvidenceError):
            pass
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "export_type": "ioscaffeinate-diagnostic-bundle",
            "exported_at_utc": now,
            "package_identifier": "com.ioscaffeinate.cli",
            "source_metadata": {
                "package_version": package_version,
                "source_commit_sha": source_commit,
                "export_tool": "p018_evidence.py",
            },
            "files": manifest_files,
            "validation_report": {
                "status": "REQUIRES_STANDALONE_VALIDATOR",
                "validator": "p018_validate_export.py",
                "scope": "schema_paths_types_sizes_hashes_encoding_privacy",
            },
            "hardware_evidence_accepted": "NOT_ESTABLISHED",
            "privacy_notice": "Review every included source before sharing; hashes establish consistency, not provenance.",
        }
        manifest_bytes = (json.dumps(manifest, ensure_ascii=True, sort_keys=True,
                                     separators=(",", ":")) + "\n").encode()
        manifest_tmp = ".manifest.tmp"
        tmp_fd = os.open(manifest_tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=destination_fd)
        try:
            os.fchown(tmp_fd, 0, 0); os.fchmod(tmp_fd, 0o600)
            view = memoryview(manifest_bytes)
            while view:
                count = os.write(tmp_fd, view)
                if count <= 0: raise OSError("short manifest write")
                view = view[count:]
            os.fsync(tmp_fd)
        finally:
            os.close(tmp_fd)
        os.link(manifest_tmp, "manifest.json", src_dir_fd=destination_fd,
                dst_dir_fd=destination_fd, follow_symlinks=False)
        manifest_written = True
        os.unlink(manifest_tmp, dir_fd=destination_fd)
        manifest_tmp = None
        os.fsync(destination_fd)
        p018_validate_export.validate_bundle(destination)
        os.fsync(parent_fd)
        for descriptor, _ in created:
            os.close(descriptor)
        for descriptor, _ in created_dirs:
            os.close(descriptor)
        os.close(destination_fd)
        os.close(parent_fd)
        return {
            "schema_version": SCHEMA_VERSION,
            "command": "evidence.export",
            "export_status": "EXPORT_CREATED",
            "export_directory": str(destination),
            "export_created": "yes",
            "files_exported": len(manifest_files),
            "hardware_evidence_accepted": "NOT_ESTABLISHED",
            "privacy_review_required": "yes",
        }
    except BaseException:
        cleanup_export(destination_fd, parent_fd, name, created, created_dirs,
                       manifest_tmp, manifest_written)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "inventory", "validate"):
        item = sub.add_parser(command)
        item.add_argument("--json", action="store_true")
        item.add_argument("--root", type=Path, default=DATA_ROOT_DEFAULT)
    export = sub.add_parser("export")
    mode = export.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--output", type=Path)
    export.add_argument("--json", action="store_true")
    export.add_argument("--root", type=Path, default=DATA_ROOT_DEFAULT)
    export.add_argument("--include-operator-file", action="append", type=Path, default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.absolute()
    try:
        if args.command in ("status", "inventory"):
            report = inventory_report(root)
            report["command"] = "evidence." + args.command
            if args.command == "status":
                report["items"] = [item for item in report["items"] if item["state"] != "MISSING"]
            emit_report(report, args.json)
            return 1 if report["inventory_status"] == "INVALID" else 0
        if args.command == "validate":
            items, _sources = collect_inventory(root)
            p009_dir = root / "p009"
            p009_state = "MISSING"
            if p009_dir.exists() or p009_dir.is_symlink():
                p009_state, _ = p009_validation(p009_dir)
            invalid = sum(item["state"] == "INVALID" for item in items)
            report = {
                "schema_version": SCHEMA_VERSION,
                "command": "evidence.validate",
                "validation_status": "INVALID" if invalid or p009_state == "INVALID" else
                    "INCOMPLETE" if p009_state in ("MISSING", "UNAVAILABLE") else "VALIDATED_NOT_ACCEPTED",
                "p009_validation": p009_state,
                "items": items,
                "hardware_evidence_accepted": "NOT_ESTABLISHED",
            }
            emit_report(report, args.json)
            return 1 if report["validation_status"] == "INVALID" else 0
        if args.command == "export" and args.dry_run:
            _items, sources = collect_inventory(root)
            names = [source["source_id"] for source in sources]
            for path in args.include_operator_file:
                names.append(operator_file_source(path)["source_id"])
            report = {
                "schema_version": SCHEMA_VERSION,
                "command": "evidence.export",
                "export_status": "DRY_RUN",
                "export_created": "no",
                "would_export": ["diagnostic-inventory", "read-only-doctor"] + names,
                "hardware_evidence_accepted": "NOT_ESTABLISHED",
                "privacy_review_required": "yes",
            }
            emit_report(report, args.json)
            return 0
        if args.command == "export" and args.output:
            destination = args.output
            if not destination.is_absolute():
                raise EvidenceError("export destination must be an absolute path")
            report = export_bundle(destination, root, args.include_operator_file)
            emit_report(report, args.json)
            return 0
    except (EvidenceError, OSError, ExportInterrupted, p018_validate_export.ExportValidationError) as error:
        if isinstance(error, FileExistsError):
            code = "UNSAFE_STATE"; next_step = "choose_a_new_empty_export_destination"
        elif "root" in str(error).lower():
            code = "PERMISSION_DENIED"; next_step = "run_export_as_root_after_privacy_review"
        elif "symlink" in str(error).lower() or "hard link" in str(error).lower() or "destination" in str(error).lower():
            code = "UNSAFE_STATE"; next_step = "inspect_source_and_destination_paths_without_following_links"
        elif isinstance(error, ExportInterrupted):
            code = "IO_ERROR"; next_step = "inspect_destination_for_incomplete_files"
        else:
            code = "INTEGRITY_FAILED"; next_step = "inspect_evidence_status_and_validate_the_source"
        report = {
            "schema_version": SCHEMA_VERSION,
            "command": "evidence." + args.command,
            "operation": "evidence_" + args.command.replace("-", "_"),
            "error_code": code,
            "error_reason": safe_error_code(str(error)),
            "next_safe_step": next_step,
            "changed": "no" if args.command != "export" or args.dry_run else "unknown",
            "cleanup": "unknown" if args.command == "export" and not args.dry_run else "not_applicable",
            "hardware_evidence_accepted": "NOT_ESTABLISHED",
        }
        emit_report(report, args.json)
        return 1
    return 2


def _interrupt_handler(_signum: int, _frame: Any) -> None:
    raise ExportInterrupted("export interrupted")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _interrupt_handler)
    signal.signal(signal.SIGTERM, _interrupt_handler)
    sys.exit(main())
