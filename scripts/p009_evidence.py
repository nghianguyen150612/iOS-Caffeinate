#!/usr/bin/env python3
"""Offline validator, timeline replay, and readiness report for P009 evidence.

The program never opens a network connection and never contacts an iOS device.
It uses only the Python standard library. Integrity checks establish that files
match their manifest; they do not authenticate who created the evidence.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import math
import os
import re
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs/schemas/device-acceptance-gates-v1.json"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_SESSION_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILES = 129
MAX_EVENTS = 10_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SOURCES = {"SIMULATED", "MOCK", "CI", "DEVICE_REPORTED", "EXTERNAL_OBSERVER", "OPERATOR_RECORDED"}
PHYSICAL_SOURCES = {"DEVICE_REPORTED", "EXTERNAL_OBSERVER", "OPERATOR_RECORDED"}
EVENT_TYPES = {
    "DEVICE_PREFLIGHT", "PACKAGE_INTEGRITY_CHECK", "SIGNATURE_ACCEPTANCE", "PACKAGE_INSTALL",
    "PACKAGE_REMOVAL", "ROLLBACK", "DAEMON_LAUNCH", "ASSERTION_ACQUIRE_ATTEMPT",
    "ASSERTION_ACQUIRE_SUCCESS", "ASSERTION_ACQUIRE_FAILURE", "HOLD_ACTIVE", "SCREEN_LOCK",
    "SCREEN_UNLOCK", "LAN_OBSERVATION", "TAILSCALE_OBSERVATION", "EXPLICIT_STOP", "NATURAL_EXPIRY",
    "ASSERTION_RELEASE", "SIGTERM", "DAEMON_EXIT", "PHYSICAL_RECOVERY", "BATTERY_OBSERVATION",
    "THERMAL_OBSERVATION", "SCHEDULED_WAKE_OBSERVATION",
}
SECRET_KEY_RE = re.compile(r"(?:password|passwd|passphrase|secret|token|credential|private.?key|ssh.?key|auth.?key)", re.I)
SECRET_VALUE_RE = re.compile(
    r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PGP|PRIVATE) KEY-----|"
    r"\btskey-(?:auth|api)-[A-Za-z0-9_-]{8,}|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}",
    re.I,
)
SECRET_ASSIGNMENT_RE = re.compile(r"\b(?:password|passwd|passphrase|secret|token|auth[_ -]?key)\s*[:=]\s*\S+", re.I)


class EvidenceError(Exception):
    """An unsafe, malformed, unsupported, or internally inconsistent package."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise EvidenceError("JSON contains a non-standard numeric value")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise EvidenceError("JSON contains a non-finite numeric value")
    return parsed


def parse_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant, parse_float=_parse_finite_float)
    except EvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EvidenceError(f"{label} is not valid UTF-8 JSON") from None


def iso_time(value: Any, label: str) -> dt.datetime:
    if not isinstance(value, str) or "T" not in value:
        raise EvidenceError(f"{label} must be an ISO-8601 date-time")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceError(f"{label} must be an ISO-8601 date-time") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceError(f"{label} must include a UTC offset")
    return parsed.astimezone(dt.timezone.utc)


def safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or "\\" in value or "\x00" in value:
        raise EvidenceError("manifest contains an unsafe relative path")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise EvidenceError("manifest contains a path traversal or absolute path")
    if any(not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", part) for part in parsed.parts):
        raise EvidenceError("manifest path contains an unsupported filename")
    return parsed.as_posix()


def scan_secrets(value: Any, key: str = "") -> None:
    if key and SECRET_KEY_RE.search(key):
        raise EvidenceError("evidence contains a prohibited credential-like field")
    if isinstance(value, dict):
        for child_key, child in value.items():
            scan_secrets(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            scan_secrets(child)
    elif isinstance(value, str) and SECRET_VALUE_RE.search(value):
        raise EvidenceError("evidence contains material that resembles a credential or private key")


def _read_regular_file(root: Path, relative: str, limit: int) -> bytes:
    rel = safe_relative_path(relative)
    path = root.joinpath(*PurePosixPath(rel).parts)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise EvidenceError(f"required evidence file is missing or cannot be opened safely: {rel}") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise EvidenceError(f"evidence path is not a regular file: {rel}")
        if info.st_size > limit:
            raise EvidenceError(f"evidence file exceeds its size limit: {rel}")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            block = os.read(fd, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        data = b"".join(chunks)
        if len(data) > limit:
            raise EvidenceError(f"evidence file exceeds its size limit: {rel}")
        try:
            current = os.stat(path, follow_symlinks=False)
        except OSError:
            raise EvidenceError(f"evidence file changed while it was being read: {rel}") from None
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise EvidenceError(f"evidence file changed while it was being read: {rel}")
        return data
    finally:
        os.close(fd)


def _enumerate_tree(root: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    total = 0
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in list(dirnames):
            path = current_path / name
            rel = path.relative_to(root).as_posix()
            try:
                info = path.lstat()
            except OSError:
                raise EvidenceError("evidence directory changed during inspection") from None
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise EvidenceError("evidence package contains a symlink or non-directory path")
            safe_relative_path(rel)
            directories.add(rel)
        for name in filenames:
            path = current_path / name
            rel = path.relative_to(root).as_posix()
            safe_relative_path(rel)
            try:
                info = path.lstat()
            except OSError:
                raise EvidenceError("evidence directory changed during inspection") from None
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise EvidenceError("evidence package contains a symlink or special file")
            total += info.st_size
            if info.st_size > MAX_EVIDENCE_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise EvidenceError("evidence package exceeds a file or total size limit")
            files.add(rel)
            if len(files) > MAX_FILES:
                raise EvidenceError("evidence package contains too many files")
    return files, directories


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _schema_documents() -> dict[str, dict[str, Any]]:
    paths = (
        ROOT / "docs/schemas/device-acceptance-v1.schema.json",
        ROOT / "docs/schemas/evidence-manifest-v1.schema.json",
        ROOT / "docs/schemas/connectivity-evidence-v1.schema.json",
    )
    documents: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise EvidenceError("a required versioned evidence schema is missing or malformed") from None
        if not isinstance(document, dict) or not isinstance(document.get("$id"), str):
            raise EvidenceError("a required evidence schema has no stable identifier")
        documents[document["$id"]] = document
    return documents


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return type(value) is bool
    if expected == "integer":
        return type(value) is int
    if expected == "number":
        return not isinstance(value, bool) and isinstance(value, (int, float))
    if expected == "null":
        return value is None
    return False


def _schema_errors(value: Any, schema: dict[str, Any], current_document: dict[str, Any], documents: dict[str, dict[str, Any]], path: str = "$", depth: int = 0) -> list[str]:
    if depth > 64:
        return [f"{path}: schema reference depth exceeded"]
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str):
            return [f"{path}: invalid schema reference"]
        if reference.startswith("#/"):
            target = current_document
            pointer = reference[1:]
        elif "#" in reference:
            identifier, fragment = reference.split("#", 1)
            target = documents.get(identifier)
            pointer = fragment
        else:
            target = documents.get(reference)
            pointer = ""
        if not isinstance(target, dict):
            return [f"{path}: unsupported schema reference"]
        for encoded in filter(None, pointer.split("/")):
            key = encoded.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or key not in target:
                return [f"{path}: unresolved schema reference"]
            target = target[key]
        if not isinstance(target, dict):
            return [f"{path}: unresolved schema definition"]
        return _schema_errors(value, target, documents.get(target.get("$id"), current_document) if "$id" in target else (documents.get(reference.split("#", 1)[0], current_document)), documents, path, depth + 1)

    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(_schema_type_matches(value, kind) for kind in choices):
            return [f"{path}: expected {expected}"]
    if "const" in schema and value != schema["const"]:
        return [f"{path}: value does not match schema constant"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: value is outside the allowed values"]
    if "oneOf" in schema:
        variants = schema["oneOf"]
        matches = [not _schema_errors(value, variant, current_document, documents, path, depth + 1) for variant in variants]
        if sum(matches) != 1:
            return [f"{path}: value must match exactly one schema alternative"]
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            errors.append(f"{path}: string length is outside the schema limits")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: string does not match the required pattern")
        if schema.get("format") == "date-time":
            try:
                iso_time(value, path)
            except EvidenceError:
                errors.append(f"{path}: value is not a timezone-qualified date-time")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            errors.append(f"{path}: number is outside the schema limits")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            errors.append(f"{path}: array length is outside the schema limits")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, schema["items"], current_document, documents, f"{path}[{index}]", depth + 1))
                if errors:
                    break
    if isinstance(value, dict):
        if len(value) < schema.get("minProperties", 0) or len(value) > schema.get("maxProperties", float("inf")):
            errors.append(f"{path}: object size is outside the schema limits")
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{path}: missing required field {required}")
        properties = schema.get("properties", {})
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is None:
                additional = schema.get("additionalProperties", True)
                if additional is False:
                    errors.append(f"{path}: unexpected field {key}")
                elif isinstance(additional, dict):
                    errors.extend(_schema_errors(child, additional, current_document, documents, f"{path}.{key}", depth + 1))
            else:
                errors.extend(_schema_errors(child, child_schema, current_document, documents, f"{path}.{key}", depth + 1))
            if errors:
                break
    return errors


def validate_against_schema(value: Any, schema_id: str) -> None:
    documents = _schema_documents()
    schema = documents.get(schema_id)
    if schema is None:
        raise EvidenceError("required evidence schema is unavailable")
    errors = _schema_errors(value, schema, schema, documents)
    if errors:
        raise EvidenceError(f"schema validation failed: {errors[0]}")


def _validate_manifest(manifest: Any) -> list[dict[str, Any]]:
    validate_against_schema(manifest, "https://ios-caffeinate.invalid/schemas/evidence-manifest-v1.schema.json")
    if not isinstance(manifest, dict) or set(manifest) != {"manifest_version", "files"}:
        raise EvidenceError("manifest fields do not match version 1")
    if type(manifest.get("manifest_version")) is not int or manifest.get("manifest_version") != 1:
        raise EvidenceError("unsupported evidence manifest version")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise EvidenceError("manifest must list between 1 and 129 files")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"file_id", "path", "size_bytes", "sha256"}:
            raise EvidenceError("manifest file entry has unsupported fields")
        file_id = entry["file_id"]
        if not isinstance(file_id, str) or not ID_RE.fullmatch(file_id) or file_id in seen_ids:
            raise EvidenceError("manifest has a missing or duplicate file identifier")
        path = safe_relative_path(entry["path"])
        if path in seen_paths:
            raise EvidenceError("manifest lists a path more than once")
        size = entry["size_bytes"]
        if type(size) is not int or size < 0 or size > MAX_EVIDENCE_FILE_BYTES:
            raise EvidenceError("manifest contains an invalid or oversized file size")
        digest = entry["sha256"]
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise EvidenceError("manifest contains an invalid SHA-256")
        seen_ids.add(file_id)
        seen_paths.add(path)
        normalized.append({"file_id": file_id, "path": path, "size_bytes": size, "sha256": digest})
    if [entry["path"] for entry in normalized] != sorted(entry["path"] for entry in normalized):
        raise EvidenceError("manifest entries are not in deterministic path order")
    if "session.json" not in seen_paths:
        raise EvidenceError("manifest does not cover session.json")
    session_entry = next(entry for entry in normalized if entry["path"] == "session.json")
    if session_entry["file_id"] != "session":
        raise EvidenceError("session.json must use the reserved file identifier 'session'")
    if "manifest.json" in seen_paths:
        raise EvidenceError("manifest must not include itself")
    return normalized


def _validate_connectivity(data: Any) -> None:
    if not isinstance(data, dict) or set(data) != {"version", "lan", "tailscale"} or data.get("version") != 1:
        raise EvidenceError("connectivity_evidence does not match the P006 version 1 contract")
    for name, required in (
        ("lan", {"local_address", "tcp_22_reachable", "ssh_authenticated", "latency_ms", "timestamp", "screen_lock_status"}),
        ("tailscale", {"tailnet_address", "peer_connected", "path", "ssh_authenticated", "latency_ms", "timestamp", "screen_lock_status"}),
    ):
        record = data.get(name)
        if not isinstance(record, dict) or set(record) != required:
            raise EvidenceError(f"P006 {name} evidence fields do not match the existing schema")
        for key in ("tcp_22_reachable", "peer_connected", "ssh_authenticated"):
            if key in record and record[key] is not None and type(record[key]) is not bool:
                raise EvidenceError(f"P006 {name} {key} must be boolean or null")
        address_key = "local_address" if name == "lan" else "tailnet_address"
        address = record[address_key]
        if address is not None and (not isinstance(address, str) or not 1 <= len(address) <= 128):
            raise EvidenceError(f"P006 {name} address is invalid")
        latency = record["latency_ms"]
        if latency is not None and (isinstance(latency, bool) or not isinstance(latency, (int, float)) or latency < 0):
            raise EvidenceError(f"P006 {name} latency is invalid")
        if record["screen_lock_status"] not in {"LOCKED", "UNLOCKED", "UNKNOWN"}:
            raise EvidenceError(f"P006 {name} screen state is invalid")
        if record["timestamp"] is not None:
            iso_time(record["timestamp"], f"P006 {name} timestamp")
        if name == "tailscale" and record["path"] not in {"DIRECT", "RELAY", "UNKNOWN"}:
            raise EvidenceError("P006 Tailscale path is invalid")


def _validate_session(session: Any, entries: list[dict[str, Any]]) -> None:
    allowed = {
        "schema_version", "session_id", "source_commit_sha", "build_run", "device", "evidence_origin",
        "physical_presence_confirmed", "started_at", "ended_at", "clock", "trial", "observations",
        "connectivity_evidence", "cleanup", "unresolved_conditions", "evidence_files", "review_status",
    }
    required = allowed - {"connectivity_evidence"}
    if not isinstance(session, dict) or not required.issubset(session) or set(session) - allowed:
        raise EvidenceError("session fields do not match device-acceptance-v1")
    if type(session["schema_version"]) is not int or session["schema_version"] != 1:
        raise EvidenceError("unsupported device acceptance schema version")
    if not isinstance(session["session_id"], str) or not ID_RE.fullmatch(session["session_id"]):
        raise EvidenceError("session_id is invalid")
    if not isinstance(session["source_commit_sha"], str) or not COMMIT_RE.fullmatch(session["source_commit_sha"]):
        raise EvidenceError("source_commit_sha must be a full lowercase Git SHA")
    if session["evidence_origin"] not in SOURCES:
        raise EvidenceError("evidence_origin is unsupported")
    if type(session["physical_presence_confirmed"]) is not bool:
        raise EvidenceError("physical_presence_confirmed must be a boolean")
    start = iso_time(session["started_at"], "started_at")
    end = iso_time(session["ended_at"], "ended_at")

    build = session["build_run"]
    build_fields = {"build_id", "package_identifier", "package_version", "package_sha256", "binary_sha256"}
    if not isinstance(build, dict) or set(build) != build_fields:
        raise EvidenceError("build_run fields do not match device-acceptance-v1")
    for key in ("build_id", "package_identifier", "package_version"):
        if not isinstance(build[key], str) or not build[key] or len(build[key]) > 256:
            raise EvidenceError(f"build_run {key} is invalid")
    if not isinstance(build["package_sha256"], str) or not SHA256_RE.fullmatch(build["package_sha256"]):
        raise EvidenceError("build_run package_sha256 is invalid")
    binaries = build["binary_sha256"]
    if not isinstance(binaries, dict) or not 1 <= len(binaries) <= 32:
        raise EvidenceError("build_run binary_sha256 must identify at least one binary")
    if any(not isinstance(name, str) or not ID_RE.fullmatch(name) or not isinstance(value, str) or not SHA256_RE.fullmatch(value) for name, value in binaries.items()):
        raise EvidenceError("build_run binary_sha256 contains an invalid name or digest")

    device = session["device"]
    if not isinstance(device, dict) or set(device) != {"model", "ios_version", "jailbreak_bootstrap"}:
        raise EvidenceError("device fields do not match device-acceptance-v1")
    if any(value is not None and (not isinstance(value, str) or len(value) > limit) for value, limit in ((device["model"], 128), (device["ios_version"], 64), (device["jailbreak_bootstrap"], 256))):
        raise EvidenceError("device metadata is invalid")

    clock = session["clock"]
    if not isinstance(clock, dict) or set(clock) != {"source", "uncertainty_ms"}:
        raise EvidenceError("clock fields do not match device-acceptance-v1")
    if not isinstance(clock["source"], str) or not clock["source"] or len(clock["source"]) > 256:
        raise EvidenceError("clock source is invalid")
    if type(clock["uncertainty_ms"]) is not int or not 0 <= clock["uncertainty_ms"] <= 86_400_000:
        raise EvidenceError("clock uncertainty is invalid")
    if end < start and (start - end).total_seconds() * 1000 > 2 * clock["uncertainty_ms"]:
        raise EvidenceError("session end precedes session start beyond stated clock uncertainty")

    trial = session["trial"]
    if not isinstance(trial, dict) or set(trial) != {"trial_id", "authorized_duration_seconds", "attended"}:
        raise EvidenceError("trial fields do not match device-acceptance-v1")
    if not isinstance(trial["trial_id"], str) or not ID_RE.fullmatch(trial["trial_id"]):
        raise EvidenceError("trial_id is invalid")
    if type(trial["authorized_duration_seconds"]) is not int or not 1 <= trial["authorized_duration_seconds"] <= 300:
        raise EvidenceError("authorized trial duration must be between 1 and 300 seconds")
    if type(trial["attended"]) is not bool:
        raise EvidenceError("trial attended must be a boolean")

    cleanup = session["cleanup"]
    if not isinstance(cleanup, dict) or set(cleanup) != {"outcome"} or cleanup["outcome"] not in {"COMPLETE", "INCOMPLETE", "UNRESOLVED", "UNKNOWN", "NOT_APPLICABLE"}:
        raise EvidenceError("cleanup fields or outcome are invalid")
    unresolved = session["unresolved_conditions"]
    if not isinstance(unresolved, list) or len(unresolved) > 1000 or any(not isinstance(item, str) or len(item) > 500 for item in unresolved):
        raise EvidenceError("unresolved_conditions is invalid")
    if session["review_status"] not in {"PENDING", "REVIEW_REQUIRED", "REVIEWED", "REJECTED"}:
        raise EvidenceError("review_status is invalid")

    observations = session["observations"]
    if not isinstance(observations, list) or len(observations) > MAX_EVENTS:
        raise EvidenceError("observations must be a bounded array")
    event_ids: set[str] = set()
    sequences: set[int] = set()
    for event in observations:
        fields = {"event_id", "sequence", "event_type", "timestamp", "source", "timebase_id", "uncertainty_ms", "details"}
        if not isinstance(event, dict) or set(event) != fields:
            raise EvidenceError("observation fields do not match device-acceptance-v1")
        if not isinstance(event["event_id"], str) or not ID_RE.fullmatch(event["event_id"]) or event["event_id"] in event_ids:
            raise EvidenceError("observation has a missing or duplicate event_id")
        event_ids.add(event["event_id"])
        if type(event["sequence"]) is not int or event["sequence"] < 0 or event["sequence"] in sequences:
            raise EvidenceError("observation has a missing or duplicate sequence")
        sequences.add(event["sequence"])
        if event["event_type"] not in EVENT_TYPES:
            raise EvidenceError("observation has an unsupported event type")
        iso_time(event["timestamp"], f"observation {event['event_id']} timestamp")
        if event["source"] not in SOURCES:
            raise EvidenceError("observation has an unsupported source class")
        if not isinstance(event["timebase_id"], str) or not ID_RE.fullmatch(event["timebase_id"]):
            raise EvidenceError("observation timebase_id is invalid")
        if type(event["uncertainty_ms"]) is not int or not 0 <= event["uncertainty_ms"] <= 86_400_000:
            raise EvidenceError("observation clock uncertainty is invalid")
        if not isinstance(event["details"], dict) or len(event["details"]) > 64:
            raise EvidenceError("observation details must be a bounded object")
        boolean_details = {
            "success", "verified", "accepted", "launchd_disabled", "observed", "tcp_22_reachable",
            "ssh_authenticated", "peer_connected", "operator_confirmed_screen_state",
        }
        string_details = {"model", "ios_version", "package_sha256", "address", "path", "screen_lock_status", "screen_lock_event_id", "trial_id", "state", "outcome"}
        for key in boolean_details & set(event["details"]):
            if type(event["details"][key]) is not bool:
                raise EvidenceError(f"observation {event['event_id']} has an invalid {key} field")
        for key in string_details & set(event["details"]):
            value = event["details"][key]
            if value is not None and not isinstance(value, str):
                raise EvidenceError(f"observation {event['event_id']} has an invalid {key} field")
        if "latency_ms" in event["details"]:
            latency = event["details"]["latency_ms"]
            if latency is not None and (isinstance(latency, bool) or not isinstance(latency, (int, float)) or latency < 0):
                raise EvidenceError(f"observation {event['event_id']} has an invalid latency_ms field")
        if "exit_code" in event["details"] and type(event["details"]["exit_code"]) is not int:
            raise EvidenceError(f"observation {event['event_id']} has an invalid exit_code field")
        if event["event_type"] == "TAILSCALE_OBSERVATION" and "path" in event["details"] and event["details"]["path"] not in {"DIRECT", "RELAY", "UNKNOWN"}:
            raise EvidenceError("Tailscale observation path is invalid")
        if "screen_lock_status" in event["details"] and event["details"]["screen_lock_status"] not in {"LOCKED", "UNLOCKED", "UNKNOWN"}:
            raise EvidenceError("observation screen_lock_status is invalid")

    refs = session["evidence_files"]
    if not isinstance(refs, list) or len(refs) > MAX_FILES - 1:
        raise EvidenceError("evidence_files must be a bounded array")
    ref_ids: set[str] = set()
    ref_paths: set[str] = set()
    normalized_refs = []
    for ref in refs:
        fields = {"file_id", "path", "size_bytes", "sha256", "media_type"}
        media_types = {"application/json", "text/plain", "text/csv", "image/jpeg", "image/png", "application/octet-stream"}
        if not isinstance(ref, dict) or set(ref) != fields:
            raise EvidenceError("evidence file reference fields are invalid")
        file_id = ref["file_id"]
        path = safe_relative_path(ref["path"])
        if not isinstance(file_id, str) or not ID_RE.fullmatch(file_id) or file_id == "session" or file_id in ref_ids:
            raise EvidenceError("evidence file reference has a duplicate or reserved identifier")
        size = ref["size_bytes"]
        if type(size) is not int or size < 0 or size > MAX_EVIDENCE_FILE_BYTES:
            raise EvidenceError("evidence file reference size is invalid")
        if not isinstance(ref["sha256"], str) or not SHA256_RE.fullmatch(ref["sha256"]):
            raise EvidenceError("evidence file reference SHA-256 is invalid")
        if ref["media_type"] not in media_types:
            raise EvidenceError("evidence file media type is unsupported")
        if path == "session.json" or path == "manifest.json":
            raise EvidenceError("evidence file references a reserved package path")
        ref_ids.add(file_id)
        ref_paths.add(path)
        normalized_refs.append({key: ref[key] for key in fields})
    manifest_attachments = [item for item in entries if item["path"] != "session.json"]
    if len(manifest_attachments) != len(normalized_refs):
        raise EvidenceError("manifest and session evidence file lists differ")
    by_path = {item["path"]: item for item in manifest_attachments}
    if ref_paths != set(by_path):
        raise EvidenceError("manifest and session evidence file paths differ")
    for ref in normalized_refs:
        entry = by_path[ref["path"]]
        if any(ref[key] != entry[key] for key in ("file_id", "path", "size_bytes", "sha256")):
            raise EvidenceError("manifest and session evidence file integrity records differ")
    if "connectivity_evidence" in session:
        _validate_connectivity(session["connectivity_evidence"])

    scan_secrets(session)


def load_package(input_path: str | os.PathLike[str]) -> dict[str, Any]:
    provided = Path(input_path)
    try:
        if provided.is_symlink():
            raise EvidenceError("evidence directory must not be a symlink")
        root = provided.resolve(strict=True)
    except OSError:
        raise EvidenceError("evidence directory does not exist or cannot be resolved") from None
    if not root.is_dir():
        raise EvidenceError("evidence input must be a directory")
    files_on_disk, directories_on_disk = _enumerate_tree(root)
    if "manifest.json" not in files_on_disk:
        raise EvidenceError("evidence package is missing manifest.json")
    manifest_raw = _read_regular_file(root, "manifest.json", MAX_MANIFEST_BYTES)
    manifest = parse_json(manifest_raw, "manifest.json")
    entries = _validate_manifest(manifest)
    expected = {entry["path"] for entry in entries} | {"manifest.json"}
    if files_on_disk != expected:
        raise EvidenceError("evidence package has missing or unexpected files")
    expected_dirs = {
        parent.as_posix()
        for entry in entries
        for parent in PurePosixPath(entry["path"]).parents
        if parent.as_posix() != "."
    }
    if directories_on_disk != expected_dirs:
        raise EvidenceError("evidence package has unexpected or missing directories")

    contents: dict[str, bytes] = {}
    actual_total = 0
    for entry in entries:
        path = entry["path"]
        limit = MAX_SESSION_BYTES if path == "session.json" else MAX_EVIDENCE_FILE_BYTES
        raw = _read_regular_file(root, path, limit)
        actual_total += len(raw)
        if actual_total > MAX_TOTAL_BYTES:
            raise EvidenceError("evidence package exceeds its total size limit")
        if len(raw) != entry["size_bytes"] or _digest(raw) != entry["sha256"]:
            raise EvidenceError(f"SHA-256 or size mismatch for {path}")
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            decoded = ""
        if SECRET_VALUE_RE.search(decoded) or SECRET_ASSIGNMENT_RE.search(decoded):
            raise EvidenceError("evidence file contains material that resembles a credential or private key")
        contents[path] = raw

    session_raw = contents.get("session.json")
    if session_raw is None:
        raise EvidenceError("evidence package is missing session.json")
    session = parse_json(session_raw, "session.json")
    validate_against_schema(session, "https://ios-caffeinate.invalid/schemas/device-acceptance-v1.schema.json")
    _validate_session(session, entries)
    return {
        "root": root,
        "manifest": manifest,
        "manifest_sha256": _digest(manifest_raw),
        "session": session,
        "session_sha256": _digest(session_raw),
        "verified_files": [entry["path"] for entry in entries],
    }


def _atomic_write(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".p009-stage-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def create_manifest(input_path: str | os.PathLike[str], replace_existing: bool = False) -> dict[str, Any]:
    provided = Path(input_path)
    try:
        if provided.is_symlink():
            raise EvidenceError("evidence directory must not be a symlink")
        root = provided.resolve(strict=True)
    except OSError:
        raise EvidenceError("evidence directory does not exist or cannot be resolved") from None
    if not root.is_dir():
        raise EvidenceError("evidence input must be a directory")
    manifest_path = root / "manifest.json"
    if manifest_path.exists() and not replace_existing:
        raise EvidenceError("manifest.json already exists; use --replace only after reviewing package contents")
    files, directories = _enumerate_tree(root)
    if "manifest.json" in files:
        files.remove("manifest.json")
    if "session.json" not in files:
        raise EvidenceError("evidence package is missing session.json")
    attachment_paths = sorted(path for path in files if path != "session.json")
    if len(attachment_paths) > MAX_FILES - 1 or any(not path.startswith("evidence/") for path in attachment_paths):
        raise EvidenceError("attachments must be stored under evidence/ and remain within file-count limits")
    expected_dirs = {
        parent.as_posix()
        for value in files
        for parent in PurePosixPath(value).parents
        if parent.as_posix() != "."
    }
    if directories != expected_dirs:
        raise EvidenceError("evidence package has unexpected or empty directories")
    raw_session = _read_regular_file(root, "session.json", MAX_SESSION_BYTES)
    session = parse_json(raw_session, "session.json")
    validate_against_schema(session, "https://ios-caffeinate.invalid/schemas/device-acceptance-v1.schema.json")
    refs = []
    entries = []
    total = len(raw_session)
    media_types = {".json": "application/json", ".txt": "text/plain", ".csv": "text/csv", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    for relative in attachment_paths:
        raw = _read_regular_file(root, relative, MAX_EVIDENCE_FILE_BYTES)
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise EvidenceError("evidence package exceeds its total size limit")
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            decoded = ""
        if SECRET_VALUE_RE.search(decoded) or SECRET_ASSIGNMENT_RE.search(decoded):
            raise EvidenceError("evidence file contains material that resembles a credential or private key")
        file_id = "evidence-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
        suffix = PurePosixPath(relative).suffix.lower()
        refs.append({
            "file_id": file_id, "path": relative, "size_bytes": len(raw),
            "sha256": _digest(raw), "media_type": media_types.get(suffix, "application/octet-stream"),
        })
        entries.append({"file_id": file_id, "path": relative, "size_bytes": len(raw), "sha256": _digest(raw)})
    session["evidence_files"] = refs
    scan_secrets(session)
    validate_against_schema(session, "https://ios-caffeinate.invalid/schemas/device-acceptance-v1.schema.json")
    session_raw = (json.dumps(session, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    entries.append({"file_id": "session", "path": "session.json", "size_bytes": len(session_raw), "sha256": _digest(session_raw)})
    manifest = {"manifest_version": 1, "files": sorted(entries, key=lambda item: item["path"])}
    validate_against_schema(manifest, "https://ios-caffeinate.invalid/schemas/evidence-manifest-v1.schema.json")
    manifest_raw = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write(root / "session.json", session_raw)
    _atomic_write(manifest_path, manifest_raw)
    return {"manifest": "manifest.json", "files": [item["path"] for item in manifest["files"]], "manifest_sha256": _digest(manifest_raw)}


def _event_time(event: dict[str, Any]) -> dt.datetime:
    return iso_time(event["timestamp"], "event timestamp")


def _interval(event: dict[str, Any]) -> tuple[dt.datetime, dt.datetime]:
    instant = _event_time(event)
    uncertainty = dt.timedelta(milliseconds=event["uncertainty_ms"])
    return instant - uncertainty, instant + uncertainty


def _definitely_before(first: dict[str, Any], second: dict[str, Any]) -> bool | None:
    if first["timebase_id"] != second["timebase_id"]:
        return None
    return _interval(first)[1] < _interval(second)[0]


def _nominal_before(first: dict[str, Any], second: dict[str, Any]) -> bool | None:
    if first["timebase_id"] != second["timebase_id"]:
        return None
    return _event_time(first) < _event_time(second)


def all_events(session: dict[str, Any]) -> list[dict[str, Any]]:
    events = [dict(event) for event in session["observations"]]
    session_uncertainty = session["clock"]["uncertainty_ms"]
    for event in events:
        event["uncertainty_ms"] = max(event["uncertainty_ms"], session_uncertainty)
    legacy = session.get("connectivity_evidence")
    if legacy:
        for path_name, event_type, fields in (
            ("lan", "LAN_OBSERVATION", {"local_address": "address", "tcp_22_reachable": "tcp_22_reachable", "ssh_authenticated": "ssh_authenticated", "latency_ms": "latency_ms", "screen_lock_status": "screen_lock_status"}),
            ("tailscale", "TAILSCALE_OBSERVATION", {"tailnet_address": "address", "peer_connected": "peer_connected", "path": "path", "ssh_authenticated": "ssh_authenticated", "latency_ms": "latency_ms", "screen_lock_status": "screen_lock_status"}),
        ):
            record = legacy[path_name]
            if record["timestamp"] is None:
                continue
            details = {target: record[source] for source, target in fields.items()}
            details["trial_id"] = session["trial"]["trial_id"]
            details["operator_confirmed_screen_state"] = record["screen_lock_status"] == "LOCKED"
            events.append({
                "event_id": f"legacy-{path_name}", "sequence": len(events), "event_type": event_type,
                "timestamp": record["timestamp"], "source": "OPERATOR_RECORDED",
                "timebase_id": "legacy-connectivity", "uncertainty_ms": session["clock"]["uncertainty_ms"],
                "details": details,
            })
    return sorted(events, key=lambda event: (event["sequence"], event["event_id"]))


def replay(session: dict[str, Any]) -> dict[str, Any]:
    events = all_events(session)
    findings: list[dict[str, Any]] = []

    def finding(code: str, severity: str, message: str, event_ids: list[str] | None = None) -> None:
        item: dict[str, Any] = {"code": code, "severity": severity, "message": message}
        if event_ids:
            item["event_ids"] = sorted(set(event_ids))
        if item not in findings:
            findings.append(item)

    timebases = sorted({event["timebase_id"] for event in events})
    if len(timebases) > 1:
        finding("CROSS_TIMEBASE_ORDER_UNCERTAIN", "INFO", "Events from different clocks are not ordered unless their evidence provides an explicit trial association.")

    if iso_time(session["ended_at"], "ended_at") < iso_time(session["started_at"], "started_at"):
        finding("SESSION_BOUNDARY_ORDER_UNCERTAIN", "WARNING", "Session start and end timestamps overlap the declared clock uncertainty.")
    for timebase in timebases:
        by_sequence = sorted((event for event in events if event["timebase_id"] == timebase), key=lambda event: (event["sequence"], event["event_id"]))
        for previous, current in zip(by_sequence, by_sequence[1:]):
            if _definitely_before(current, previous):
                finding("TIMESTAMP_SEQUENCE_CONTRADICTION", "ERROR", "Recorded sequence moves backward beyond the stated clock uncertainty.", [previous["event_id"], current["event_id"]])
            elif _nominal_before(current, previous):
                finding("TIMESTAMP_ORDER_UNCERTAIN", "WARNING", "Recorded timestamps overlap their uncertainty intervals; order is not definitive.", [previous["event_id"], current["event_id"]])

    acquires = [event for event in events if event["event_type"] == "ASSERTION_ACQUIRE_SUCCESS" and event["details"].get("success", True) is True]
    for preflight in (event for event in events if event["event_type"] == "DEVICE_PREFLIGHT"):
        observed_model = preflight["details"].get("model")
        observed_ios = preflight["details"].get("ios_version")
        if (observed_model and observed_model != session["device"]["model"]) or (observed_ios and observed_ios != session["device"]["ios_version"]):
            finding("DEVICE_METADATA_CONTRADICTION", "ERROR", "Preflight identity differs from the session device metadata.", [preflight["event_id"]])

    acquire_attempts = [event for event in events if event["event_type"] == "ASSERTION_ACQUIRE_ATTEMPT"]
    acquire_failures = [event for event in events if event["event_type"] == "ASSERTION_ACQUIRE_FAILURE"]
    if len(acquire_attempts) > 1:
        finding("MULTIPLE_ACQUISITION_ATTEMPTS", "ERROR", "One acceptance trial contains multiple assertion-acquisition attempts.", [event["event_id"] for event in acquire_attempts])
    if acquire_failures and acquires:
        finding("ACQUISITION_FAILURE_WITH_SUCCESS", "ERROR", "The trial records both a failed and successful assertion acquisition.", [event["event_id"] for event in acquire_failures + acquires])

    termination_events = [event for event in events if event["event_type"] in {"EXPLICIT_STOP", "NATURAL_EXPIRY", "SIGTERM"}]
    if len({event["event_type"] for event in termination_events}) > 1:
        finding("MULTIPLE_TERMINATION_MODES", "ERROR", "A single trial records more than one distinct termination mode.", [event["event_id"] for event in termination_events])

    integrity = [event for event in events if event["event_type"] == "PACKAGE_INTEGRITY_CHECK" and event["details"].get("verified") is True]
    signatures = [event for event in events if event["event_type"] == "SIGNATURE_ACCEPTANCE" and event["details"].get("accepted") is True]
    installs = [event for event in events if event["event_type"] == "PACKAGE_INSTALL" and event["details"].get("success") is True]
    for install in installs:
        if any(_definitely_before(install, accepted) is True for accepted in signatures):
            finding("INSTALL_BEFORE_SIGNATURE_ACCEPTANCE", "ERROR", "Package installation is recorded before signature acceptance.", [install["event_id"], *[event["event_id"] for event in signatures]])
        if any(_definitely_before(install, verified) is True for verified in integrity):
            finding("INSTALL_BEFORE_INTEGRITY_CHECK", "ERROR", "Package installation is recorded before package integrity verification.", [install["event_id"], *[event["event_id"] for event in integrity]])

    releases = [event for event in events if event["event_type"] == "ASSERTION_RELEASE"]
    successful_releases = [event for event in releases if event["details"].get("success") is True]
    failed_releases = [event for event in releases if event["details"].get("success") is False]
    unresolved_release_failures = [
        failed for failed in failed_releases
        if not any(_definitely_before(failed, successful) is True for successful in successful_releases)
    ]
    if unresolved_release_failures:
        finding("RELEASE_FAILURE", "ERROR", "An assertion release failure has no later correlated successful release.", [event["event_id"] for event in unresolved_release_failures])
    elif failed_releases:
        finding("RELEASE_RETRY_RECOVERED", "WARNING", "A later correlated release succeeded after an earlier release failure.", [event["event_id"] for event in failed_releases + successful_releases])
    if acquires:
        for acquire in acquires:
            related = [release for release in releases if _definitely_before(acquire, release) is True]
            if not related:
                same_base = [release for release in releases if release["timebase_id"] == acquire["timebase_id"]]
                if same_base:
                    finding("ASSERTION_RELEASE_ORDER_INVALID", "ERROR", "No assertion release is recorded after acquisition.", [acquire["event_id"], *[item["event_id"] for item in same_base]])
                else:
                    finding("ASSERTION_RELEASE_UNCORRELATED", "WARNING", "A release record exists, but its clock cannot establish that it followed acquisition.", [acquire["event_id"], *[item["event_id"] for item in releases]])
        if not releases:
            finding("ASSERTION_RELEASE_MISSING", "ERROR", "An assertion was acquired without an observed release.", [event["event_id"] for event in acquires])
    elif releases:
        finding("RELEASE_WITHOUT_ACQUISITION", "WARNING", "A release record has no acquisition in this evidence session.", [event["event_id"] for event in releases])

    stops = [event for event in events if event["event_type"] == "EXPLICIT_STOP"]
    for stop in stops:
        for acquire in acquires:
            if _definitely_before(stop, acquire) is True:
                finding("STOP_BEFORE_ACQUIRE", "ERROR", "Explicit STOP is recorded before assertion acquisition.", [stop["event_id"], acquire["event_id"]])

    for acquire in acquires:
        end_events = [event for event in successful_releases if _definitely_before(acquire, event) is True]
        if end_events:
            end_event = min(end_events, key=lambda event: _event_time(event))
            duration = (_event_time(end_event) - _event_time(acquire)).total_seconds()
            uncertainty = (acquire["uncertainty_ms"] + end_event["uncertainty_ms"]) / 1000
            ceiling = session["trial"]["authorized_duration_seconds"]
            if duration - uncertainty > ceiling:
                finding("TRIAL_DURATION_EXCEEDED", "ERROR", "Observed hold duration exceeds the authorized trial ceiling after clock uncertainty.", [acquire["event_id"], end_event["event_id"]])
            elif duration + uncertainty > ceiling:
                finding("TRIAL_DURATION_UNCERTAIN", "WARNING", "Clock uncertainty overlaps the authorized trial ceiling.", [acquire["event_id"], end_event["event_id"]])
        else:
            start = _event_time(acquire)
            session_end = iso_time(session["ended_at"], "ended_at")
            combined_uncertainty = acquire["uncertainty_ms"] + session["clock"]["uncertainty_ms"]
            if (session_end - start).total_seconds() - (combined_uncertainty / 1000) > session["trial"]["authorized_duration_seconds"]:
                finding("TRIAL_DURATION_EXCEEDED_WITHOUT_CLEANUP", "ERROR", "The open trial extends beyond its authorized duration and has no correlated release.", [acquire["event_id"]])

    for launch in (event for event in events if event["event_type"] == "DAEMON_LAUNCH"):
        if launch["details"].get("success") is False:
            finding("DAEMON_UNAVAILABLE", "ERROR", "Daemon launch was recorded as unsuccessful.", [launch["event_id"]])
        for acquire in acquires:
            if _definitely_before(acquire, launch) is True:
                prior_releases = [event for event in successful_releases if _definitely_before(acquire, event) is True and _definitely_before(event, launch) is True]
                if not prior_releases:
                    finding("RESTART_DURING_TRIAL", "ERROR", "Daemon launch occurred during a trial without a correlated successful release.", [acquire["event_id"], launch["event_id"]])

    for network in (event for event in events if event["event_type"] in {"LAN_OBSERVATION", "TAILSCALE_OBSERVATION"}):
        details = network["details"]
        reachable_key = "tcp_22_reachable" if network["event_type"] == "LAN_OBSERVATION" else "peer_connected"
        reachable = details.get(reachable_key)
        if reachable is True and details.get("ssh_authenticated") is not True:
            finding("NETWORK_WITHOUT_AUTHENTICATED_SSH", "WARNING", "Reachability alone is not authenticated SSH evidence.", [network["event_id"]])
        locks = [event for event in events if event["event_type"] == "SCREEN_LOCK" and _definitely_before(event, network) is True]
        unlocks = [event for event in events if event["event_type"] == "SCREEN_UNLOCK" and _definitely_before(event, network) is True]
        if unlocks and (not locks or max(unlocks, key=lambda event: _event_time(event))["sequence"] > max(locks, key=lambda event: _event_time(event))["sequence"]):
            finding("CONNECTIVITY_AFTER_UNLOCK", "WARNING", "Connectivity was observed after the last recorded screen unlock.", [network["event_id"], *[item["event_id"] for item in unlocks]])
    for event_type, reachable_key, label in (("LAN_OBSERVATION", "tcp_22_reachable", "LAN"), ("TAILSCALE_OBSERVATION", "peer_connected", "Tailscale")):
        rows = [event for event in events if event["event_type"] == event_type]
        successes = [event for event in rows if event["details"].get(reachable_key) is True and event["details"].get("ssh_authenticated") is True]
        failures = [event for event in rows if event["details"].get(reachable_key) is False or event["details"].get("ssh_authenticated") is False]
        if successes and failures:
            finding(f"CONTRADICTORY_{label.upper()}_OBSERVATIONS", "ERROR", f"{label} observations disagree within one acceptance session.", [event["event_id"] for event in successes + failures])
    if any(event["event_type"] == "TAILSCALE_OBSERVATION" for event in events) and not any(event["event_type"] == "LAN_OBSERVATION" for event in events):
        finding("LAN_NOT_PROVED_BY_TAILSCALE", "WARNING", "Tailscale observations do not establish LAN reachability.")

    if session["trial"]["attended"] is False and session["evidence_origin"] in PHYSICAL_SOURCES:
        finding("UNATTENDED_PHYSICAL_TRIAL", "ERROR", "Physical acceptance trials must be attended.")
    if not any(event["event_type"] == "PHYSICAL_RECOVERY" and event["details"].get("success") is True for event in events):
        finding("RECOVERY_NOT_CONFIRMED", "WARNING", "Physical recovery confirmation is missing.")
    if any(event["event_type"] in {"ROLLBACK", "PACKAGE_REMOVAL"} and event["details"].get("success") is False for event in events):
        finding("ROLLBACK_INCOMPLETE", "ERROR", "Package removal or rollback is recorded as unsuccessful.")

    timeline = [
        {
            "sequence": event["sequence"], "event_id": event["event_id"], "event_type": event["event_type"],
            "timestamp": event["timestamp"], "timebase_id": event["timebase_id"],
            "uncertainty_ms": event["uncertainty_ms"], "source": event["source"],
        }
        for event in sorted(events, key=lambda item: (item["timebase_id"], _event_time(item), item["sequence"], item["event_id"]))
    ]
    findings.sort(key=lambda item: (item["severity"], item["code"], item.get("event_ids", [])))
    return {"timeline": timeline, "findings": findings, "timebases": timebases}


def _successful_event(events: list[dict[str, Any]], event_type: str, key: str = "success") -> list[dict[str, Any]]:
    return [event for event in events if event["event_type"] == event_type and event["details"].get(key) is True]


def _within_trial(event: dict[str, Any], session: dict[str, Any], events: list[dict[str, Any]], acquire: dict[str, Any] | None, release: dict[str, Any] | None) -> bool:
    if event["details"].get("trial_id") == session["trial"]["trial_id"]:
        return True
    if acquire is not None and release is not None and _definitely_before(acquire, event) is True and _definitely_before(event, release) is True:
        return True
    return False


def gate_candidates(session: dict[str, Any], analysis: dict[str, Any]) -> dict[str, tuple[str, list[str]]]:
    events = all_events(session)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_type.setdefault(event["event_type"], []).append(event)
    acquires = _successful_event(events, "ASSERTION_ACQUIRE_SUCCESS")
    releases = _successful_event(events, "ASSERTION_RELEASE")
    all_release_failures = [event for event in events if event["event_type"] == "ASSERTION_RELEASE" and event["details"].get("success") is False]
    release_failures = [
        failed for failed in all_release_failures
        if not any(_definitely_before(failed, successful) is True for successful in releases)
    ]
    definite_release_pairs = [
        (acquire, release) for acquire in acquires for release in releases
        if _definitely_before(acquire, release) is True
    ]
    physical = session["evidence_origin"] in PHYSICAL_SOURCES and session["physical_presence_confirmed"] is True
    map_events = lambda values: sorted(event["event_id"] for event in values)
    result: dict[str, tuple[str, list[str]]] = {}

    def put(name: str, ok: bool, used: list[dict[str, Any]] = (), failed: bool = False, missing: str = "Required observations are missing or cannot be correlated.") -> None:
        if not physical:
            result[name] = ("BLOCKED", map_events(used))
        elif any(event["source"] not in PHYSICAL_SOURCES for event in used):
            result[name] = ("BLOCKED", map_events(used))
        elif failed:
            result[name] = ("FAIL", map_events(used))
        elif not ok:
            result[name] = ("INSUFFICIENT_EVIDENCE", map_events(used))
        else:
            result[name] = ("REVIEW_REQUIRED", map_events(used))

    preflight = by_type.get("DEVICE_PREFLIGHT", [])
    physical_preflight = [event for event in preflight if event["source"] in PHYSICAL_SOURCES]
    identity_events = [
        event for event in physical_preflight
        if event["details"].get("model") == session["device"]["model"]
        and event["details"].get("ios_version") == session["device"]["ios_version"]
    ]
    identity_mismatch = any(
        (event["details"].get("model") and event["details"].get("model") != session["device"]["model"])
        or (event["details"].get("ios_version") and event["details"].get("ios_version") != session["device"]["ios_version"])
        for event in physical_preflight
    )
    put("device_identity_verified", bool(identity_events and session["device"]["model"] and session["device"]["ios_version"]), identity_events or physical_preflight, identity_mismatch)
    runtime = [event for event in physical_preflight if event["details"].get("ios_version") and session["device"]["ios_version"] == event["details"].get("ios_version")]
    put("ios_runtime_verified", bool(runtime), runtime)

    integrity_events = [event for event in by_type.get("PACKAGE_INTEGRITY_CHECK", []) if event["details"].get("verified") is True and event["details"].get("package_sha256") == session["build_run"]["package_sha256"]]
    integrity_failed = any(event["details"].get("verified") is False or (event["details"].get("package_sha256") and event["details"].get("package_sha256") != session["build_run"]["package_sha256"]) for event in by_type.get("PACKAGE_INTEGRITY_CHECK", []))
    put("package_integrity_verified", bool(integrity_events), integrity_events, integrity_failed)
    signature_events = [event for event in by_type.get("SIGNATURE_ACCEPTANCE", []) if event["details"].get("accepted") is True]
    signature_failed = any(event["details"].get("accepted") is False for event in by_type.get("SIGNATURE_ACCEPTANCE", []))
    put("signature_acceptance_verified", bool(signature_events), signature_events, signature_failed)
    install_events = [
        event for event in by_type.get("PACKAGE_INSTALL", [])
        if event["details"].get("success") is True
        and event["details"].get("package_sha256") == session["build_run"]["package_sha256"]
        and any(_definitely_before(check, event) is True for check in integrity_events)
        and any(_definitely_before(signature, event) is True for signature in signature_events)
    ]
    install_failed = any(
        event["details"].get("success") is False
        or (event["details"].get("package_sha256") and event["details"].get("package_sha256") != session["build_run"]["package_sha256"])
        or any(_definitely_before(event, check) is True for check in integrity_events + signature_events)
        for event in by_type.get("PACKAGE_INSTALL", [])
    )
    put("installation_verified", bool(install_events), install_events, install_failed)
    successful_rollbacks = [event for event in by_type.get("ROLLBACK", []) if event["details"].get("success") is True]
    successful_removals = [event for event in by_type.get("PACKAGE_REMOVAL", []) if event["details"].get("success") is True]
    rollback_events = successful_rollbacks + successful_removals
    rollback_failed = any(event["details"].get("success") is False for event in by_type.get("ROLLBACK", []) + by_type.get("PACKAGE_REMOVAL", []))
    put("rollback_verified", bool(successful_rollbacks and successful_removals), rollback_events, rollback_failed)

    acquire_failed = any(event["details"].get("success") is False for event in by_type.get("ASSERTION_ACQUIRE_FAILURE", []))
    put("iokit_acquire_verified", bool(acquires), acquires, acquire_failed and not acquires)
    put("iokit_release_verified", bool(definite_release_pairs) and not release_failures, [event for pair in definite_release_pairs for event in pair] + release_failures, bool(release_failures) or bool(releases and not definite_release_pairs))
    over_duration = any(item["code"] == "TRIAL_DURATION_EXCEEDED" for item in analysis["findings"])
    duration_uncertain = any(item["code"] == "TRIAL_DURATION_UNCERTAIN" for item in analysis["findings"])
    bounded_events = [event for pair in definite_release_pairs for event in pair]
    put("bounded_hold_verified", bool(definite_release_pairs) and not over_duration and not duration_uncertain and session["trial"]["attended"], bounded_events, over_duration or (bool(acquires) and (bool(release_failures) or not session["trial"]["attended"])))

    explicit_stop = by_type.get("EXPLICIT_STOP", [])
    stop_pairs = [(stop, release) for stop in explicit_stop for release in releases if _definitely_before(stop, release) is True]
    put("explicit_stop_verified", bool(stop_pairs), [event for pair in stop_pairs for event in pair] or explicit_stop, bool(release_failures) or bool(explicit_stop and not stop_pairs and any(_definitely_before(stop, acquire) is True for stop in explicit_stop for acquire in acquires)))
    expiry = by_type.get("NATURAL_EXPIRY", [])
    expiry_pairs = [(item, release) for item in expiry for release in releases if _definitely_before(item, release) is True]
    put("natural_expiry_verified", bool(expiry_pairs), [event for pair in expiry_pairs for event in pair] or expiry, bool(release_failures) or bool(expiry and not expiry_pairs and releases))
    sigterms = by_type.get("SIGTERM", [])
    exits = by_type.get("DAEMON_EXIT", [])
    sigterm_pairs = [
        (acquire, signal, release, exit_event)
        for acquire in acquires for signal in sigterms for release in releases for exit_event in exits
        if _definitely_before(acquire, signal) is True
        and _definitely_before(signal, release) is True
        and _definitely_before(release, exit_event) is True
    ]
    put("sigterm_cleanup_verified", bool(sigterm_pairs), [event for pair in sigterm_pairs for event in pair] or sigterms, bool(release_failures) or bool(sigterms and not sigterm_pairs and releases))

    acquire_for_network = min(acquires, key=lambda event: _event_time(event)) if acquires else None
    release_for_network = min(releases, key=lambda event: _event_time(event)) if releases else None

    def network_candidates(kind: str) -> tuple[list[dict[str, Any]], bool]:
        event_type = "LAN_OBSERVATION" if kind == "LAN" else "TAILSCALE_OBSERVATION"
        rows = by_type.get(event_type, [])
        candidates: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        events_by_id = {event["event_id"]: event for event in events}
        for event in rows:
            details = event["details"]
            reachable_key = "tcp_22_reachable" if kind == "LAN" else "peer_connected"
            field_complete = details.get(reachable_key) is True and details.get("ssh_authenticated") is True
            field_failure = details.get(reachable_key) is False or details.get("ssh_authenticated") is False
            screen_lock_id = details.get("screen_lock_event_id")
            screen_record = events_by_id.get(screen_lock_id) if isinstance(screen_lock_id, str) else None
            screen = (
                details.get("screen_lock_status") == "LOCKED"
                and details.get("operator_confirmed_screen_state") is True
                and screen_record is not None
                and screen_record["event_type"] == "SCREEN_LOCK"
                and screen_record["source"] == "OPERATOR_RECORDED"
                and screen_record["details"].get("screen_lock_status") == "LOCKED"
            )
            unlocked_after_lock = False
            if screen_record is not None and screen_record["timebase_id"] == event["timebase_id"]:
                unlocked_after_lock = any(
                    unlock["event_type"] == "SCREEN_UNLOCK"
                    and _definitely_before(screen_record, unlock) is True
                    and _definitely_before(unlock, event) is True
                    for unlock in events
                )
            screen_conflict = details.get("screen_lock_status") == "LOCKED" and screen_record is not None and (
                screen_record["source"] != "OPERATOR_RECORDED"
                or screen_record["details"].get("screen_lock_status") != "LOCKED"
                or unlocked_after_lock
            )
            screen = screen and not unlocked_after_lock
            interval = _within_trial(event, session, events, acquire_for_network, release_for_network)
            latency_ok = isinstance(details.get("latency_ms"), (int, float)) and not isinstance(details.get("latency_ms"), bool) and details.get("latency_ms") >= 0
            address_key = "address"
            try:
                ipaddress.ip_address(details.get(address_key, ""))
                has_address = True
            except (ValueError, TypeError):
                has_address = False
            path_ok = kind == "LAN" or (isinstance(details.get("path"), str) and details.get("path") in {"DIRECT", "RELAY", "UNKNOWN"})
            independent = event["source"] == "EXTERNAL_OBSERVER"
            if field_complete and screen and interval and latency_ok and has_address and path_ok and independent:
                candidates.extend([event, screen_record])
            elif field_failure or screen_conflict:
                failures.append(event)
        return candidates, bool(failures and not candidates)

    lan, lan_failed = network_candidates("LAN")
    tailscale, tailscale_failed = network_candidates("TAILSCALE")
    put("screen_locked_lan_verified", bool(lan), lan, lan_failed)
    put("screen_locked_tailscale_verified", bool(tailscale), tailscale, tailscale_failed)
    ssh_events = [event for event in events if event["event_type"] in {"LAN_OBSERVATION", "TAILSCALE_OBSERVATION"} and event["details"].get("ssh_authenticated") is True]
    ssh_failed = any(event["event_type"] in {"LAN_OBSERVATION", "TAILSCALE_OBSERVATION"} and event["details"].get("ssh_authenticated") is False for event in events)
    put("authenticated_ssh_verified", bool(ssh_events), ssh_events, ssh_failed and not ssh_events)
    observer_events = [event for event in events if event["event_type"] in {"LAN_OBSERVATION", "TAILSCALE_OBSERVATION"} and event["source"] == "EXTERNAL_OBSERVER"]
    put("independent_observer_verified", bool(observer_events), observer_events)

    for name, event_type in (("battery_observation_available", "BATTERY_OBSERVATION"), ("thermal_observation_available", "THERMAL_OBSERVATION")):
        rows = [event for event in by_type.get(event_type, []) if event["details"].get("observed", True) is True]
        put(name, bool(rows), rows)
    recovery = _successful_event(events, "PHYSICAL_RECOVERY")
    put("physical_recovery_confirmed", bool(recovery), recovery)
    launchd = [event for event in physical_preflight if event["details"].get("launchd_disabled") is True]
    launchd_failed = any(event["details"].get("launchd_disabled") is False for event in physical_preflight)
    put("launchd_remains_disabled", bool(launchd), launchd, launchd_failed)

    unresolved_assertion = bool(
        release_failures or session["cleanup"]["outcome"] != "COMPLETE" or session["unresolved_conditions"]
        or (acquires and not definite_release_pairs)
    )
    clean_release = bool(definite_release_pairs and not release_failures and session["cleanup"]["outcome"] == "COMPLETE" and not session["unresolved_conditions"])
    put("no_unresolved_assertion", clean_release, [event for pair in definite_release_pairs for event in pair], unresolved_assertion)
    scheduled_wake = _successful_event(events, "SCHEDULED_WAKE_OBSERVATION")
    scheduled_wake_failed = any(event["details"].get("success") is False for event in by_type.get("SCHEDULED_WAKE_OBSERVATION", []))
    put("scheduled_wake_verified", bool(scheduled_wake), scheduled_wake, scheduled_wake_failed)

    expected = {item["id"] for item in json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["gates"]}
    if set(result) != expected:
        raise EvidenceError("gate evaluator and machine-readable registry do not match")
    return result


def readiness_report(package: dict[str, Any], analysis: dict[str, Any], review_decisions: dict[str, str] | None = None, reviewer: str | None = None) -> dict[str, Any]:
    session = package["session"]
    candidates = gate_candidates(session, analysis)
    decisions = review_decisions or {}
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    registry_by_id = {item["id"]: item for item in registry["gates"]}
    gates: list[dict[str, Any]] = []
    has_error_finding = any(item["severity"] == "ERROR" for item in analysis["findings"])
    for gate_id in registry_by_id:
        state, evidence_ids = candidates[gate_id]
        if state == "REVIEW_REQUIRED" and has_error_finding:
            state = "FAIL"
        elif state == "REVIEW_REQUIRED" and decisions.get(gate_id) == "PASS":
            state = "PASS"
        elif state == "REVIEW_REQUIRED" and decisions.get(gate_id) == "FAIL":
            state = "FAIL"
        category = registry_by_id[gate_id]["category"]
        reason = {
            "PASS": "Evidence was individually approved during this explicit human review.",
            "FAIL": "Evidence contradicts the gate or was rejected during human review.",
            "BLOCKED": "Evidence source or physical-presence provenance cannot establish a hardware result.",
            "REVIEW_REQUIRED": "Evidence is structurally supported and requires explicit human review.",
            "INSUFFICIENT_EVIDENCE": "Required observations are missing or their causal/time relationship is not established.",
            "PENDING": "No evaluation has been performed.",
        }[state]
        gates.append({"id": gate_id, "category": category, "status": state, "evidence_event_ids": evidence_ids, "reason": reason})
    states = {item["status"] for item in gates}
    hardware = "PASS" if states == {"PASS"} else ("FAIL" if "FAIL" in states else "PENDING")
    lan_state = next(item["status"] for item in gates if item["id"] == "screen_locked_lan_verified")
    ts_state = next(item["status"] for item in gates if item["id"] == "screen_locked_tailscale_verified")
    scheduled_state = next(item["status"] for item in gates if item["id"] == "scheduled_wake_verified")
    lan_event = next((event for event in all_events(session) if event["event_type"] == "LAN_OBSERVATION"), None)
    ts_event = next((event for event in all_events(session) if event["event_type"] == "TAILSCALE_OBSERVATION"), None)

    def network_summary(event: dict[str, Any] | None, state: str, kind: str) -> dict[str, Any]:
        if event is None:
            return {"gate_status": state, "observed": False, "authenticated_ssh": None, "screen_locked": None, "latency_ms": None, "path": None}
        details = event["details"]
        return {
            "gate_status": state,
            "observed": True,
            "authenticated_ssh": details.get("ssh_authenticated"),
            "screen_locked": details.get("screen_lock_status") == "LOCKED" and details.get("operator_confirmed_screen_state") is True,
            "latency_ms": details.get("latency_ms"),
            "path": details.get("path") if kind == "tailscale" else None,
        }

    report = {
        "report_version": 1,
        "session_id": session["session_id"],
        "structural_validation": "PASS",
        "identity": {
            "evidence_session": session["session_id"],
            "device_model": session["device"]["model"],
            "ios_version": session["device"]["ios_version"],
            "jailbreak_bootstrap": session["device"]["jailbreak_bootstrap"],
            "source_commit_sha": session["source_commit_sha"],
            "build_id": session["build_run"]["build_id"],
            "package_identifier": session["build_run"]["package_identifier"],
            "package_version": session["build_run"]["package_version"],
            "package_sha256": session["build_run"]["package_sha256"],
            "binary_sha256": dict(sorted(session["build_run"]["binary_sha256"].items())),
            "evidence_origin": session["evidence_origin"],
            "physical_presence_confirmed": session["physical_presence_confirmed"],
            "review_status_claimed_by_session": session["review_status"],
            "session_started_at": session["started_at"],
            "session_ended_at": session["ended_at"],
            "clock_source": session["clock"]["source"],
            "clock_uncertainty_ms": session["clock"]["uncertainty_ms"],
            "trial_id": session["trial"]["trial_id"],
            "authorized_duration_seconds": session["trial"]["authorized_duration_seconds"],
            "trial_attended": session["trial"]["attended"],
            "evidence_files": [
                {"file_id": item["file_id"], "path": item["path"], "size_bytes": item["size_bytes"], "sha256": item["sha256"]}
                for item in session["evidence_files"]
            ],
            "manifest_sha256": package["manifest_sha256"],
        },
        "power": {
            "acquisition": next(item["status"] for item in gates if item["id"] == "iokit_acquire_verified"),
            "release": next(item["status"] for item in gates if item["id"] == "iokit_release_verified"),
            "explicit_stop": next(item["status"] for item in gates if item["id"] == "explicit_stop_verified"),
            "natural_expiry": next(item["status"] for item in gates if item["id"] == "natural_expiry_verified"),
            "sigterm_cleanup": next(item["status"] for item in gates if item["id"] == "sigterm_cleanup_verified"),
            "cleanup_outcome": session["cleanup"]["outcome"],
            "unresolved_conditions_count": len(session["unresolved_conditions"]),
            "unresolved_assertion_status": next(item["status"] for item in gates if item["id"] == "no_unresolved_assertion"),
        },
        "networking": {
            "lan": network_summary(lan_event, lan_state, "lan"),
            "tailscale": network_summary(ts_event, ts_state, "tailscale"),
            "paths_are_independent": True,
            "screen_lock_correlation": "REVIEW_REQUIRED" if lan_event or ts_event else "INSUFFICIENT_EVIDENCE",
            "authenticated_ssh_gate": next(item["status"] for item in gates if item["id"] == "authenticated_ssh_verified"),
        },
        "safety": {
            "battery_observation": next(item["status"] for item in gates if item["id"] == "battery_observation_available"),
            "thermal_observation": next(item["status"] for item in gates if item["id"] == "thermal_observation_available"),
            "physical_recovery": next(item["status"] for item in gates if item["id"] == "physical_recovery_confirmed"),
            "launchd_disabled": next(item["status"] for item in gates if item["id"] == "launchd_remains_disabled"),
            "rollback_readiness": next(item["status"] for item in gates if item["id"] == "rollback_verified"),
        },
        "decision": {
            "hardware_acceptance": hardware,
            "scheduled_wake": "PASS" if scheduled_state == "PASS" else "UNVERIFIED",
            "unattended_24_7": "NOT_VALIDATED",
            "unattended_operation_authorized": False,
            "missing_evidence": [item["id"] for item in gates if item["status"] == "INSUFFICIENT_EVIDENCE"],
            "blocked_gates": [item["id"] for item in gates if item["status"] == "BLOCKED"],
            "contradictions": analysis["findings"],
            "review_requirements": [item["id"] for item in gates if item["status"] == "REVIEW_REQUIRED"],
            "evidence_integrity": "HASHES_MATCH; provenance and truth are not authenticated",
        },
        "gates": gates,
        "timeline": analysis["timeline"],
    }
    if reviewer:
        report["human_review"] = {
            "reviewed_by": reviewer,
            "accepted_gate_ids": sorted(gate_id for gate_id, decision in decisions.items() if decision == "PASS"),
            "rejected_gate_ids": sorted(gate_id for gate_id, decision in decisions.items() if decision == "FAIL"),
            "cryptographic_authenticity": "NOT_ESTABLISHED",
        }
    return report


def markdown_report(report: dict[str, Any]) -> str:
    identity = report["identity"]
    power = report["power"]
    net = report["networking"]
    safety = report["safety"]
    decision = report["decision"]

    def md_text(value: Any) -> str:
        text = " ".join(str(value or "not observed").split())
        return text.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`").replace("<", "&lt;").replace(">", "&gt;")

    lines = [
        f"# Device Acceptance Report — {report['session_id']}", "",
        f"- Structural validation: **{report['structural_validation']}**",
        f"- Hardware acceptance: **{decision['hardware_acceptance']}**",
        f"- Unattended 24/7: **{decision['unattended_24_7']}**",
        f"- Scheduled wake: **{decision['scheduled_wake']}**", "",
        "## Identity", "",
        f"- Device: {md_text(identity['device_model'])}; iOS {md_text(identity['ios_version'])}",
        f"- Session origin: `{identity['evidence_origin']}`; physical presence confirmed: `{str(identity['physical_presence_confirmed']).lower()}`",
        f"- Source commit: `{identity['source_commit_sha']}`",
        f"- Build: {md_text(identity['build_id'])}; package {md_text(identity['package_identifier'])}@{md_text(identity['package_version'])}",
        f"- Package SHA-256: `{identity['package_sha256']}`", "",
        f"- Trial `{md_text(identity['trial_id'])}`: authorized {identity['authorized_duration_seconds']} s; attended `{str(identity['trial_attended']).lower()}`",
        f"- Session window: `{identity['session_started_at']}` to `{identity['session_ended_at']}`; clock `{md_text(identity['clock_source'])}` ±{identity['clock_uncertainty_ms']} ms",
        f"- Evidence files: {len(identity['evidence_files'])}; manifest SHA-256: `{identity['manifest_sha256']}`", "",
        "## Power", "",
        f"- Assertion acquisition: **{power['acquisition']}**; release: **{power['release']}**",
        f"- STOP: **{power['explicit_stop']}**; natural expiry: **{power['natural_expiry']}**; SIGTERM cleanup: **{power['sigterm_cleanup']}**",
        f"- Cleanup: `{power['cleanup_outcome']}`; unresolved conditions: {power['unresolved_conditions_count']}", "",
        "## Networking", "",
        f"- LAN: **{net['lan']['gate_status']}**; authenticated SSH: `{net['lan']['authenticated_ssh']}`; locked-screen confirmation: `{net['lan']['screen_locked']}`",
        f"- Tailscale: **{net['tailscale']['gate_status']}**; authenticated SSH: `{net['tailscale']['authenticated_ssh']}`; path: `{net['tailscale']['path']}`",
        "- LAN and Tailscale are evaluated independently. Local daemon state is not network reachability.", "",
        "## Safety", "",
        f"- Battery: **{safety['battery_observation']}**; thermal: **{safety['thermal_observation']}**",
        f"- Physical recovery: **{safety['physical_recovery']}**; launchd disabled: **{safety['launchd_disabled']}**; rollback: **{safety['rollback_readiness']}**", "",
        "## Decision", "",
        f"- Hardware acceptance: **{decision['hardware_acceptance']}**",
        f"- Unattended operation authorized: **{str(decision['unattended_operation_authorized']).lower()}**",
        f"- Evidence integrity: {decision['evidence_integrity']}",
        f"- Missing evidence: {', '.join(decision['missing_evidence']) or 'none'}",
        f"- Review required: {', '.join(decision['review_requirements']) or 'none'}",
        "- Hashes detect mismatches; they do not prove that observations came from a genuine iPad.",
        "- No report authorizes unattended operation or a 24/7 test.", "",
        "## Gate status", "",
        "| Gate | Status | Reason |", "|---|---|---|",
    ]
    lines.extend(f"| `{gate['id']}` | **{gate['status']}** | {gate['reason']} |" for gate in report["gates"])
    if "human_review" in report:
        lines.extend(["", f"Human reviewer: `{report['human_review']['reviewed_by']}`. This review record is not cryptographically authenticated."])
    return "\n".join(lines) + "\n"


def _emit(value: Any, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
    elif output_format == "markdown":
        print(markdown_report(value), end="")
    else:
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _print_error(error: Exception) -> None:
    print(f"ERROR: {error}", file=sys.stderr)


def command_validate(args: argparse.Namespace) -> int:
    try:
        package = load_package(args.evidence_directory)
        output = {
            "structural_validation": "PASS",
            "schema_version": package["session"]["schema_version"],
            "session_id": package["session"]["session_id"],
            "verified_files": package["verified_files"],
            "manifest_sha256": package["manifest_sha256"],
            "session_sha256": package["session_sha256"],
            "hardware_acceptance": "PENDING; structural validation does not establish hardware acceptance",
        }
        _emit(output, "json" if args.json else "human")
        return 0
    except (EvidenceError, OSError, ValueError, TypeError, KeyError, IndexError) as error:
        _print_error(error)
        return 2


def command_replay(args: argparse.Namespace) -> int:
    try:
        package = load_package(args.evidence_directory)
        result = replay(package["session"])
        _emit(result, "json" if args.json else "json")
        return 3 if any(item["severity"] == "ERROR" for item in result["findings"]) else 0
    except (EvidenceError, OSError, ValueError, TypeError, KeyError, IndexError) as error:
        _print_error(error)
        return 2


def command_report(args: argparse.Namespace) -> int:
    try:
        package = load_package(args.evidence_directory)
        analysis = replay(package["session"])
        report = readiness_report(package, analysis)
        _emit(report, args.format)
        return 0
    except (EvidenceError, OSError, ValueError, TypeError, KeyError, IndexError) as error:
        _print_error(error)
        return 2


def command_manifest(args: argparse.Namespace) -> int:
    try:
        result = create_manifest(args.evidence_directory, args.replace)
        _emit(result, "json")
        return 0
    except (EvidenceError, OSError, ValueError, TypeError, KeyError, IndexError) as error:
        _print_error(error)
        return 2


def command_review(args: argparse.Namespace) -> int:
    try:
        if not sys.stdin.isatty():
            raise EvidenceError("interactive review requires a terminal")
        package = load_package(args.evidence_directory)
        session = package["session"]
        analysis = replay(session)
        initial = readiness_report(package, analysis)
        candidates = [gate for gate in initial["gates"] if gate["status"] == "REVIEW_REQUIRED"]
        if not candidates:
            _emit(initial, args.format)
            print("No gate has complete physical evidence eligible for review.", file=sys.stderr)
            return 0
        reviewer = input("Reviewer identifier (letters, digits, dot, underscore, hyphen): ").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", reviewer):
            raise EvidenceError("reviewer identifier is invalid")
        print("Review the evidence outside this tool. Type PASS for each gate you approve, or SKIP to leave it pending.")
        print("This interactive review does not create a cryptographic signature or establish provenance.")
        decisions: dict[str, str] = {}
        for gate in candidates:
            answer = input(f"{gate['id']} [{', '.join(gate['evidence_event_ids']) or 'no event id'}] (PASS/SKIP): ").strip().upper()
            if answer == "PASS":
                decisions[gate["id"]] = "PASS"
            elif answer != "SKIP":
                raise EvidenceError("review response must be PASS or SKIP")
        _emit(readiness_report(package, analysis, decisions, reviewer), args.format)
        return 0
    except (EvidenceError, OSError, ValueError, TypeError, KeyError, IndexError) as error:
        _print_error(error)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and replay iOS-Caffeinate acceptance evidence offline.")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="verify schemas, manifest hashes, paths, sizes, and evidence fields")
    validate.add_argument("evidence_directory", help="explicit evidence package directory")
    validate.add_argument("--json", action="store_true", help="write machine-readable JSON")
    validate.set_defaults(function=command_validate)
    replay_cmd = sub.add_parser("replay", help="reconstruct event order and report contradictions or uncertainty")
    replay_cmd.add_argument("evidence_directory", help="explicit evidence package directory")
    replay_cmd.add_argument("--json", action="store_true", help="write machine-readable JSON")
    replay_cmd.set_defaults(function=command_replay)
    report = sub.add_parser("report", help="produce a deterministic readiness report without human approval")
    report.add_argument("evidence_directory", help="explicit evidence package directory")
    report.add_argument("--format", choices=("markdown", "json"), default="markdown")
    report.set_defaults(function=command_report)
    review = sub.add_parser("review", help="interactively review gates supported by physical evidence")
    review.add_argument("evidence_directory", help="explicit evidence package directory")
    review.add_argument("--format", choices=("markdown", "json"), default="markdown")
    review.set_defaults(function=command_review)
    manifest = sub.add_parser("manifest", help="prepare deterministic hashes in an explicitly staged evidence package")
    manifest.add_argument("evidence_directory", help="explicit evidence package directory")
    manifest.add_argument("--replace", action="store_true", help="rebuild an existing manifest after reviewing staged package contents")
    manifest.set_defaults(function=command_manifest)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.function(args)


if __name__ == "__main__":
    raise SystemExit(main())
