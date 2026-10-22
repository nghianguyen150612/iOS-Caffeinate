#!/usr/bin/env python3
"""Offline, read-only P020 release readiness evaluator. It never authorizes publication."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/v0.2/P020-RELEASE-MANIFEST.schema.json"
PROVENANCE_SCHEMA_PATH = ROOT / "docs/v0.2/P020-BUILD-PROVENANCE.schema.json"
sys.path.insert(0, str(ROOT / "scripts"))
import p012_common  # noqa: E402

try:
    from p011_release_preflight import EXPECTED_PROFILE_SHA256, EXPECTED_SIGNER_SHA256, EXPECTED_SIGNER_VERSION
except ImportError:  # pragma: no cover - source-tree packaging errors are surfaced during validation
    EXPECTED_PROFILE_SHA256 = "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca"
    EXPECTED_SIGNER_SHA256 = "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c"
    EXPECTED_SIGNER_VERSION = "2.1.5-procursus7"
EXPECTED_SIGNER_SOURCE = "https://github.com/ProcursusTeam/ldid.git"
EXPECTED_SIGNER_COMMIT = "aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef"

EXPECTED_CHAIN = [
    ("P011", 10, "ios/p011-signed-package-acceptance", "1fed3d15f44099d4f862ac1ff422da287b78b0b3", "main", "0cfdc645dc1d67ddc4320a00bb114763b9669b66", "16f3ea06e2c100bc1caa208f5d539bb9620222c0"),
    ("P012", 11, "ios/p012-controlled-idle-power-research", "f459e332deefb134b6725c1455c5721830d0bb3a", "main", "16f3ea06e2c100bc1caa208f5d539bb9620222c0", "50f96891b8369583c7b86576bd198854283edc0c"),
    ("P013", 12, "ios/p013-launchd-lifecycle", "3d7b5d4c700194ab71713c51577e7a7cf0acd48c", "main", "50f96891b8369583c7b86576bd198854283edc0c", "077b62bcf167a7b54ddf6f56c8bd3895c4f2da19"),
    ("P014", 13, "ios/p014-crash-recovery", "5dbf08176f3219c082e5b8f48bac43461b3fdd96", "main", "077b62bcf167a7b54ddf6f56c8bd3895c4f2da19", "4abecae5ce4baf69de159b648fb07a9e0ff8a446"),
    ("P015", 14, "ios/p015-server-mode-v2", "ef46cdc467128bf658c81dc891915aa91a2ddbca", "main", "4abecae5ce4baf69de159b648fb07a9e0ff8a446", "938c7c87f84090ecebbe2e2bbb9e8116f263e5be"),
    ("P016", 15, "ios/p016-health-telemetry", "1b0e258b136f6325c4720bf55c569449935418c3", "main", "938c7c87f84090ecebbe2e2bbb9e8116f263e5be", "12228ac832f77243e4d87c5a0178208cf3f3eef6"),
    ("P017", 16, "ios/p017-scheduling-v2", "15861c0f9b765731c7dee506fd147ca7e53cbf7e", "main", "12228ac832f77243e4d87c5a0178208cf3f3eef6", "84277473bbbad2c2d2df977f559840f13db6c25b"),
    ("P018", 17, "ios/p018-cli-package-ux", "e9d94c9abdfb63ccabd96e11ea2f667c33918e90", "main", "84277473bbbad2c2d2df977f559840f13db6c25b", "9083f9265ddcb0cc9f6c75edce0e0c473d74897b"),
    ("P019", 18, "ios/p019-supervised-reliability", "7d5723fca2595b8928ed3e1717ca872906d48538", "main", "9083f9265ddcb0cc9f6c75edce0e0c473d74897b", "7dbd47e4500c0ddf3d65d282d8e6a8881d6c8703"),
]
HARDWARE_REQUIREMENTS: dict[str, set[str]] = {
    "p010_signer_provenance": {"P010_SIGNER_PROVENANCE"},
    "p011_stable_package_acceptance": {"P011_DEVICE_ACCEPTANCE"},
    "installed_candidate_identity": {"V02_CANDIDATE_IDENTITY"},
    "p012_physical_trials": {"P012_TRIAL_SET", "P012_ANALYSIS"},
    "p013_lifecycle_acceptance": {"P013_ACCEPTANCE"},
    "p014_physical_recovery": {"P014_ACCEPTANCE"},
    "p016_resource_review": {"P016_RESOURCE_REVIEW"},
    "p018_privacy_review": {"P018_PRIVACY_REVIEW"},
    "p019_supervised_cycles": {"P019_SESSION", "P019_ACCEPTANCE_RESULT"},
    "p009_independent_provenance_review": {"P009_RAW_EVIDENCE", "P009_INDEPENDENT_REVIEW"},
}
PHYSICAL_CLASSES = {"DEVICE_REPORTED", "EXTERNAL_OBSERVER", "OPERATOR_RECORDED", "INDEPENDENT_REVIEW"}
SYNTHETIC_CLASSES = {"SIMULATED", "MOCK", "CI"}
REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "reviewer_id", "reviewed_at_utc", "review_scope", "conclusion", "independent", "evidence_sha256", "findings"],
    "properties": {
        "schema_version": {"const": 1},
        "reviewer_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._@+-]{1,127}$"},
        "reviewed_at_utc": {"type": "string", "format": "date-time"},
        "review_scope": {"type": "string", "minLength": 8, "maxLength": 1000},
        "conclusion": {"enum": ["ACCEPTED", "REJECTED", "INCOMPLETE"]},
        "independent": {"const": True},
        "evidence_sha256": {"type": "array", "minItems": 1, "maxItems": 128, "uniqueItems": True, "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
        "findings": {"type": "array", "maxItems": 256, "items": {"type": "string", "maxLength": 1000}}
    }
}


class GateError(ValueError):
    pass


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _json_bytes(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(GateError(f"invalid JSON constant {value}")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"{label} is not strict UTF-8 JSON: {exc}") from None


def _read_regular(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise GateError(f"cannot safely open regular file {path.name}: {exc}") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > maximum:
            raise GateError(f"file type, hardlink count, or size is unsafe: {path.name}")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum or len(raw) != st.st_size:
            raise GateError(f"file changed during read or exceeded the read limit: {path.name}")
        return raw
    finally:
        os.close(fd)


class EvidenceStore:
    """Read-only evidence cache with aggregate limits for untrusted manifests."""

    def __init__(self, root: Path, max_files: int = 256, max_total_bytes: int = 128 * 1024 * 1024):
        self.root = root
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes
        self._cache: dict[str, bytes] = {}
        self._total_bytes = 0

    def read(self, relative: str, maximum: int = 16 * 1024 * 1024) -> bytes:
        if relative in self._cache:
            raw = self._cache[relative]
            if len(raw) > maximum:
                raise GateError(f"evidence exceeds the read limit: {relative}")
            return raw
        if len(self._cache) >= self.max_files:
            raise GateError(f"evidence bundle exceeds {self.max_files} distinct files")
        raw = _safe_relative_bytes(self.root, relative, maximum)
        if self._total_bytes + len(raw) > self.max_total_bytes:
            raise GateError(f"evidence bundle exceeds the {self.max_total_bytes}-byte aggregate limit")
        self._cache[relative] = raw
        self._total_bytes += len(raw)
        return raw


def _safe_relative_bytes(root: Path, relative: str, maximum: int = 16 * 1024 * 1024) -> bytes:
    pure = Path(relative)
    if pure.is_absolute() or not relative or any(part in ("", ".", "..") for part in pure.parts):
        raise GateError(f"evidence path must be relative and traversal-free: {relative!r}")
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    flags_file = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        directory_fd = os.open(root, flags_dir)
    except OSError as exc:
        raise GateError(f"cannot safely open evidence bundle root: {exc}") from None
    try:
        for part in pure.parts[:-1]:
            try:
                next_fd = os.open(part, flags_dir, dir_fd=directory_fd)
            except OSError as exc:
                raise GateError(f"cannot safely open evidence directory {part}: {exc}") from None
            os.close(directory_fd)
            directory_fd = next_fd
        try:
            fd = os.open(pure.parts[-1], flags_file, dir_fd=directory_fd)
        except OSError as exc:
            raise GateError(f"cannot safely open evidence file {pure.parts[-1]}: {exc}") from None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > maximum:
                raise GateError(f"evidence is not a single-link regular file within size limits: {relative}")
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > maximum or len(raw) != st.st_size:
                raise GateError(f"evidence changed during read or exceeded size limit: {relative}")
            return raw
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)


def _load_manifest(path: Path) -> tuple[dict[str, Any], Path]:
    if not path.is_absolute():
        raise GateError("--manifest must be an absolute path")
    raw = _read_regular(path, 4 * 1024 * 1024)
    value = _json_bytes(raw, "release manifest")
    if not isinstance(value, dict):
        raise GateError("release manifest root must be an object")
    schema = _json_bytes(_read_regular(SCHEMA_PATH, 1024 * 1024), "release manifest schema")
    issues = p012_common.validate_json_schema(value, schema)
    if issues:
        raise GateError("release manifest schema validation failed: " + "; ".join(issues))
    return value, path.parent.resolve(strict=True)


def _load_evidence(store: EvidenceStore, file_record: dict[str, Any]) -> tuple[dict[str, Any], str]:
    raw = store.read(file_record["path"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != file_record["sha256"]:
        raise GateError(f"SHA-256 mismatch for evidence {file_record['path']}")
    value = _json_bytes(raw, f"evidence {file_record['path']}")
    if not isinstance(value, dict):
        raise GateError("evidence JSON root must be an object")
    declared_class = value.get("evidence_class", value.get("evidence_origin", value.get("source_class")))
    if declared_class is not None and not isinstance(declared_class, str):
        raise GateError("evidence provenance class must be a string")
    if declared_class in SYNTHETIC_CLASSES:
        raise GateError(f"evidence declares synthetic provenance {declared_class}")
    return value, digest


def _reviewed(store: EvidenceStore, receipt: dict[str, Any], evidence_digest: str, trusted_keyring: Path | None) -> tuple[bool, str]:
    raw = store.read(receipt["path"], 1024 * 1024)
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != receipt["sha256"]:
        raise GateError(f"review receipt SHA-256 mismatch: {receipt['path']}")
    review = _json_bytes(raw, "independent review receipt")
    issues = p012_common.validate_json_schema(review, REVIEW_SCHEMA)
    if issues:
        raise GateError("review receipt schema invalid: " + "; ".join(issues))
    if evidence_digest not in review["evidence_sha256"]:
        raise GateError("review receipt does not bind the referenced evidence hash")
    if review["conclusion"] != "ACCEPTED":
        return False, f"independent review conclusion is {review['conclusion']}"
    if trusted_keyring is None:
        raise GateError("UNVERIFIED: no external trusted reviewer keyring was supplied")
    if not trusted_keyring.is_absolute():
        raise GateError("trusted reviewer keyring path must be absolute")
    keyring_raw = _read_regular(trusted_keyring, 16 * 1024 * 1024)
    keyring_path = trusted_keyring.resolve(strict=True)
    try:
        keyring_path.relative_to(store.root.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise GateError("trusted reviewer keyring must be outside the evidence bundle")
    signature = receipt["signature"]
    signature_raw = store.read(signature["path"], 1024 * 1024)
    if hashlib.sha256(signature_raw).hexdigest() != signature["sha256"]:
        raise GateError("review receipt signature SHA-256 mismatch")
    gpgv = shutil.which("gpgv")
    if not gpgv:
        raise GateError("UNVERIFIED: gpgv is unavailable for reviewer signature verification")
    with tempfile.TemporaryDirectory(prefix="p020-review-") as temp_name:
        temp = Path(temp_name)
        receipt_file = temp / "review.json"
        signature_file = temp / "review.json.sig"
        keyring_file = temp / "trusted-reviewers.gpg"
        receipt_file.write_bytes(raw)
        signature_file.write_bytes(signature_raw)
        keyring_file.write_bytes(keyring_raw)
        result = subprocess.run(
            [gpgv, "--homedir", str(temp), "--status-fd", "1", "--keyring", str(keyring_file), str(signature_file), str(receipt_file)],
            capture_output=True, text=True, timeout=10, check=False,
        )
    if result.returncode != 0:
        raise GateError("review receipt signature is not valid under the external trusted keyring")
    fingerprints = [match.group(1).upper() for match in re.finditer(r"\[GNUPG:\] VALIDSIG ([0-9A-Fa-f]+)", result.stdout)]
    if receipt["signer_fingerprint"].upper() not in fingerprints:
        raise GateError("review signer fingerprint does not match the signed receipt reference")
    return True, f"reviewed by {review['reviewer_id']} at {review['reviewed_at_utc']}"


def _sha256_text(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_signer_evidence(value: dict[str, Any], expected_source_sha: str) -> None:
    if value.get("artifact_type") != "P010_SIGNER_PROVENANCE" or value.get("source_commit_sha") != expected_source_sha:
        raise GateError("P010 signer provenance is not bound to the exact v0.2 source")
    signer = value.get("signer")
    profile = value.get("profile")
    if not isinstance(signer, dict) or not isinstance(profile, dict):
        raise GateError("P010 signer record or profile record is missing")
    if signer.get("version") != EXPECTED_SIGNER_VERSION or signer.get("sha256") != EXPECTED_SIGNER_SHA256:
        raise GateError("P010 signer does not match the pinned executable identity")
    if signer.get("origin") != EXPECTED_SIGNER_SOURCE or signer.get("source_commit_sha") != EXPECTED_SIGNER_COMMIT:
        raise GateError("P010 signer origin/commit does not match the pinned Procursus source")
    if profile.get("id") != "amethyst-ios12-rootful" or profile.get("sha256") != EXPECTED_PROFILE_SHA256:
        raise GateError("P010 entitlement profile does not match the approved profile")
    if value.get("tool_execution_verified") is not True or value.get("source_binary_hashes_verified") is not True:
        raise GateError("P010 signer execution or source-to-signed-binary verification is incomplete")
    source_hashes = value.get("source_binary_sha256")
    final_hashes = value.get("final_binary_sha256")
    if (not isinstance(source_hashes, dict) or not isinstance(final_hashes, dict)
            or set(source_hashes) != {"cli", "daemon"} or set(final_hashes) != {"cli", "daemon"}
            or not all(_sha256_text(item) for item in (*source_hashes.values(), *final_hashes.values()))):
        raise GateError("P010 source/final CLI and daemon hashes are incomplete")
    if not _sha256_text(value.get("package_sha256")):
        raise GateError("P010 signed package SHA-256 is missing")
    if value.get("signing_exit_code") != 0 or value.get("signed_binary_inspection") != "PASS":
        raise GateError("P010 signing command or signed-binary inspection did not pass")
    command = value.get("signing_command")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        raise GateError("P010 signing command provenance is missing")


def _validate_candidate_identity(value: dict[str, Any], expected_source_sha: str) -> None:
    required = {
        "artifact_type": "V02_CANDIDATE_IDENTITY", "source_commit_sha": expected_source_sha,
        "package_identifier": "com.ioscaffeinate.cli", "package_version": "0.2.0~rc1-1",
        "architecture": "iphoneos-arm", "profile_id": "amethyst-ios12-rootful",
        "profile_sha256": EXPECTED_PROFILE_SHA256, "ldid_version": EXPECTED_SIGNER_VERSION,
        "ldid_sha256": EXPECTED_SIGNER_SHA256, "signature_validation": "PASS", "installed_paths_verified": True,
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise GateError(f"v0.2 installed candidate identity has invalid {key}")
    for key in ("package_sha256", "cli_binary_sha256", "daemon_binary_sha256", "source_cli_binary_sha256", "source_daemon_binary_sha256", "rollback_artifact_sha256"):
        if not _sha256_text(value.get(key)):
            raise GateError(f"v0.2 installed candidate identity is missing {key}")
    if not isinstance(value.get("build_id"), str) or not value["build_id"].strip():
        raise GateError("v0.2 installed candidate identity is missing build_id")


def _candidate_evidence_issues(hardware_payloads: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
    signer = hardware_payloads.get("p010_signer_provenance", {}).get("P010_SIGNER_PROVENANCE")
    identity = hardware_payloads.get("installed_candidate_identity", {}).get("V02_CANDIDATE_IDENTITY")
    session = hardware_payloads.get("p019_supervised_cycles", {}).get("P019_SESSION")
    if not (signer and identity and session):
        return []
    issues = []
    final_hashes = signer["final_binary_sha256"]
    if signer["package_sha256"] != identity["package_sha256"]:
        issues.append("P010 signed package hash does not match the installed v0.2 candidate")
    if final_hashes["cli"] != identity["cli_binary_sha256"] or final_hashes["daemon"] != identity["daemon_binary_sha256"]:
        issues.append("P010 final signed binary hashes do not match installed candidate binaries")
    source_hashes = signer["source_binary_sha256"]
    if source_hashes["cli"] != identity["source_cli_binary_sha256"] or source_hashes["daemon"] != identity["source_daemon_binary_sha256"]:
        issues.append("P010 signed binary inputs do not match the recorded unsigned candidate binaries")
    candidate = session["candidate"]
    for key in ("source_commit_sha", "package_identifier", "package_version", "package_sha256", "profile_id", "profile_sha256", "ldid_version", "ldid_sha256", "build_id", "rollback_artifact_sha256"):
        identity_key = key
        if candidate.get(key) != identity.get(identity_key):
            issues.append(f"P019 session candidate {key} does not match the installed candidate identity")
    if candidate.get("cli_binary_sha256") != identity.get("cli_binary_sha256") or candidate.get("daemon_binary_sha256") != identity.get("daemon_binary_sha256"):
        issues.append("P019 session CLI/daemon hashes do not match the installed candidate identity")
    if candidate.get("installed_paths_verified") is not True or candidate.get("signature_validation") != "PASS":
        issues.append("P019 session does not confirm signed candidate and installed-path identity")
    return issues


def _validate_schema(value: Any, schema_path: Path, label: str) -> None:
    schema = _json_bytes(_read_regular(schema_path, 2 * 1024 * 1024), f"{label} schema")
    issues = p012_common.validate_json_schema(value, schema)
    if issues:
        raise GateError(f"{label} schema validation failed: " + "; ".join(issues))


def _validate_p019_result(value: dict[str, Any]) -> None:
    _validate_schema(value, ROOT / "experiments/p019/acceptance-result-v1.schema.json", "P019 acceptance result")
    if value.get("status") != "ACCEPTED_FOR_TESTED_SCOPE" or value.get("hardware_acceptance") != "ACCEPTED_FOR_TESTED_SCOPE":
        raise GateError("P019 acceptance result does not accept its tested scope")
    if value.get("p020_readiness") != "ASSESSABLE_FROM_CLOUD" or value.get("cloud_status") != "P019_CLOUD_COMPLETE_HARDWARE_ACCEPTANCE_PENDING":
        raise GateError("P019 result readiness fields do not match the accepted tested-scope state")
    metrics = value.get("metrics")
    if not isinstance(metrics, dict):
        raise GateError("P019 acceptance metrics are missing")
    required_counts = {
        "planned_trials": 24, "valid_trials": 24, "invalid_trials": 0,
        "incomplete_trials": 0, "interrupted_trials": 0,
        "successful_bounded_holds": 12, "confirmed_releases": 12,
        "release_failures": 0, "unexpected_daemon_exits": 0, "unexpected_restarts": 0,
    }
    for key, expected in required_counts.items():
        if metrics.get(key) != expected:
            raise GateError(f"P019 acceptance metric {key} is {metrics.get(key)!r}, expected {expected}")
    p009_review = value.get("p009_review")
    p018_review = value.get("p018_export_review")
    if not isinstance(p009_review, dict) or not isinstance(p018_review, dict) or p009_review.get("status") != "PASS" or p018_review.get("status") != "PASS":
        raise GateError("P019 P009 or P018 evidence review is not complete")


def _validate_p019_session(value: dict[str, Any], expected_source_sha: str) -> dict[str, Any]:
    _validate_schema(value, ROOT / "experiments/p019/session-v1.schema.json", "P019 session")
    from p019_session import analyze_session, load_protocol, validate_session

    protocol, p012_protocol, protocol_issues = load_protocol()
    if protocol_issues:
        raise GateError("checked-in P019/P012 protocol validation failed: " + "; ".join(protocol_issues))
    session_issues = validate_session(value, protocol, p012_protocol)
    if session_issues:
        raise GateError("P019 session protocol validation failed: " + "; ".join(session_issues))
    if value.get("session_state") != "ENDED" or value.get("source_commit_sha") != expected_source_sha:
        raise GateError("P019 session is not ended at the exact release source")
    if value.get("evidence_class") not in PHYSICAL_CLASSES - {"INDEPENDENT_REVIEW"}:
        raise GateError("P019 session does not declare physical evidence provenance")
    candidate = value.get("candidate", {})
    if candidate.get("artifact_role") != "DEVELOPMENT_CANDIDATE" or candidate.get("source_commit_sha") != expected_source_sha:
        raise GateError("P019 session candidate identity does not match the exact release source")
    trials = value.get("trial_records", [])
    if len(trials) != 24:
        raise GateError(f"P019 session has {len(trials)} trial records; expected 24")
    for trial in trials:
        _validate_schema(trial, ROOT / "experiments/p012/trial-record-v1.schema.json", "P012 trial record")
        if trial.get("evidence_origin") not in PHYSICAL_CLASSES - {"INDEPENDENT_REVIEW"}:
            raise GateError("P019 session contains a nonphysical P012 trial")
    cycles = value.get("bounded_cycles", [])
    if len(cycles) != 12:
        raise GateError(f"P019 session has {len(cycles)} bounded cycles; expected 12")
    period_counts: dict[int, int] = {}
    period_dates: dict[int, set[str]] = {}
    for cycle in cycles:
        period = cycle["observation_period"]
        period_counts[period] = period_counts.get(period, 0) + 1
        period_dates.setdefault(period, set()).add(cycle["started_at_utc"][:10])
        if cycle["source_class"] not in PHYSICAL_CLASSES - {"INDEPENDENT_REVIEW"}:
            raise GateError("P019 session contains a nonphysical bounded cycle")
        if (not cycle["attended"] or cycle["acquisition"] != "CONFIRMED" or cycle["release"] != "CONFIRMED"
                or cycle["cleanup_state"] != "SAFE" or cycle["daemon_exit"] != "EXPECTED"
                or cycle["unexpected_restart"] or cycle["assertion_duration_seconds"] != 180
                or cycle["duration_method"] == "UNKNOWN" or not cycle["duration_timebase_id"]
                or cycle["duration_uncertainty_ms"] is None):
            raise GateError(f"P019 bounded cycle {cycle['cycle_id']} does not meet supervised acquire/release acceptance")
        if cycle["duration_method"] == "DEVICE_MONOTONIC" and not cycle["device_timebase_id"]:
            raise GateError(f"P019 bounded cycle {cycle['cycle_id']} lacks device monotonic timebase identity")
    if period_counts != {1: 4, 2: 4, 3: 4} or any(len(period_dates.get(period, set())) != 1 for period in (1, 2, 3)):
        raise GateError("P019 cycles must form four-cycle periods on three distinct attended calendar dates")
    all_dates = {date for dates in period_dates.values() for date in dates}
    if len(all_dates) != 3:
        raise GateError("P019 observation periods are not on three separate calendar dates")
    review = value["review"]
    if (review["status"] != "REVIEWED" or review["decision"] != "ACCEPT" or review["independent"] is not True
            or not review["reviewer_id"] or not review["operator_id"] or review["reviewer_id"] == review["operator_id"]):
        raise GateError("P019 session lacks a distinct independent reviewer acceptance")
    return analyze_session(value, protocol, p012_protocol)["metrics"]


def _evaluate_hardware_gate(name: str, gate: dict[str, Any], store: EvidenceStore, trusted_keyring: Path | None, expected_source_sha: str) -> dict[str, Any]:
    required_types = HARDWARE_REQUIREMENTS[name]
    evidence = gate["evidence"]
    if not evidence:
        reason = "required physical evidence has not been submitted"
        if name == "p010_signer_provenance":
            reason = "SIGNER_PROVENANCE_BLOCKED: exact pinned ldid executable and origin review are unavailable"
        return {"status": "PENDING", "reason": reason, "evidence_count": 0}
    seen: set[str] = set()
    accepted_review_notes: list[str] = []
    payloads: dict[str, dict[str, Any]] = {}
    p019_recomputed_metrics: dict[str, Any] | None = None
    for item in evidence:
        kind = item["artifact_type"]
        if kind in seen:
            return {"status": "FAILED", "reason": f"duplicate evidence type {kind}", "evidence_count": len(evidence)}
        seen.add(kind)
        source_class = item["file"]["evidence_class"]
        if source_class in SYNTHETIC_CLASSES:
            return {"status": "BLOCKED", "reason": f"{source_class} evidence cannot satisfy a hardware gate", "evidence_count": len(evidence)}
        if source_class not in PHYSICAL_CLASSES:
            return {"status": "UNVERIFIED", "reason": f"unsupported evidence class {source_class}", "evidence_count": len(evidence)}
        try:
            value, digest = _load_evidence(store, item["file"])
        except GateError as exc:
            return {"status": "FAILED", "reason": str(exc), "evidence_count": len(evidence)}
        if kind not in {"P019_SESSION", "P019_ACCEPTANCE_RESULT"} and value.get("artifact_type") != kind:
            return {"status": "FAILED", "reason": f"evidence payload type disagrees with manifest for {kind}", "evidence_count": len(evidence)}
        if kind in {"P019_SESSION", "P019_ACCEPTANCE_RESULT"} and "artifact_type" in value:
            return {"status": "FAILED", "reason": f"{kind} payload must conform to its checked-in versioned schema without extra type fields", "evidence_count": len(evidence)}
        payload_class = value.get("evidence_class", value.get("evidence_origin", value.get("source_class")))
        if payload_class is not None and payload_class != source_class:
            return {"status": "FAILED", "reason": f"evidence payload provenance disagrees with manifest for {kind}", "evidence_count": len(evidence)}
        if kind == "P010_SIGNER_PROVENANCE":
            _validate_signer_evidence(value, expected_source_sha)
        if kind == "V02_CANDIDATE_IDENTITY":
            _validate_candidate_identity(value, expected_source_sha)
        if kind == "P019_ACCEPTANCE_RESULT":
            _validate_p019_result(value)
        if kind == "P019_SESSION":
            p019_recomputed_metrics = _validate_p019_session(value, expected_source_sha)
        payloads[kind] = value
        receipt = item.get("review_receipt")
        if receipt is None:
            return {"status": "UNVERIFIED", "reason": f"independent review receipt is missing for {kind}", "evidence_count": len(evidence)}
        try:
            ok, note = _reviewed(store, receipt, digest, trusted_keyring)
        except GateError as exc:
            if str(exc).startswith("UNVERIFIED:"):
                return {"status": "UNVERIFIED", "reason": str(exc), "evidence_count": len(evidence)}
            return {"status": "FAILED", "reason": str(exc), "evidence_count": len(evidence)}
        if not ok:
            return {"status": "BLOCKED", "reason": f"{kind}: {note}", "evidence_count": len(evidence)}
        accepted_review_notes.append(note)
    missing = sorted(required_types - seen)
    extra = sorted(seen - required_types)
    if missing or extra:
        return {"status": "PENDING", "reason": f"evidence set incomplete (missing={missing}, unexpected={extra})", "evidence_count": len(evidence)}
    if name == "p019_supervised_cycles":
        session = payloads["P019_SESSION"]
        result = payloads["P019_ACCEPTANCE_RESULT"]
        if result["session_id"] != session["session_id"] or result["source_commit_sha"] != expected_source_sha:
            return {"status": "FAILED", "reason": "P019 acceptance result does not bind the exact session and release source", "evidence_count": len(evidence)}
        metrics = result["metrics"]
        recomputed = p019_recomputed_metrics or {}
        for key in ("planned_trials", "attempted_trials", "valid_trials", "invalid_trials", "incomplete_trials", "interrupted_trials",
                    "successful_bounded_holds", "confirmed_releases", "p012_confirmed_releases", "p012_release_failures",
                    "release_failures", "unexpected_daemon_exits", "unexpected_restarts"):
            if metrics.get(key) != recomputed.get(key):
                return {"status": "FAILED", "reason": f"P019 acceptance metric {key} disagrees with the checked-in session analysis", "evidence_count": len(evidence)}
    # Human reviewers authenticate source reality and reviewer identity outside this offline tool.
    return {"status": "PASS", "reason": "required artifacts are hashed and review signatures verify under the external trusted keyring", "evidence_count": len(evidence), "reviews": accepted_review_notes, "_payloads": payloads}


def _verify_cloud_gate(name: str, gate: dict[str, Any], store: EvidenceStore, source_sha: str) -> dict[str, Any]:
    status = gate["status"]
    if status != "PASS":
        return {"status": status, "reason": f"cloud gate is {status}", "evidence_count": len(gate["evidence"])}
    if not gate["evidence"]:
        return {"status": "FAILED", "reason": "PASS has no CI evidence reference", "evidence_count": 0}
    for file_record in gate["evidence"]:
        try:
            value, _digest = _load_evidence(store, file_record)
        except GateError as exc:
            return {"status": "FAILED", "reason": str(exc), "evidence_count": len(gate["evidence"])}
        if file_record["evidence_class"] == "BUILD_PROVENANCE":
            if name != "build_provenance":
                return {"status": "FAILED", "reason": "build provenance may only satisfy the build_provenance cloud gate", "evidence_count": len(gate["evidence"])}
            try:
                build = _validate_build_provenance(value, store, source_sha)
            except GateError as exc:
                return {"status": "FAILED", "reason": str(exc), "evidence_count": len(gate["evidence"])}
            build_status = build["reproducibility"]["status"]
            continue
        if file_record["evidence_class"] != "CI":
            return {"status": "FAILED", "reason": "cloud gate evidence must be CI or exact build provenance", "evidence_count": len(gate["evidence"])}
        if value.get("source_sha") != source_sha or value.get("gate_results", {}).get(name) != "PASS":
            return {"status": "FAILED", "reason": "CI evidence source SHA or gate result does not match", "evidence_count": len(gate["evidence"])}
    result = {"status": "PASS", "reason": "exact-source cloud evidence hash and gate result verified", "evidence_count": len(gate["evidence"])}
    if name == "build_provenance":
        if "build" not in locals():
            return {"status": "FAILED", "reason": "build provenance record is missing", "evidence_count": len(gate["evidence"])}
        result["reproducibility"] = build_status
    return result


def _validate_build_provenance(value: dict[str, Any], store: EvidenceStore, expected_source_sha: str) -> dict[str, Any]:
    _validate_schema(value, PROVENANCE_SCHEMA_PATH, "P020 build provenance")
    if value["source"]["commit_sha"] != expected_source_sha or value["source"]["worktree_clean"] is not True:
        raise GateError("build provenance source SHA or clean worktree does not match")
    try:
        expected_tree = subprocess.run(["git", "-C", str(ROOT), "rev-parse", f"{expected_source_sha}^{{tree}}"],
                                       check=True, capture_output=True, text=True).stdout.strip()
        expected_epoch = int(subprocess.run(["git", "-C", str(ROOT), "show", "-s", "--format=%ct", expected_source_sha],
                                            check=True, capture_output=True, text=True).stdout.strip())
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise GateError("build provenance source commit or timestamp is unavailable") from None
    if value["source"]["tree_sha"] != expected_tree or value["build_configuration"]["source_date_epoch"] != expected_epoch:
        raise GateError("build provenance tree SHA or SOURCE_DATE_EPOCH does not match the source commit")
    if value["candidate_state"] != "UNSIGNED_DEVELOPMENT" or value["signing"]["state"] != "UNSIGNED" or value["signing"]["provenance_status"] != "SIGNER_PROVENANCE_BLOCKED":
        raise GateError("cloud candidate provenance must remain explicitly unsigned and signer-blocked")
    if value["signing"]["profile_sha256"] != EXPECTED_PROFILE_SHA256:
        raise GateError("cloud candidate provenance does not identify the repository's approved entitlement profile")
    if (value["package"] != {"identifier": "com.ioscaffeinate.cli", "version": "0.2.0~rc1-1", "architecture": "iphoneos-arm"}
            or value["target"]["binary_architecture"] != "arm64 Mach-O"
            or value["build_configuration"]["target_triple"] != "arm64-apple-ios12.0"):
        raise GateError("build provenance candidate identity or target is incorrect")
    if value["ci"]["source_sha_verified"] is not True or value["validation"]["device_installation"] != "NOT_PERFORMED":
        raise GateError("build provenance overstates source verification or device installation")
    if value["reproducibility"]["independent_builds"] != 2 or value["reproducibility"]["status"] == "NOT_TESTED":
        raise GateError("P020 build provenance must characterize two independent builds")
    artifact_hashes: dict[str, str] = {}
    for name, record in value["artifacts"].items():
        raw = store.read(record["path"])
        digest = hashlib.sha256(raw).hexdigest()
        if digest != record["sha256"]:
            raise GateError(f"build provenance artifact SHA-256 mismatch: {name}")
        artifact_hashes[name] = digest
    first = (artifact_hashes["cli"], artifact_hashes["daemon"], artifact_hashes["package"])
    second = (artifact_hashes["second_build_cli"], artifact_hashes["second_build_daemon"], artifact_hashes["second_build_package"])
    repro = value["reproducibility"]
    same_bytes = first == second
    if repro["artifact_hashes_match"] is not same_bytes:
        raise GateError("build provenance reproducibility claim disagrees with measured artifact hashes")
    if repro["status"] == "REPRODUCIBLE" and (not repro["inputs_match"] or not same_bytes):
        raise GateError("REPRODUCIBLE claim lacks matching inputs and byte-identical artifacts")
    if repro["status"] == "NON_REPRODUCIBLE" and (not repro["inputs_match"] or same_bytes):
        raise GateError("NON_REPRODUCIBLE claim disagrees with recorded inputs or artifacts")
    if repro["status"] == "INCONCLUSIVE" and repro["inputs_match"]:
        raise GateError("INCONCLUSIVE reproducibility claim must identify differing build inputs")
    return value


def _verify_auth_ref(name: str, ref: dict[str, Any] | None, store: EvidenceStore, expected_type: str, trusted_keyring: Path | None) -> dict[str, Any]:
    if ref is None:
        return {"status": "PENDING", "reason": f"{name} evidence is missing"}
    if ref["artifact_type"] != expected_type:
        return {"status": "FAILED", "reason": f"expected {expected_type}, received {ref['artifact_type']}"}
    try:
        value, digest = _load_evidence(store, ref["file"])
    except GateError as exc:
        return {"status": "FAILED", "reason": str(exc)}
    receipt = ref.get("review_receipt")
    if receipt is None:
        return {"status": "UNVERIFIED", "reason": "independent review receipt is missing"}
    try:
        ok, note = _reviewed(store, receipt, digest, trusted_keyring)
    except GateError as exc:
        if str(exc).startswith("UNVERIFIED:"):
            return {"status": "UNVERIFIED", "reason": str(exc)}
        return {"status": "FAILED", "reason": str(exc)}
    if not ok:
        return {"status": "BLOCKED", "reason": note}
    if value.get("status") in {"FAILED", "OPEN", "REJECTED"}:
        return {"status": "FAILED", "reason": f"evidence records {value['status']}"}
    return {"status": "PASS", "reason": note}


def _validate_chain(source: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    chain = source["milestone_chain"]
    for index, expected in enumerate(EXPECTED_CHAIN):
        milestone, pr, branch, head, base_branch, base_sha, merge_sha = expected
        item = chain[index]
        if (item["milestone"], item["pr"], item["branch"], item["head_sha"], item["base_branch"], item["base_sha"], item["merge_sha"]) != (milestone, pr, branch, head, base_branch, base_sha, merge_sha):
            issues.append(f"{milestone} PR #{pr} head/base differs from the verified P011–P019 chain")
        if item["state"] != "MERGED":
            issues.append(f"{milestone} PR #{pr} is {item['state']}")
        if item["mergeability"] == "CONFLICTING":
            issues.append(f"{milestone} PR #{pr} is conflicting")
        if item["review_state"] in {"CHANGES_REQUESTED", "REVIEW_REQUIRED", "UNKNOWN"}:
            issues.append(f"{milestone} PR #{pr} review state is {item['review_state']}")
        if item["exact_head_ci"] != "PASS":
            issues.append(f"{milestone} PR #{pr} exact-head CI is {item['exact_head_ci']}")
    if source["p020_base_branch"] != "main":
        issues.append("P020 base branch is not the integrated main branch")
    p019_head = EXPECTED_CHAIN[-1][3]
    try:
        source_tree = subprocess.run(["git", "-C", str(ROOT), "rev-parse", f"{source['commit_sha']}^{{tree}}"], capture_output=True, text=True, check=True).stdout.strip()
        if source_tree != source["tree_sha"]:
            issues.append("manifest tree SHA does not match the exact source commit")
        p019_is_source_ancestor = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", p019_head, source["commit_sha"]], capture_output=True)
        if p019_is_source_ancestor.returncode != 0:
            issues.append("P020 source does not retain the exact P019 commit as an ancestor")
        base_has_p019 = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", p019_head, source["p020_base_sha"]], capture_output=True)
        if base_has_p019.returncode != 0:
            issues.append("integrated main base does not contain the exact P019 commit")
        for milestone, _pr, _branch, _head, _base_branch, _base_sha, merge_sha in EXPECTED_CHAIN:
            present = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", merge_sha, source["p020_base_sha"]], capture_output=True)
            if present.returncode != 0:
                issues.append(f"{milestone} merge commit is not an ancestor of the integrated main base")
        merge_base = subprocess.run(["git", "-C", str(ROOT), "merge-base", source["commit_sha"], source["p020_base_sha"]], capture_output=True, text=True, check=True).stdout.strip()
        if merge_base != p019_head:
            issues.append("P020 source/base merge-base is not the preserved P019 source head")
    except (OSError, subprocess.CalledProcessError):
        issues.append("source, P019 head, or integrated base commit is unavailable for DAG verification")
    if source["commit_sha"] == EXPECTED_CHAIN[-1][3]:
        issues.append("P020 source commit has no integration change beyond P019")
    return issues


def assess(manifest_path: Path, expected_source_sha: str | None = None, trusted_keyring: Path | None = None) -> dict[str, Any]:
    manifest, root = _load_manifest(manifest_path)
    source = manifest["source"]
    chain_issues = _validate_chain(source)
    if expected_source_sha:
        if source["commit_sha"] != expected_source_sha:
            chain_issues.append("manifest source SHA differs from the required exact source SHA")
    else:
        try:
            head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            if source["commit_sha"] != head:
                chain_issues.append("manifest source SHA differs from the current source checkout")
        except (OSError, subprocess.CalledProcessError):
            chain_issues.append("current Git source identity is unavailable")
    store = EvidenceStore(root)
    cloud = {name: _verify_cloud_gate(name, gate, store, source["commit_sha"]) for name, gate in manifest["cloud_gates"].items()}
    hardware = {name: _evaluate_hardware_gate(name, gate, store, trusted_keyring, source["commit_sha"]) for name, gate in manifest["hardware_gates"].items()}
    payloads = {name: result.pop("_payloads", {}) for name, result in hardware.items()}
    identity_issues = _candidate_evidence_issues(payloads)
    if identity_issues:
        reason = "; ".join(identity_issues)
        for name in ("p010_signer_provenance", "installed_candidate_identity", "p019_supervised_cycles"):
            hardware[name] = {"status": "FAILED", "reason": reason, "evidence_count": hardware[name]["evidence_count"]}
    auth = manifest["authorization"]
    authorization = {
        "release_critical_issues_resolved": _verify_security_closeout(auth["release_critical_issues_resolved"], store, trusted_keyring),
        "operator_acceptance_review": _verify_auth_ref("operator_acceptance_review", auth["operator_acceptance_review"], store, "OPERATOR_ACCEPTANCE_REVIEW", trusted_keyring),
        "limitations_disclosed": _verify_auth_ref("limitations_disclosed", auth["limitations_disclosed"], store, "LIMITATIONS_DISCLOSURE", trusted_keyring),
        "rollback_plan_review": _verify_auth_ref("rollback_plan_review", auth["rollback_plan_review"], store, "ROLLBACK_PLAN_REVIEW", trusted_keyring),
        "human_release_approval": _verify_auth_ref("human_release_approval", auth["human_release_approval"], store, "HUMAN_RELEASE_APPROVAL", trusted_keyring),
        "publication_authorization": "NOT_PROVIDED_TO_THIS_TOOL",
    }
    blockers: list[str] = []
    blockers.extend(f"{name}: {reason}" for name, reason in sorted(cloud.items()) if reason["status"] != "PASS")
    blockers.extend(f"{name}: {reason['reason']}" for name, reason in sorted(hardware.items()) if reason["status"] != "PASS")
    blockers.extend(f"{name}: {reason['reason']}" for name, reason in sorted(authorization.items()) if isinstance(reason, dict) and reason["status"] != "PASS")
    blockers.extend(chain_issues)
    required_pass = all(item["status"] == "PASS" for item in cloud.values()) and all(item["status"] == "PASS" for item in hardware.values())
    authorization_pass = all(isinstance(item, dict) and item["status"] == "PASS" for key, item in authorization.items() if key != "publication_authorization")
    if (chain_issues
            or any(item["status"] in {"FAILED", "BLOCKED"} for item in hardware.values())
            or any(item["status"] in {"FAILED", "BLOCKED"} for item in cloud.values())
            or any(isinstance(item, dict) and item["status"] in {"FAILED", "BLOCKED"} for item in authorization.values())):
        decision = "RELEASE_BLOCKED"
    elif not required_pass:
        decision = "RELEASE_BLOCKED"
    elif not authorization_pass:
        decision = "REVIEW_REQUIRED"
    else:
        decision = "READY_FOR_RELEASE_AUTHORIZATION"
    return {
        "assessment_version": 1,
        "source_commit_sha": source["commit_sha"],
        "release_version": manifest["release"]["version"],
        "decision": decision,
        "cloud_gates": cloud,
        "hardware_gates": hardware,
        "authorization_gates": authorization,
        "chain_issues": chain_issues,
        "blockers": blockers,
        "publication_authorized": False,
        "interpretation": "This offline assessment does not authenticate physical reality or authorize publication; evidence hashes and structured review receipts require independent human review.",
    }


def _verify_security_closeout(refs: list[dict[str, Any]] | None, store: EvidenceStore, trusted_keyring: Path | None) -> dict[str, Any]:
    if refs is None or not refs:
        return {"status": "PENDING", "reason": "security findings closeout is missing"}
    if len(refs) != 1:
        return {"status": "FAILED", "reason": "security findings closeout must contain exactly one consolidated record"}
    result = _verify_auth_ref("release_critical_issues_resolved", refs[0], store, "P020_SECURITY_CLOSEOUT", trusted_keyring)
    if result["status"] != "PASS":
        return result
    value, _digest = _load_evidence(store, refs[0]["file"])
    findings = value.get("findings")
    if not isinstance(findings, list) or value.get("release_blocking_open") != 0:
        return {"status": "FAILED", "reason": "security closeout must enumerate findings and report zero open release blockers"}
    if value.get("status") not in {"CLOSED", "RESOLVED"}:
        return {"status": "BLOCKED", "reason": "security findings closeout is not closed"}
    for finding in findings:
        if not isinstance(finding, dict):
            return {"status": "FAILED", "reason": "security closeout contains a malformed finding"}
        required_fields = {"finding_id", "severity", "affected_component", "reproduction_evidence", "security_consequence", "fix_commit", "regression_test", "verification_status", "release_blocking"}
        if (not required_fields.issubset(finding) or not isinstance(finding["finding_id"], str) or not finding["finding_id"]
                or finding["severity"] not in {"Critical", "High", "Medium", "Low", "Informational"}
                or not isinstance(finding["release_blocking"], bool)
                or any(not isinstance(finding[key], str) or not finding[key].strip() for key in required_fields - {"release_blocking"})
                or finding["verification_status"] not in {"OPEN", "FIXED_UNVERIFIED", "RESOLVED_VERIFIED", "ACCEPTED_WITH_MITIGATION", "NOT_A_SECURITY_DEFECT", "EXTERNAL_BLOCKER"}):
            return {"status": "FAILED", "reason": "security closeout finding lacks required register fields or valid severity"}
        if finding.get("severity") in {"Critical", "High"} and finding.get("verification_status") != "RESOLVED_VERIFIED":
            return {"status": "BLOCKED", "reason": "a critical or high security finding is not resolved and verified"}
        if finding.get("release_blocking") is True and finding.get("verification_status") != "RESOLVED_VERIFIED":
            return {"status": "BLOCKED", "reason": "a release-blocking security finding is not resolved and verified"}
    return result


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# P020 Release Readiness Assessment", "",
        f"- Release: `{result['release_version']}` (draft target)",
        f"- Source: `{result['source_commit_sha']}`",
        f"- Decision: **{result['decision']}**",
        "- Publication authorized: **NO**", "",
        "## Cloud gates", "", "| Gate | Status | Evidence | Reason |", "|---|---|---:|---|",
    ]
    for name, value in sorted(result["cloud_gates"].items()):
        lines.append(f"| {name} | {value['status']} | {value['evidence_count']} | {value['reason']} |")
    lines.extend(["", "## Hardware gates", "", "| Gate | Status | Evidence | Reason |", "|---|---|---:|---|"])
    for name, value in sorted(result["hardware_gates"].items()):
        lines.append(f"| {name} | {value['status']} | {value['evidence_count']} | {value['reason']} |")
    lines.extend(["", "## Authorization review", "", "| Gate | Status | Reason |", "|---|---|---|"])
    for name, value in sorted(result["authorization_gates"].items()):
        if isinstance(value, dict):
            lines.append(f"| {name} | {value['status']} | {value['reason']} |")
        else:
            lines.append(f"| {name} | {value} | Publication remains a separate authorized action. |")
    lines.extend(["", "## Blockers", ""])
    lines.extend([f"- {item}" for item in result["blockers"]] or ["- None reported by the evidence manifest."])
    lines.extend(["", result["interpretation"], ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("assess", "report"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--manifest", type=Path, required=True)
        cmd.add_argument("--expected-source-sha", help="require this exact checked-out source SHA")
        cmd.add_argument("--trusted-review-keyring", type=Path, help="absolute, externally provisioned GPG keyring for independent review signatures")
    args = parser.parse_args(argv)
    try:
        result = assess(args.manifest, args.expected_source_sha, args.trusted_review_keyring)
    except (GateError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.command == "report":
        print(render_report(result), end="")
    else:
        print(json.dumps(result, sort_keys=True, indent=2))
    # A blocked decision is an expected successful assessment. CI tests the decision separately.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
