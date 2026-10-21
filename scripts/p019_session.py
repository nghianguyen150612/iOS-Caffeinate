#!/usr/bin/env python3
"""Offline P019 planning, session validation, analysis, and reporting.

This tool reads local files and writes only when the operator explicitly uses
``init`` or ``record-confirmation`` with a new output path. It has no SSH client,
device transport, daemon control, package installer, launchd writer, or IOKit
binding. Its evidence result is a review aid, never proof that a JSON claim is
physically true.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import p009_evidence
import p012_analyze
import p012_common
import p018_validate_export


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "experiments/p019/protocol-v1.json"
PROTOCOL_SCHEMA_PATH = ROOT / "experiments/p019/protocol-v1.schema.json"
SESSION_SCHEMA_PATH = ROOT / "experiments/p019/session-v1.schema.json"
RESULT_SCHEMA_PATH = ROOT / "experiments/p019/acceptance-result-v1.schema.json"
P012_PROTOCOL_PATH = ROOT / "experiments/p012/protocol-v1.json"
P012_PROTOCOL_SHA256 = "5cf6c44806be0f3d510cbef368ecf96a95d9092585b7f02d6f04674760af3169"
STABLE_PACKAGE_SHA256 = "439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c"
RECORDED_LDID_VERSION = "2.1.5-procursus7"
RECORDED_LDID_SHA256 = "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c"
PROFILE_ID = "amethyst-ios12-rootful"
PROFILE_SHA256 = "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca"
SOURCES = {"DEVICE_REPORTED", "EXTERNAL_OBSERVER", "OPERATOR_RECORDED", "SIMULATED", "MOCK", "CI"}
PHYSICAL_SOURCES = {"DEVICE_REPORTED", "EXTERNAL_OBSERVER", "OPERATOR_RECORDED"}
FORBIDDEN_ACCEPTANCE_SOURCES = {"SIMULATED", "MOCK", "CI", "UNASSIGNED"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

EVENT_TYPES = {
    "package_preflight": "DEVICE_PREFLIGHT",
    "package_integrity": "PACKAGE_INTEGRITY_CHECK",
    "signature_acceptance": "SIGNATURE_ACCEPTANCE",
    "package_installation": "PACKAGE_INSTALL",
    "daemon_launch": "DAEMON_LAUNCH",
    "assertion_acquire": "ASSERTION_ACQUIRE_SUCCESS",
    "hold": "HOLD_ACTIVE",
    "assertion_release": "ASSERTION_RELEASE",
    "daemon_exit": "DAEMON_EXIT",
    "screen_lock": "SCREEN_LOCK",
    "lan_observation": "LAN_OBSERVATION",
    "tailscale_observation": "TAILSCALE_OBSERVATION",
    "battery": "BATTERY_OBSERVATION",
    "thermal": "THERMAL_OBSERVATION",
    "physical_recovery": "PHYSICAL_RECOVERY",
    "abnormal_or_interrupted_trial": None,
}

REQUIRED_P009_PURPOSES = {
    "package_preflight", "package_integrity", "signature_acceptance", "package_installation",
    "daemon_launch", "assertion_acquire", "hold", "assertion_release", "daemon_exit",
    "screen_lock", "lan_observation", "tailscale_observation", "battery", "thermal",
    "physical_recovery",
}


class P019Error(ValueError):
    """Invalid P019 input or evidence cross-reference."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_read(path: Path, maximum: int = 2 * 1024 * 1024) -> bytes:
    if path.is_symlink():
        raise P019Error("refusing to read a symbolic-link input")
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise P019Error("input must be a bounded regular file")
        return path.read_bytes()
    except OSError as exc:
        raise P019Error("input file is missing or cannot be read") from exc


def _load_json(path: Path, maximum: int = 2 * 1024 * 1024) -> Any:
    return p012_common.parse_json_bytes(_safe_read(path, maximum))


def _load_schema(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict) or not isinstance(value.get("$id"), str):
        raise P019Error("a required P019 schema is malformed")
    return value


def load_protocol() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    protocol = _load_json(PROTOCOL_PATH)
    schema = _load_schema(PROTOCOL_SCHEMA_PATH)
    issues = ["schema: " + item for item in p012_common.validate_json_schema(protocol, schema)]
    if not isinstance(protocol, dict):
        return {}, {}, issues + ["protocol must be an object"]
    if protocol.get("protocol_id") != "P019" or protocol.get("protocol_version") != 1:
        issues.append("unsupported P019 protocol identity or version")
    expected_digest = protocol.get("p012_reference", {}).get("sha256")
    actual_digest = _sha256(_safe_read(P012_PROTOCOL_PATH))
    if expected_digest != actual_digest or actual_digest != P012_PROTOCOL_SHA256:
        issues.append("p012 protocol v1 digest differs from the preregistered reference")
    p012_protocol = _load_json(P012_PROTOCOL_PATH)
    p012_issues = p012_common.validate_protocol(p012_protocol)
    issues.extend("P012 protocol: " + item for item in p012_issues)
    reference = protocol.get("p012_reference", {})
    if reference.get("conditions") != [item.get("id") for item in p012_protocol.get("conditions", [])]:
        issues.append("P019 conditions differ from P012 v1")
    if reference.get("routes") != p012_protocol.get("design", {}).get("routes"):
        issues.append("P019 routes differ from P012 v1")
    if reference.get("planned_probe_trials") != p012_protocol.get("design", {}).get("total_planned_probe_trials"):
        issues.append("P019 planned probe count differs from P012 v1")
    if reference.get("active_hold_seconds") != p012_protocol.get("assertion", {}).get("active_hold_seconds"):
        issues.append("P019 hold duration differs from P012 v1")
    if reference.get("maximum_hold_seconds") != p012_protocol.get("assertion", {}).get("maximum_hold_seconds"):
        issues.append("P019 assertion ceiling differs from P012 v1")
    return protocol, p012_protocol, issues


def protocol_sha256() -> str:
    return _sha256(_safe_read(PROTOCOL_PATH))


def build_plan(protocol: dict[str, Any], p012_protocol: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_version": protocol["protocol_version"],
        "protocol_status": protocol["protocol_status"],
        "protocol_sha256": protocol_sha256(),
        "target_platform": protocol["target_platform"],
        "cloud_only": True,
        "device_actions_started": False,
        "phase_order": [item["id"] for item in protocol["phases"]],
        "phase_entry_gates": [{"phase": item["id"], "name": item["name"], "entry_gate": item["entry_gate"], "state_changes_allowed": item["state_changes_allowed"]} for item in protocol["phases"]],
        "p012_matrix": {
            "conditions": p012_protocol["conditions"],
            "planned_probe_trials": p012_protocol["design"]["total_planned_probe_trials"],
            "quiet_interval_seconds": p012_protocol["quiet_period"]["seconds"],
            "quiet_interval_allowed_seconds": [p012_protocol["quiet_period"]["minimum_seconds"], p012_protocol["quiet_period"]["maximum_seconds"]],
            "hold_seconds": p012_protocol["assertion"]["active_hold_seconds"],
            "maximum_hold_seconds": p012_protocol["assertion"]["maximum_hold_seconds"],
            "probe_timeout_seconds": p012_protocol["probe"]["timeout_seconds"],
            "maximum_probes_per_trial": p012_protocol["probe"]["maximum_probes_per_trial"],
            "route_order_by_repetition": p012_protocol["design"]["route_order_by_repetition"],
            "condition_order_by_repetition": p012_protocol["design"]["condition_order_by_repetition"],
            "automated_physical_trial_series": False,
        },
        "repeated_bounded_sessions": protocol["endurance_plan"],
        "required_prerequisite_gates": protocol["prerequisite_gates"],
        "stop_conditions": protocol["stop_conditions"],
        "result_limit": "A plan is not authorization, a physical result, or evidence of reliability.",
    }


def _empty_prerequisites(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"gate_id": gate, "status": "NOT_ASSESSED", "source_class": "UNASSIGNED", "evidence_ref": None, "reason": "Not assessed; no physical operation is authorized by this template."}
        for gate in protocol["prerequisite_gates"]
    ]


def create_session(session_id: str, source_commit_sha: str, protocol: dict[str, Any]) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(session_id):
        raise P019Error("session ID must contain only letters, digits, dot, underscore, or hyphen")
    if not HEX40.fullmatch(source_commit_sha):
        raise P019Error("source commit SHA must be an exact lowercase 40-character Git SHA")
    return {
        "session_version": 1,
        "protocol_id": "P019",
        "protocol_version": 1,
        "protocol_sha256": protocol_sha256(),
        "session_id": session_id,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_commit_sha": source_commit_sha,
        "session_state": "NOT_STARTED",
        "current_phase": 0,
        "evidence_class": "UNASSIGNED",
        "candidate": {
            "artifact_role": "UNASSIGNED", "source_commit_sha": None, "build_id": None,
            "package_identifier": None, "package_version": None, "package_sha256": None,
            "cli_binary_sha256": None, "daemon_binary_sha256": None, "profile_id": None,
            "profile_sha256": None, "ldid_version": None, "ldid_sha256": None,
            "signature_validation": "NOT_RUN", "installed_paths_verified": False,
            "rollback_artifact_sha256": None,
        },
        "prerequisites": _empty_prerequisites(protocol),
        "supervision": {"operator_id": None, "attendance": "NOT_RECORDED", "independent_recovery": "NOT_RECORDED", "recovery_method_available": False, "source_class": "UNASSIGNED"},
        "operator_confirmations": [],
        "trial_records": [],
        "bounded_cycles": [],
        "resource_observations": [],
        "p009_evidence": {"status": "NOT_PROVIDED", "validation_status": "NOT_RUN", "replay_status": "NOT_RUN", "packages": [], "event_refs": []},
        "p018_export": {"status": "NOT_CREATED", "manifest_sha256": None, "source_commit_sha": None, "hardware_evidence_accepted": "NOT_ESTABLISHED"},
        "review": {"status": "PENDING", "reviewer_id": None, "operator_id": None, "independent": False, "reviewed_at_utc": None, "reviewed_p009_session_sha256": None, "checked_source_hashes": [], "decision": "NOT_DECIDED", "findings": []},
        "incidents": [],
        "protocol_deviations": [],
    }


def validate_session(session: Any, protocol: dict[str, Any], p012_protocol: dict[str, Any]) -> list[str]:
    schema = _load_schema(SESSION_SCHEMA_PATH)
    issues = ["schema: " + item for item in p012_common.validate_json_schema(session, schema)]
    if not isinstance(session, dict):
        return issues + ["session must be an object"]
    if session.get("protocol_sha256") != protocol_sha256():
        issues.append("session protocol digest does not match the checked-in preregistered protocol")
    if session.get("protocol_id") != protocol.get("protocol_id") or session.get("protocol_version") != protocol.get("protocol_version"):
        issues.append("session protocol reference is unsupported")
    prerequisites = session.get("prerequisites", [])
    gate_ids = [item.get("gate_id") for item in prerequisites if isinstance(item, dict)]
    if set(gate_ids) != set(protocol.get("prerequisite_gates", [])) or len(gate_ids) != len(set(gate_ids)):
        issues.append("prerequisite gate set must exactly match the preregistered protocol")
    if not HEX40.fullmatch(str(session.get("source_commit_sha", ""))):
        issues.append("source_commit_sha must identify the exact P019 tooling source")
    if not str(session.get("created_at_utc", "")).endswith("Z") or p012_common.parse_utc(session.get("created_at_utc")) is None:
        issues.append("session creation timestamp must be UTC Z time")
    candidate = session.get("candidate", {})
    role = candidate.get("artifact_role")
    if role == "STABLE_V0.1.0":
        if candidate.get("package_sha256") != STABLE_PACKAGE_SHA256:
            issues.append("stable v0.1.0 artifact digest does not match the pinned P011 package")
        if candidate.get("package_identifier") != "com.ioscaffeinate.cli" or candidate.get("package_version") != "0.1.0-1":
            issues.append("stable v0.1.0 package identity does not match P011")
    if role == "DEVELOPMENT_CANDIDATE":
        if candidate.get("source_commit_sha") != session.get("source_commit_sha"):
            issues.append("development candidate source SHA must match the exact P019 source being tested")
        if candidate.get("package_identifier") not in (None, "com.ioscaffeinate.cli"):
            issues.append("development candidate package identifier is unsupported")
        if candidate.get("ldid_version") not in (None, RECORDED_LDID_VERSION) or candidate.get("ldid_sha256") not in (None, RECORDED_LDID_SHA256):
            issues.append("development candidate signer does not match the exact P010 ldid version and hash")
        if candidate.get("profile_id") not in (None, PROFILE_ID) or candidate.get("profile_sha256") not in (None, PROFILE_SHA256):
            issues.append("development candidate signing profile differs from the P010 Amethyst profile")
        if candidate.get("signature_validation") == "PASS" and (candidate.get("ldid_sha256") != RECORDED_LDID_SHA256 or candidate.get("profile_sha256") != PROFILE_SHA256):
            issues.append("signature validation cannot pass without exact signer and entitlement-profile provenance")
        required_candidate_fields = ("build_id", "package_version", "package_sha256", "cli_binary_sha256", "daemon_binary_sha256", "rollback_artifact_sha256")
        if any(not candidate.get(field) for field in required_candidate_fields):
            issues.append("development candidate identity is incomplete")
        for field in ("package_sha256", "cli_binary_sha256", "daemon_binary_sha256", "rollback_artifact_sha256"):
            if candidate.get(field) is not None and not HEX64.fullmatch(str(candidate[field])):
                issues.append(f"development candidate {field} is not a SHA-256")
        if candidate.get("signature_validation") != "PASS":
            issues.append("development candidate P010 package and entitlement validation is not PASS")
    if candidate.get("installed_paths_verified") and (not HEX64.fullmatch(str(candidate.get("cli_binary_sha256", ""))) or not HEX64.fullmatch(str(candidate.get("daemon_binary_sha256", "")))):
        issues.append("installed-path verification requires the actual CLI and daemon binary hashes")

    trial_ids: set[str] = set()
    cells: set[tuple[str, str, int]] = set()
    trial_origins: set[str] = set()
    for index, record in enumerate(session.get("trial_records", [])):
        if not isinstance(record, dict):
            issues.append(f"trial_records[{index}] is not an object")
            continue
        trial_check = p012_common.validate_trial(record, p012_protocol)
        issues.extend(f"trial_records[{index}]: {item}" for item in trial_check.get("issues", []))
        trial_id = record.get("trial_id")
        if isinstance(trial_id, str):
            if trial_id in trial_ids:
                issues.append(f"duplicate P012 trial ID: {trial_id}")
            trial_ids.add(trial_id)
        condition, route, repetition = record.get("condition_id"), record.get("route"), record.get("repetition")
        if isinstance(condition, str) and isinstance(route, str) and type(repetition) is int:
            cell = (condition, route, repetition)
            if cell in cells:
                issues.append("duplicate condition/route/repetition cell")
            cells.add(cell)
        origin = record.get("evidence_origin")
        if isinstance(origin, str):
            trial_origins.add(origin)
    if session.get("evidence_class") in FORBIDDEN_ACCEPTANCE_SOURCES and trial_origins and trial_origins - {session.get("evidence_class")}:
        issues.append("trial evidence classes differ from the session's declared fixture class")
    if session.get("evidence_class") in PHYSICAL_SOURCES and trial_origins & FORBIDDEN_ACCEPTANCE_SOURCES:
        issues.append("physical session label cannot promote simulated, mock, or CI trial records")

    cycles = session.get("bounded_cycles", [])
    cycle_ids: set[str] = set()
    period_dates: dict[int, set[str]] = {}
    period_numbers: dict[int, set[int]] = {}
    for index, cycle in enumerate(cycles):
        if not isinstance(cycle, dict):
            issues.append(f"bounded_cycles[{index}] is not an object")
            continue
        cycle_id = cycle.get("cycle_id")
        if isinstance(cycle_id, str):
            if cycle_id in cycle_ids:
                issues.append(f"duplicate bounded cycle ID: {cycle_id}")
            cycle_ids.add(cycle_id)
        duration = cycle.get("assertion_duration_seconds")
        if type(duration) is int and duration > 300:
            issues.append(f"bounded cycle {cycle_id} exceeds the 300-second assertion ceiling")
        if cycle.get("attended") is False and cycle.get("acquisition") != "NOT_ATTEMPTED":
            issues.append(f"bounded cycle {cycle_id} records a physical operation without attendance")
        if cycle.get("release") == "FAILED" or cycle.get("cleanup_state") in {"UNRESOLVED", "CORRUPT"}:
            issues.append(f"bounded cycle {cycle_id} has unresolved cleanup and must stop further testing")
        period = cycle.get("observation_period")
        number = cycle.get("cycle_number")
        start = p012_common.parse_utc(cycle.get("started_at_utc"))
        end = p012_common.parse_utc(cycle.get("ended_at_utc"))
        if not str(cycle.get("started_at_utc", "")).endswith("Z") or not str(cycle.get("ended_at_utc", "")).endswith("Z"):
            issues.append(f"bounded cycle {cycle_id} timestamps must be UTC Z timestamps")
        if cycle.get("timestamp_uncertainty_ms") is None and (cycle.get("acquisition") == "CONFIRMED" or cycle.get("release") == "CONFIRMED"):
            issues.append(f"bounded cycle {cycle_id} lacks UTC timestamp uncertainty")
        if start and end:
            if end < start:
                issues.append(f"bounded cycle {cycle_id} ends before it starts")
            if type(period) is int:
                period_dates.setdefault(period, set()).add(start.date().isoformat())
        if type(period) is int and type(number) is int:
            period_numbers.setdefault(period, set()).add(number)
            if number > 1 and (cycle.get("rest_before_seconds") is None or cycle.get("rest_before_seconds", 0) < 300):
                issues.append(f"bounded cycle {cycle_id} lacks the preregistered five-minute unasserted rest")
        if cycle.get("battery_api_state") == "UNAVAILABLE" and cycle.get("battery_operator_state") == "NOT_RECORDED":
            issues.append(f"bounded cycle {cycle_id} has no usable battery safety observation")
        if cycle.get("thermal_api_state") == "UNAVAILABLE" and cycle.get("thermal_operator_state") == "NOT_RECORDED":
            issues.append(f"bounded cycle {cycle_id} has no usable thermal safety observation")
        if cycle.get("duration_method") == "UNKNOWN" or not cycle.get("duration_timebase_id") or cycle.get("duration_uncertainty_ms") is None:
            if cycle.get("acquisition") == "CONFIRMED" or cycle.get("release") == "CONFIRMED":
                issues.append(f"bounded cycle {cycle_id} lacks a duration timebase or uncertainty")
        if cycle.get("duration_method") == "DEVICE_MONOTONIC":
            if not cycle.get("device_timebase_id") or cycle.get("duration_timebase_id") != cycle.get("device_timebase_id"):
                issues.append(f"bounded cycle {cycle_id} device-monotonic duration lacks matching device timebase identity")
            if cycle.get("device_monotonic_elapsed_seconds") is None or cycle.get("device_clock_uncertainty_ms") is None:
                issues.append(f"bounded cycle {cycle_id} device-monotonic duration lacks elapsed-time or clock uncertainty")
        if cycle.get("duration_method") == "HOST_MONOTONIC":
            if cycle.get("duration_timebase_id") != cycle.get("observer_timebase_id"):
                issues.append(f"bounded cycle {cycle_id} host-monotonic duration uses another timebase")
            if cycle.get("observer_monotonic_elapsed_seconds") is None or cycle.get("timestamp_uncertainty_ms") is None:
                issues.append(f"bounded cycle {cycle_id} host-monotonic duration lacks elapsed-time or clock uncertainty")
    for period, dates in period_dates.items():
        if len(dates) > 1:
            issues.append(f"observation period {period} spans multiple calendar dates")
    period_values = [(period, next(iter(dates))) for period, dates in period_dates.items() if dates]
    for index, (period, day) in enumerate(period_values):
        if any(day == other_day for other_period, other_day in period_values[index + 1:] if period != other_period):
            issues.append("repeated observation periods must occur on separate calendar dates")
    if any(len(numbers) > 4 for numbers in period_numbers.values()):
        issues.append("a repeated observation period exceeds four preregistered cycles")
    if len(cycles) == 12 and set(period_numbers) != {1, 2, 3}:
        issues.append("the 12-cycle plan must contain all three observation periods")
    if len(cycles) == 12 and any(period_numbers.get(period) != {1, 2, 3, 4} for period in (1, 2, 3)):
        issues.append("each of the three observation periods must contain cycles 1 through 4")

    observations = session.get("resource_observations", [])
    observation_ids: set[str] = set()
    for item in observations:
        if not isinstance(item, dict):
            continue
        identifier = item.get("observation_id")
        if isinstance(identifier, str) and identifier in observation_ids:
            issues.append(f"duplicate resource observation ID: {identifier}")
        if isinstance(identifier, str):
            observation_ids.add(identifier)
        if not str(item.get("observed_at_utc", "")).endswith("Z") or p012_common.parse_utc(item.get("observed_at_utc")) is None:
            issues.append("P016 observations must retain UTC Z timestamps")
        if item.get("availability") == "UNAVAILABLE" and item.get("value") is not None:
            issues.append("an unavailable P016 value must remain null")
        if item.get("field") == "battery_percent" and item.get("availability") == "AVAILABLE":
            if type(item.get("value")) is not int or not 0 <= item["value"] <= 100:
                issues.append("available battery percentage must be an observed integer from 0 to 100")

    p009_record = session.get("p009_evidence", {})
    package_ids = [item.get("session_id") for item in p009_record.get("packages", []) if isinstance(item, dict)]
    if len(package_ids) != len(set(package_ids)):
        issues.append("duplicate P009 evidence package session ID")
    package_id_set = set(package_ids)
    event_ref_keys: set[tuple[str, str]] = set()
    for ref in p009_record.get("event_refs", []):
        if not isinstance(ref, dict):
            continue
        key = (str(ref.get("p009_session_id")), str(ref.get("event_id")))
        if key in event_ref_keys:
            issues.append("duplicate P009 event reference")
        event_ref_keys.add(key)
        if ref.get("p009_session_id") not in package_id_set:
            issues.append("P009 event reference does not name a listed raw evidence package")

    confirmation_ids = [item.get("confirmation_id") for item in session.get("operator_confirmations", []) if isinstance(item, dict)]
    if len(confirmation_ids) != len(set(confirmation_ids)):
        issues.append("duplicate operator confirmation ID")
    for item in session.get("operator_confirmations", []):
        if isinstance(item, dict) and (not str(item.get("recorded_at_utc", "")).endswith("Z") or p012_common.parse_utc(item.get("recorded_at_utc")) is None):
            issues.append("operator confirmations must retain UTC Z timestamps")
    incident_ids = [item.get("incident_id") for item in session.get("incidents", []) if isinstance(item, dict)]
    if len(incident_ids) != len(set(incident_ids)):
        issues.append("duplicate incident ID")
    for item in session.get("incidents", []) + session.get("protocol_deviations", []):
        if isinstance(item, dict) and (not str(item.get("occurred_at_utc", "")).endswith("Z") or p012_common.parse_utc(item.get("occurred_at_utc")) is None):
            issues.append("incidents and deviations must retain UTC Z timestamps")
    deviation_ids = {item.get("deviation_id") for item in session.get("protocol_deviations", []) if isinstance(item, dict)}
    for cycle in cycles:
        if isinstance(cycle, dict) and set(cycle.get("deviation_ids", [])) - deviation_ids:
            issues.append("bounded cycle references an absent protocol deviation")
    try:
        p009_evidence.scan_secrets(session)
    except p009_evidence.EvidenceError:
        issues.append("session contains a prohibited secret-like field or value")
    return sorted(set(issues))


def _physical_status(gate: dict[str, Any]) -> tuple[str, str]:
    status = gate.get("status")
    source = gate.get("source_class")
    if status == "PASS" and source in PHYSICAL_SOURCES and gate.get("evidence_ref"):
        return "PASS", "reported prerequisite has physical/operator provenance; independent review remains required"
    if status == "BLOCKED":
        return "BLOCKED", gate.get("reason") or "blocked by the recorded prerequisite"
    if status == "NOT_APPLICABLE":
        return "NOT_APPLICABLE", gate.get("reason") or "not applicable to the declared tested scope"
    if status == "PASS" and source in FORBIDDEN_ACCEPTANCE_SOURCES:
        return "BLOCKED", "simulated, mock, CI, or unassigned data cannot satisfy a hardware gate"
    if status == "PASS" and source in PHYSICAL_SOURCES:
        return "PENDING", "a reviewed evidence reference is required for every passed gate"
    return "PENDING", gate.get("reason") or "required physical evidence is not established"


def _inspect_p009(session: dict[str, Any], directories: list[Path]) -> dict[str, Any]:
    references = session["p009_evidence"]
    errors: list[str] = []
    packages: dict[str, dict[str, Any]] = {}
    for directory in directories:
        try:
            package = p009_evidence.load_package(directory)
            raw = package["session"]
            sid = raw["session_id"]
            if sid in packages:
                errors.append("duplicate P009 directory session ID")
                continue
            packages[sid] = package
        except (p009_evidence.EvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(f"P009 package rejected: {type(exc).__name__}")
    listed = {item["session_id"]: item for item in references["packages"]}
    for sid, package in packages.items():
        ref = listed.get(sid)
        if ref is None:
            errors.append("unlisted P009 raw package supplied for review")
            continue
        raw = package["session"]
        device = raw.get("device", {})
        if device.get("model") != "iPad mini 2 A1489 / iPad4,4" or device.get("ios_version") != "12.5.7" or device.get("jailbreak_bootstrap") != "Amethyst / Procursus rootful":
            errors.append("P009 raw package does not identify the preregistered reference platform")
        if ref["session_sha256"] != package["session_sha256"] or ref["manifest_sha256"] != package["manifest_sha256"]:
            errors.append("P009 raw hash does not match its P019 cross-reference")
        if ref["artifact_role"] == "STABLE_V0.1.0" and ref["package_sha256"] != STABLE_PACKAGE_SHA256:
            errors.append("P009 stable-package cross-reference does not match pinned v0.1.0")
        if ref["artifact_role"] == "DEVELOPMENT_CANDIDATE":
            if ref["package_sha256"] != session["candidate"].get("package_sha256") or ref["source_commit_sha"] != session["candidate"].get("source_commit_sha"):
                errors.append("P009 candidate identity differs from the exact tested candidate")
            if raw.get("build_run", {}).get("package_sha256") != ref["package_sha256"] or raw.get("source_commit_sha") != ref["source_commit_sha"]:
                errors.append("P009 raw record does not identify the declared development candidate")
        if raw.get("evidence_origin") not in PHYSICAL_SOURCES:
            errors.append("P009 raw package source is simulated, mock, or CI")
        if raw.get("build_run", {}).get("package_sha256") != ref["package_sha256"]:
            errors.append("P009 raw package digest differs from its P019 package reference")
    missing_package_refs = set(listed) - set(packages)
    if missing_package_refs:
        errors.append("one or more P019 P009 package references were not supplied for offline validation")

    all_events: dict[tuple[str, str], dict[str, Any]] = {}
    replay_statuses: list[str] = []
    for sid, package in packages.items():
        for event in p009_evidence.all_events(package["session"]):
            all_events[(sid, event["event_id"])] = event
        replay_result = p009_evidence.replay(package["session"])
        severities = {item["severity"] for item in replay_result["findings"]}
        if "ERROR" in severities:
            replay_statuses.append("FAIL")
            errors.append("P009 replay contains an error finding")
        elif severities:
            replay_statuses.append("WARNINGS")
        else:
            replay_statuses.append("PASS")

    purposes: Counter[str] = Counter()
    referenced_events: list[dict[str, Any]] = []
    for ref in references["event_refs"]:
        key = (ref["p009_session_id"], ref["event_id"])
        event = all_events.get(key)
        if event is None:
            errors.append("P019 P009 event reference is missing from raw evidence")
            continue
        expected_type = EVENT_TYPES[ref["purpose"]]
        if expected_type is not None and event.get("event_type") != expected_type:
            errors.append("P009 event type does not match its P019 evidence purpose")
        if event.get("source") not in PHYSICAL_SOURCES:
            errors.append("simulated, mock, or CI P009 event cannot support hardware acceptance")
        purposes[ref["purpose"]] += 1
        referenced_events.append(event)
    missing_purposes = sorted(REQUIRED_P009_PURPOSES - set(purposes))
    if directories and missing_purposes:
        errors.append("P009 raw evidence is missing required event classes: " + ", ".join(missing_purposes))
    if not directories:
        errors.append("P009 raw evidence directories were not supplied")
    return {
        "status": "PASS" if not errors and directories else "FAIL" if errors and directories else "PENDING",
        "packages_checked": len(packages),
        "events_checked": len(referenced_events),
        "purpose_counts": dict(sorted(purposes.items())),
        "replay_statuses": sorted(replay_statuses),
        "missing_purposes": missing_purposes,
        "issues": sorted(set(errors)),
        "hardware_acceptance": "NOT_ESTABLISHED",
    }


def _inspect_p018_export(session: dict[str, Any], export_dir: Path | None) -> dict[str, Any]:
    reference = session["p018_export"]
    if export_dir is None:
        if reference.get("status") == "EXPORT_BLOCKED_BY_PRIVACY":
            return {"status": "BLOCKED", "issues": ["EXPORT_BLOCKED_BY_PRIVACY; preserve raw evidence and retain P018 privacy filters"], "hardware_evidence_accepted": "NOT_ESTABLISHED"}
        return {"status": "PENDING", "issues": ["sanitized export directory not supplied"], "hardware_evidence_accepted": "NOT_ESTABLISHED"}
    try:
        checked = p018_validate_export.validate_bundle(export_dir)
        manifest_path = export_dir / "manifest.json"
        manifest = p018_validate_export.strict_json(_safe_read(manifest_path, 256 * 1024), "P018 manifest")
        manifest_hash = _sha256(_safe_read(manifest_path, 256 * 1024))
        metadata = manifest["source_metadata"]
        issues: list[str] = []
        if reference.get("status") != "VALID":
            issues.append("P019 export reference does not record VALID status")
        if reference.get("manifest_sha256") != manifest_hash:
            issues.append("P018 sanitized manifest hash does not match its P019 cross-reference")
        if reference.get("source_commit_sha") != metadata.get("source_commit_sha") or metadata.get("source_commit_sha") != session["candidate"].get("source_commit_sha"):
            issues.append("P018 export source identity differs from the tested development candidate")
        if manifest.get("hardware_evidence_accepted") != "NOT_ESTABLISHED":
            issues.append("P018 export cannot claim hardware acceptance")
        return {"status": "PASS" if not issues and checked.get("validation") == "VALID" else "FAIL", "issues": issues, "manifest_sha256": manifest_hash, "files_checked": checked.get("files_checked"), "hardware_evidence_accepted": checked.get("hardware_evidence_accepted")}
    except (p018_validate_export.ExportValidationError, p009_evidence.EvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
        return {"status": "FAIL", "issues": [f"P018 export rejected: {type(exc).__name__}"], "hardware_evidence_accepted": "NOT_ESTABLISHED"}


def _latency_summary(records: list[dict[str, Any]], route: str) -> dict[str, Any]:
    values = []
    counts: Counter[str] = Counter()
    for record in records:
        if record.get("route") != route:
            continue
        probe = record.get("probe", {})
        if not isinstance(probe, dict) or not isinstance(probe.get("result"), str):
            continue
        counts[probe["result"]] += 1
        value = probe.get("elapsed_ms")
        if probe["result"] == "AUTHENTICATED_SUCCESS" and type(value) in (int, float) and value >= 0:
            values.append(float(value))
    values.sort()
    if values:
        middle = len(values) // 2
        median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
        p25 = values[round((len(values) - 1) * 0.25)]
        p75 = values[round((len(values) - 1) * 0.75)]
    else:
        median = p25 = p75 = None
    return {"attempted": sum(counts.values()), "authenticated_successes": counts.get("AUTHENTICATED_SUCCESS", 0), "authenticated_failures": sum(value for key, value in counts.items() if key != "AUTHENTICATED_SUCCESS"), "outcomes": dict(sorted(counts.items())), "successful_latency_ms": {"n": len(values), "median": median, "p25": p25, "p75": p75, "min": min(values) if values else None, "max": max(values) if values else None}}


def _duration_seconds(start_text: str, end_text: str) -> int:
    start = p012_common.parse_utc(start_text)
    end = p012_common.parse_utc(end_text)
    if not start or not end or end < start:
        return 0
    return int((end - start).total_seconds())


def analyze_session(session: dict[str, Any], protocol: dict[str, Any], p012_protocol: dict[str, Any], p009_dirs: list[Path] | None = None, export_dir: Path | None = None) -> dict[str, Any]:
    validation_issues = validate_session(session, protocol, p012_protocol)
    p012_report = p012_analyze.build_report(session.get("trial_records", []), validation_issues, p012_protocol, source_sha=session.get("source_commit_sha"))
    p009_review = _inspect_p009(session, p009_dirs or [])
    export_review = _inspect_p018_export(session, export_dir)
    prereq_by_id = {item.get("gate_id"): item for item in session.get("prerequisites", []) if isinstance(item, dict)}
    gates: list[dict[str, Any]] = []
    reasons: list[str] = []
    all_prerequisites_pass = True
    provenance_problem = False
    for gate_id in protocol["prerequisite_gates"]:
        gate = prereq_by_id.get(gate_id, {"status": "NOT_ASSESSED", "source_class": "UNASSIGNED", "reason": "gate is missing"})
        status, reason = _physical_status(gate)
        gates.append({"gate_id": gate_id, "status": status, "reason": reason, "provenance": gate.get("source_class", "UNASSIGNED")})
        if status not in {"PASS", "NOT_APPLICABLE"}:
            all_prerequisites_pass = False
        if status == "BLOCKED":
            reasons.append("PREREQUISITE_BLOCKED:" + gate_id)
        if gate_id in {"p010_exact_ldid_provenance", "development_candidate_provenance", "installed_candidate_identity"} and status != "PASS":
            provenance_problem = True

    p009_good = p009_review["status"] == "PASS" and session["p009_evidence"].get("status") == "VALIDATED" and session["p009_evidence"].get("validation_status") == "PASS" and session["p009_evidence"].get("replay_status") in {"PASS", "WARNINGS"}
    p009_status = "PASS" if p009_good else "BLOCKED" if p009_review["status"] == "FAIL" else "PENDING"
    gates.append({"gate_id": "p009_raw_evidence", "status": p009_status, "reason": "; ".join(p009_review["issues"]) if p009_review["issues"] else "P009 v1 structure, hashes, replay, source classes, and event references checked", "provenance": "P009_V1_RAW"})
    export_good = export_review["status"] == "PASS"
    gates.append({"gate_id": "p018_sanitized_export", "status": "PASS" if export_good else "BLOCKED" if export_review["status"] == "FAIL" or session["p018_export"].get("status") == "EXPORT_BLOCKED_BY_PRIVACY" else "PENDING", "reason": "; ".join(export_review["issues"]) if export_review["issues"] else "P018 validator passed; derivative remains distinct from raw P009 evidence", "provenance": "P018_SANITIZED_DERIVATIVE"})
    review = session["review"]
    review_good = bool(
        review.get("status") == "REVIEWED" and review.get("decision") == "ACCEPT" and review.get("independent") is True
        and review.get("reviewer_id") and review.get("operator_id") and review.get("reviewer_id") != review.get("operator_id")
        and p009_good and review.get("reviewed_p009_session_sha256") in {item.get("session_sha256") for item in session["p009_evidence"]["packages"]}
    )
    gates.append({"gate_id": "independent_evidence_review", "status": "PASS" if review_good else "BLOCKED" if review.get("status") == "REJECTED" or review.get("decision") == "REJECT" else "PENDING", "reason": "independent review record names a validated P009 source hash" if review_good else "independent review of raw P009 provenance and safety is not established", "provenance": "HUMAN_REVIEW_RECORD"})

    trial_origins = {item.get("evidence_origin") for item in session.get("trial_records", []) if isinstance(item, dict)}
    cycle_origins = {item.get("source_class") for item in session.get("bounded_cycles", []) if isinstance(item, dict)}
    if (trial_origins | cycle_origins) & FORBIDDEN_ACCEPTANCE_SOURCES:
        reasons.append("SIMULATED_EVIDENCE_CANNOT_SATISFY_HARDWARE_ACCEPTANCE")
        provenance_problem = True
    if (trial_origins | cycle_origins) - PHYSICAL_SOURCES and (session.get("trial_records") or session.get("bounded_cycles")):
        reasons.append("MISSING_PHYSICAL_SOURCE_PROVENANCE")
        provenance_problem = True

    cycles = session.get("bounded_cycles", [])
    p012_release_failures = sum(1 for item in session.get("trial_records", []) if item.get("state", {}).get("assertion_release_result") == "FAILURE")
    release_failures = sum(1 for item in cycles if item.get("release") == "FAILED") + p012_release_failures
    successful_cycles = sum(1 for item in cycles if item.get("acquisition") == "CONFIRMED" and item.get("release") == "CONFIRMED" and item.get("cleanup_state") == "SAFE" and item.get("assertion_duration_seconds") == 180 and item.get("duration_method") != "UNKNOWN" and item.get("duration_timebase_id") and item.get("duration_uncertainty_ms") is not None)
    confirmed_releases = sum(1 for item in cycles if item.get("release") == "CONFIRMED")
    p012_confirmed_releases = sum(1 for item in session.get("trial_records", []) if item.get("state", {}).get("assertion_release_result") == "SUCCESS")
    unexpected_exits = sum(1 for item in cycles if item.get("daemon_exit") == "UNEXPECTED")
    unexpected_restarts = sum(1 for item in cycles if item.get("unexpected_restart") is True)
    all_probe_records = session.get("trial_records", [])
    lan = _latency_summary(all_probe_records, "LAN")
    tailscale = _latency_summary(all_probe_records, "TAILSCALE")
    resource_counts = Counter((item.get("field"), item.get("availability")) for item in session.get("resource_observations", []) if isinstance(item, dict))
    for cycle in cycles:
        resource_counts[("battery_api", cycle.get("battery_api_state"))] += 1
        resource_counts[("thermal_api", cycle.get("thermal_api_state"))] += 1
        if cycle.get("battery_operator_state") == "DOCUMENTED_SAFE":
            resource_counts[("battery_operator", "DOCUMENTED")] += 1
        if cycle.get("thermal_operator_state") == "DOCUMENTED_SAFE":
            resource_counts[("thermal_operator", "DOCUMENTED")] += 1
    observation_seconds = sum(_duration_seconds(item.get("trial_started_at_utc", ""), item.get("trial_ended_at_utc", "")) for item in all_probe_records)
    observation_seconds += sum(_duration_seconds(item.get("started_at_utc", ""), item.get("ended_at_utc", "")) for item in cycles if item.get("attended") is True)
    counts = p012_report["counts"]
    metrics = {
        "planned_trials": 24,
        "attempted_trials": counts["attempted_probes"],
        "valid_trials": counts["valid_trials"],
        "invalid_trials": counts["invalid_trials"],
        "incomplete_trials": counts["incomplete_trials"],
        "interrupted_trials": counts["interrupted_trials"],
        "successful_bounded_holds": successful_cycles,
        "confirmed_releases": confirmed_releases,
        "p012_confirmed_releases": p012_confirmed_releases,
        "p012_release_failures": p012_release_failures,
        "release_failures": release_failures,
        "unexpected_daemon_exits": unexpected_exits,
        "unexpected_restarts": unexpected_restarts,
        "lan_authenticated_successes": lan["authenticated_successes"],
        "lan_authenticated_failures": lan["authenticated_failures"],
        "tailscale_authenticated_successes": tailscale["authenticated_successes"],
        "tailscale_authenticated_failures": tailscale["authenticated_failures"],
        "supervised_observation_seconds": observation_seconds,
        "resource_availability": {
            "battery_api_available": sum(v for (k, state), v in resource_counts.items() if k in {"battery_percent", "battery_api"} and state == "AVAILABLE"),
            "battery_api_unavailable": sum(v for (k, state), v in resource_counts.items() if k in {"battery_percent", "battery_api"} and state == "UNAVAILABLE"),
            "thermal_api_available": sum(v for (k, state), v in resource_counts.items() if k in {"thermal_state", "thermal_api"} and state == "AVAILABLE"),
            "thermal_api_unavailable": sum(v for (k, state), v in resource_counts.items() if k in {"thermal_state", "thermal_api"} and state == "UNAVAILABLE"),
            "operator_observations": sum(v for (k, _state), v in resource_counts.items() if k in {"battery_percent", "charging_state", "battery_health", "thermal_state", "temperature", "battery_operator", "thermal_operator"} and k not in {"battery_api", "thermal_api"}),
        },
        "p012_comparisons": p012_report["comparisons"],
        "lan": lan,
        "tailscale": tailscale,
        "charging_state_categories": sorted({item.get("charging_state") for item in cycles if item.get("charging_state") is not None}),
        "p009_evidence_issues": p009_review["issues"],
        "p018_export_issues": export_review["issues"],
        "protocol_deviations": len(session.get("protocol_deviations", [])),
        "missing_p009_evidence_purposes": p009_review["missing_purposes"],
        "remaining_acceptance_gates": [gate["gate_id"] for gate in gates if gate["status"] not in {"PASS", "NOT_APPLICABLE"}],
    }

    stop_incidents = [item for item in session.get("incidents", []) if item.get("severity") == "STOP"]
    open_safety = [item for item in session.get("incidents", []) if item.get("severity") in {"STOP", "SAFETY_REVIEW"} and item.get("disposition") not in {"REVIEWED", "CLOSED"}]
    unsafe_trials = [item for item in all_probe_records if item.get("probe", {}).get("result") == "HOST_KEY_FAILURE" or (item.get("interrupted") is True and item.get("state", {}).get("assertion_state") in {"UNKNOWN", "ACTIVE"})]
    unsafe_cycles = [item for item in cycles if item.get("release") == "FAILED" or item.get("cleanup_state") in {"UNRESOLVED", "CORRUPT"} or item.get("unexpected_restart") is True or item.get("daemon_exit") == "UNEXPECTED" or item.get("battery_operator_state") == "CONCERN" or item.get("thermal_operator_state") == "CONCERN" or (type(item.get("assertion_duration_seconds")) is int and item["assertion_duration_seconds"] > 300)]
    unsafe_supervision = session.get("supervision", {}).get("attendance") == "ABSENT" or session.get("supervision", {}).get("independent_recovery") == "UNAVAILABLE"
    all_data = counts["records"] == 24 and counts["valid_trials"] == 24 and counts["invalid_trials"] == 0 and counts["incomplete_trials"] == 0 and counts["interrupted_trials"] == 0 and len(cycles) == 12 and successful_cycles == 12
    confounded = any(item.get("outcome") in {"INCONCLUSIVE", "NOT_IDENTIFIABLE", "INSUFFICIENT_DATA"} for item in p012_report["comparisons"])
    if stop_incidents or unsafe_trials or unsafe_cycles or unsafe_supervision or release_failures or unexpected_exits or unexpected_restarts or open_safety or session.get("p009_evidence", {}).get("replay_status") == "FAIL":
        status = "FAILED_SAFETY"
        reasons.append("SAFETY_STOP_OR_CLEANUP_FAILURE_REQUIRES_MANUAL_REVIEW")
    elif validation_issues:
        status = "INCOMPLETE"
        reasons.extend("SESSION_VALIDATION:" + item for item in validation_issues)
    elif not session.get("trial_records") and not cycles:
        if (
            session.get("session_state") == "NOT_STARTED"
            and session.get("candidate", {}).get("artifact_role") == "UNASSIGNED"
            and not session.get("operator_confirmations")
            and all(item.get("status") == "NOT_ASSESSED" for item in prereq_by_id.values())
        ):
            status = "NOT_STARTED"
            reasons.append("NO_SESSION_DATA_COLLECTED")
        elif all_prerequisites_pass and not provenance_problem:
            status = "READY_FOR_ATTENDED_TEST"
        else:
            status = "PREREQUISITES_BLOCKED"
            reasons.append("REQUIRED_PREREQUISITES_NOT_SATISFIED")
    elif (trial_origins | cycle_origins) & FORBIDDEN_ACCEPTANCE_SOURCES:
        status = "PREREQUISITES_BLOCKED"
    elif not all_data:
        status = "IN_PROGRESS" if session.get("session_state") == "IN_PROGRESS" else "INCOMPLETE"
        reasons.append("REGISTERED_TRIAL_OR_BOUNDED_CYCLE_DENOMINATORS_ARE_INCOMPLETE")
    elif confounded:
        status = "INCONCLUSIVE"
        reasons.append("ONE_OR_MORE_P012_COMPARISONS_ARE_INCONCLUSIVE")
    elif not all_prerequisites_pass or not p009_good or not export_good or not review_good:
        status = "EVIDENCE_REVIEW_PENDING"
        reasons.append("RAW_EVIDENCE_EXPORT_OR_INDEPENDENT_REVIEW_GATE_REMAINS_OPEN")
    else:
        status = "ACCEPTED_FOR_TESTED_SCOPE"

    if p009_review["status"] == "FAIL" or export_review["status"] == "FAIL":
        reasons.append("EVIDENCE_INTEGRITY_OR_PRIVACY_VALIDATION_FAILED")
        if status not in {"FAILED_SAFETY", "INCOMPLETE"}:
            status = "INCONCLUSIVE"
    p020 = "BLOCKED_BY_SAFETY" if stop_incidents or unsafe_trials or unsafe_cycles or unsafe_supervision or release_failures else "BLOCKED_BY_PROVENANCE" if provenance_problem else "BLOCKED_PENDING_PHYSICAL_ACCEPTANCE"
    if status == "ACCEPTED_FOR_TESTED_SCOPE":
        p020 = "ASSESSABLE_FROM_CLOUD"
    return {
        "result_version": 1,
        "protocol_id": "P019",
        "protocol_version": 1,
        "session_id": session.get("session_id", "invalid-session"),
        "source_commit_sha": session.get("source_commit_sha", "0" * 40),
        "status": status,
        "reason_codes": sorted(set(reasons)),
        "gates": gates,
        "tested_scope": ["Only populated after all P019 registered measurements and independent evidence review pass; scope must name exact candidate, conditions, routes, and bounded behavior." ] if status == "ACCEPTED_FOR_TESTED_SCOPE" else [],
        "excluded_scope": ["24/7 or continuous uptime", "automatic restart", "reboot persistence", "crash recovery", "unattended schedule execution", "causal sleep prevention", "conditions or routes not tested"],
        "metrics": metrics,
        "p020_readiness": p020,
        "hardware_acceptance": "NOT_ESTABLISHED" if status != "ACCEPTED_FOR_TESTED_SCOPE" else "ACCEPTED_FOR_TESTED_SCOPE",
        "cloud_status": "P019_CLOUD_COMPLETE_HARDWARE_ACCEPTANCE_PENDING",
        "provenance_limits": ["P009 hashes establish consistency, not identity or truth.", "P018 export is a sanitized derivative and its validator checks structure and privacy, not empirical authenticity.", "Human review records are claims that require independent provenance review.", "SIMULATED, MOCK, and CI records never satisfy hardware acceptance.", "Finite attended trials do not imply 24/7 reliability."],
        "analysis": p012_report,
        "p009_review": p009_review,
        "p018_export_review": export_review,
    }


def _write_new_file(path: Path, content: bytes) -> None:
    if path.is_symlink() or path.exists():
        raise P019Error("output must be a new path; existing files are never overwritten")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise P019Error("output parent must be an existing real directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise P019Error("output already exists") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def render_markdown(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    lines = [
        "# P019 Session Report", "",
        f"- Session: `{result['session_id']}`",
        f"- Source: `{result['source_commit_sha']}`",
        f"- Decision: **{result['status']}**",
        f"- Hardware acceptance: **{result['hardware_acceptance']}**",
        f"- P020 readiness: **{result['p020_readiness']}**",
        "",
        "## Trial counts", "",
        f"Planned {metrics['planned_trials']}; attempted {metrics['attempted_trials']}; valid {metrics['valid_trials']}; invalid {metrics['invalid_trials']}; incomplete {metrics['incomplete_trials']}; interrupted {metrics['interrupted_trials']}.",
        "",
        "## Bounded reliability", "",
        f"Successful bounded holds: {metrics['successful_bounded_holds']}/12; endurance-cycle releases confirmed: {metrics['confirmed_releases']}/12; P012 release confirmations: {metrics['p012_confirmed_releases']}; total release failures: {metrics['release_failures']}; unexpected daemon exits: {metrics['unexpected_daemon_exits']}; unexpected restarts: {metrics['unexpected_restarts']}.",
        f"Aggregate attended observation time: {metrics['supervised_observation_seconds']} seconds. Separate short sessions are not continuous uptime.",
        "",
        "## Network routes", "",
        "| Route | Attempts | Authenticated successes | Failed outcomes | Median successful latency (ms) |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, key in (("LAN", "lan"), ("Tailscale", "tailscale")):
        value = metrics[key]
        latency = value["successful_latency_ms"]["median"]
        lines.append(f"| {name} | {value['attempted']} | {value['authenticated_successes']} | {value['authenticated_failures']} | {latency if latency is not None else 'n/a'} |")
    lines.extend(["", "## Acceptance gates", "", "| Gate | State | Provenance | Reason |", "|---|---|---|---|"])
    for gate in result["gates"]:
        lines.append(f"| {gate['gate_id']} | {gate['status']} | {gate['provenance']} | {gate['reason']} |")
    lines.extend(["", "## Limits", "", *["- " + item for item in result["provenance_limits"]], ""])
    return "\n".join(lines)


def _read_session(path: Path, protocol: dict[str, Any], p012_protocol: dict[str, Any]) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise P019Error("session must be a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="print the preregistered offline phase and observation plan")
    plan.add_argument("--format", choices=("json", "markdown"), default="json")
    plan.set_defaults(function=command_plan)
    init = sub.add_parser("init", help="write a new host-side session template to a new path")
    init.add_argument("--session-id", required=True)
    init.add_argument("--source-commit-sha", required=True)
    init.add_argument("--output", required=True)
    init.set_defaults(function=command_init)
    confirm = sub.add_parser("record-confirmation", help="write an operator-reported confirmation as a new session copy")
    confirm.add_argument("--session", required=True)
    confirm.add_argument("--key", required=True)
    confirm.add_argument("--value", required=True, choices=("CONFIRMED", "DECLINED", "UNKNOWN"))
    confirm.add_argument("--operator-id", required=True)
    confirm.add_argument("--note", default="")
    confirm.add_argument("--output", required=True)
    confirm.set_defaults(function=command_confirmation)
    for name, help_text in (("validate", "validate a local session and optional raw/export evidence"), ("analyze", "analyze a session offline using the P012 analyzer"), ("report", "render a deterministic acceptance report")):
        item = sub.add_parser(name, help=help_text)
        item.add_argument("--session", required=True)
        item.add_argument("--p009-directory", action="append", default=[], help="raw P009 v1 evidence directory; repeat for each package")
        item.add_argument("--export-directory", help="P018 sanitized export derivative for read-only validation")
        item.add_argument("--format", choices=("json", "markdown"), default="json")
        item.set_defaults(function=command_session)
    return parser


def command_plan(args: argparse.Namespace) -> int:
    protocol, p012_protocol, issues = load_protocol()
    if issues:
        raise P019Error("protocol validation failed: " + "; ".join(issues))
    plan = build_plan(protocol, p012_protocol)
    if args.format == "json":
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print(f"# P019 Plan v{plan['protocol_version']}\n\nProtocol SHA-256: `{plan['protocol_sha256']}`\n\nCloud only: yes. Device actions started: no.\n")
        for item in plan["phase_entry_gates"]:
            print(f"- Phase {item['phase']} — {item['name']}: {item['entry_gate']}")
        print(f"\nP012 trials: {plan['p012_matrix']['planned_probe_trials']}; bounded cycles: {plan['repeated_bounded_sessions']['planned_bounded_cycles']}.")
    return 0


def command_init(args: argparse.Namespace) -> int:
    protocol, p012_protocol, issues = load_protocol()
    if issues:
        raise P019Error("protocol validation failed: " + "; ".join(issues))
    session = create_session(args.session_id, args.source_commit_sha, protocol)
    issues = validate_session(session, protocol, p012_protocol)
    if issues:
        raise P019Error("generated session template is invalid: " + "; ".join(issues))
    _write_new_file(Path(args.output), _json_bytes(session))
    print(json.dumps({"created": True, "path": str(Path(args.output)), "session_id": args.session_id, "device_access": "NOT_PERFORMED", "hardware_acceptance": "NOT_ESTABLISHED"}, sort_keys=True))
    return 0


def command_confirmation(args: argparse.Namespace) -> int:
    protocol, p012_protocol, issues = load_protocol()
    if issues:
        raise P019Error("protocol validation failed: " + "; ".join(issues))
    session = _read_session(Path(args.session), protocol, p012_protocol)
    if not SAFE_ID.fullmatch(args.operator_id):
        raise P019Error("operator ID must be a non-sensitive stable identifier")
    if len(args.note) > 500:
        raise P019Error("confirmation note exceeds 500 characters")
    confirmation = {
        "confirmation_id": f"{session['session_id']}.{len(session['operator_confirmations']) + 1}",
        "key": args.key,
        "value": args.value,
        "recorded_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "operator_id": args.operator_id,
        "source_class": "OPERATOR_RECORDED",
        "timebase_id": "host-clock-unreconciled",
        "uncertainty_ms": None,
        "note": args.note,
    }
    session["operator_confirmations"].append(confirmation)
    validation_issues = validate_session(session, protocol, p012_protocol)
    if validation_issues:
        raise P019Error("session validation failed: " + "; ".join(validation_issues))
    _write_new_file(Path(args.output), _json_bytes(session))
    print(json.dumps({"recorded": True, "source_class": "OPERATOR_RECORDED", "confirmation_is_acceptance": False, "output": str(Path(args.output))}, sort_keys=True))
    return 0


def command_session(args: argparse.Namespace) -> int:
    protocol, p012_protocol, protocol_issues = load_protocol()
    if protocol_issues:
        raise P019Error("protocol validation failed: " + "; ".join(protocol_issues))
    session = _read_session(Path(args.session), protocol, p012_protocol)
    session_issues = validate_session(session, protocol, p012_protocol)
    if args.command == "validate":
        external_p009 = _inspect_p009(session, [Path(value) for value in args.p009_directory])
        external_p018 = _inspect_p018_export(session, Path(args.export_directory) if args.export_directory else None)
        output = {
            "session_id": session.get("session_id"),
            "protocol_validation": "PASS",
            "session_validation": "PASS" if not session_issues else "FAIL",
            "session_issues": session_issues,
            "p009_raw_validation": external_p009,
            "p018_export_validation": external_p018,
            "hardware_acceptance": "NOT_ESTABLISHED",
            "device_actions": "NOT_PERFORMED",
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0 if not session_issues and external_p009["status"] != "FAIL" and external_p018["status"] != "FAIL" else 2
    result = analyze_session(session, protocol, p012_protocol, [Path(value) for value in args.p009_directory], Path(args.export_directory) if args.export_directory else None)
    if args.command == "analyze" or args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_markdown(result), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.function(args)
    except (P019Error, p012_common.P012Error, p009_evidence.EvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"P019 error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
