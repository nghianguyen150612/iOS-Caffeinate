"""Deterministic generated evidence fixtures; every record is synthetic."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "256611b97004f798c7dadd41ff25c8ebf95b6db5"
PACKAGE_SHA = "a" * 64
BINARY_SHA = "b" * 64
BASE = "2026-07-02T12:00:"


def event(event_id: str, sequence: int, event_type: str, seconds: int, details: dict[str, Any] | None = None, source: str = "SIMULATED", timebase: str = "device-clock") -> dict[str, Any]:
    return {
        "event_id": event_id,
        "sequence": sequence,
        "event_type": event_type,
        "timestamp": f"{BASE}{seconds:02d}Z",
        "source": source,
        "timebase_id": timebase,
        "uncertainty_ms": 0,
        "details": details or {},
    }


def make_session() -> dict[str, Any]:
    events = [
        event("preflight", 0, "DEVICE_PREFLIGHT", 0, {"model": "SYNTHETIC iPad mini 2", "ios_version": "12.5.7", "launchd_disabled": True}),
        event("integrity", 1, "PACKAGE_INTEGRITY_CHECK", 1, {"verified": True, "package_sha256": PACKAGE_SHA}),
        event("signature", 2, "SIGNATURE_ACCEPTANCE", 2, {"accepted": True}),
        event("install", 3, "PACKAGE_INSTALL", 3, {"success": True, "package_sha256": PACKAGE_SHA}),
        event("daemon-start", 4, "DAEMON_LAUNCH", 4, {"success": True}),
        event("battery", 5, "BATTERY_OBSERVATION", 5, {"observed": True, "level_percent": 80}),
        event("thermal", 6, "THERMAL_OBSERVATION", 6, {"observed": True, "state": "NORMAL"}),
        event("acquire-attempt", 7, "ASSERTION_ACQUIRE_ATTEMPT", 10),
        event("acquire", 8, "ASSERTION_ACQUIRE_SUCCESS", 11, {"success": True}),
        event("hold", 9, "HOLD_ACTIVE", 12),
        event("screen-lock", 10, "SCREEN_LOCK", 13, {"screen_lock_status": "LOCKED"}),
        event("lan", 11, "LAN_OBSERVATION", 15, {"address": "192.0.2.10", "tcp_22_reachable": True, "ssh_authenticated": True, "latency_ms": 12.5, "screen_lock_status": "LOCKED", "operator_confirmed_screen_state": True, "screen_lock_event_id": "screen-lock", "trial_id": "trial-001"}),
        event("tailscale", 12, "TAILSCALE_OBSERVATION", 16, {"address": "100.64.0.10", "peer_connected": True, "path": "RELAY", "ssh_authenticated": False, "latency_ms": 88.0, "screen_lock_status": "LOCKED", "operator_confirmed_screen_state": True, "screen_lock_event_id": "screen-lock", "trial_id": "trial-001"}),
        event("stop", 13, "EXPLICIT_STOP", 40),
        event("release", 14, "ASSERTION_RELEASE", 41, {"success": True}),
        event("daemon-exit", 15, "DAEMON_EXIT", 42, {"exit_code": 0}),
        event("recovery", 16, "PHYSICAL_RECOVERY", 43, {"success": True}),
        event("rollback", 17, "ROLLBACK", 44, {"success": True}),
        event("remove", 18, "PACKAGE_REMOVAL", 45, {"success": True}),
    ]
    return {
        "schema_version": 1,
        "session_id": "synthetic-session-001",
        "source_commit_sha": COMMIT,
        "build_run": {
            "build_id": "synthetic-build-001",
            "package_identifier": "com.ioscaffeinate.cli",
            "package_version": "0.1.0-1",
            "package_sha256": PACKAGE_SHA,
            "binary_sha256": {"ios-caffeinate": BINARY_SHA, "ios-caffeinated": "c" * 64},
        },
        "device": {"model": "SYNTHETIC iPad mini 2", "ios_version": "12.5.7", "jailbreak_bootstrap": "SYNTHETIC Amethyst/Procursus"},
        "evidence_origin": "SIMULATED",
        "physical_presence_confirmed": False,
        "started_at": f"{BASE}00Z",
        "ended_at": f"{BASE}50Z",
        "clock": {"source": "synthetic UTC clock", "uncertainty_ms": 0},
        "trial": {"trial_id": "trial-001", "authorized_duration_seconds": 60, "attended": True},
        "observations": events,
        "cleanup": {"outcome": "COMPLETE"},
        "unresolved_conditions": [],
        "evidence_files": [],
        "review_status": "REVIEWED",
    }


def write_package(root: Path, session: dict[str, Any], extra_files: dict[str, bytes] | None = None) -> Path:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    files = {"evidence/operator-note.txt": b"SYNTHETIC test-only operator note\n"}
    files.update(extra_files or {})
    refs = []
    for index, (relative, content) in enumerate(sorted(files.items()), start=1):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        suffix = path.suffix.lower()
        media = {".json": "application/json", ".txt": "text/plain", ".csv": "text/csv", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(suffix, "application/octet-stream")
        refs.append({"file_id": f"evidence-{index}", "path": relative, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "media_type": media})
    session["evidence_files"] = refs
    session_raw = (json.dumps(session, indent=2, sort_keys=True) + "\n").encode()
    (root / "session.json").write_bytes(session_raw)
    entries = [{"file_id": "session", "path": "session.json", "size_bytes": len(session_raw), "sha256": hashlib.sha256(session_raw).hexdigest()}]
    entries.extend({"file_id": ref["file_id"], "path": ref["path"], "size_bytes": ref["size_bytes"], "sha256": ref["sha256"]} for ref in refs)
    manifest = {"manifest_version": 1, "files": sorted(entries, key=lambda item: item["path"])}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return root


def build_fixture(root: Path, name: str, origin: str = "SIMULATED") -> Path:
    session = make_session()
    if origin != "SIMULATED":
        session["evidence_origin"] = origin
        session["physical_presence_confirmed"] = True
        for item in session["observations"]:
            if item["event_type"] in {"LAN_OBSERVATION", "TAILSCALE_OBSERVATION"}:
                item["source"] = "EXTERNAL_OBSERVER"
            elif item["event_type"] in {"SCREEN_LOCK", "SCREEN_UNLOCK", "BATTERY_OBSERVATION", "THERMAL_OBSERVATION", "PHYSICAL_RECOVERY"}:
                item["source"] = "OPERATOR_RECORDED"
            else:
                item["source"] = "DEVICE_REPORTED"
    observations = session["observations"]
    by_type = lambda event_type: next((item for item in observations if item["event_type"] == event_type), None)

    if name == "missing_assertion_release":
        observations.remove(by_type("ASSERTION_RELEASE"))
        observations.remove(by_type("DAEMON_EXIT"))
        session["cleanup"]["outcome"] = "UNRESOLVED"
        session["ended_at"] = f"{BASE}50Z"
    elif name == "natural_expiry":
        stop = by_type("EXPLICIT_STOP")
        stop["event_type"] = "NATURAL_EXPIRY"
        stop["event_id"] = "expiry"
    elif name == "release_failure":
        by_type("ASSERTION_RELEASE")["details"]["success"] = False
        session["cleanup"]["outcome"] = "UNRESOLVED"
    elif name == "recovered_release_failure":
        release = by_type("ASSERTION_RELEASE")
        release["timestamp"] = f"{BASE}42Z"
        release["sequence"] += 1
        for item in observations:
            if item["sequence"] > 14 and item["event_id"] != "release":
                item["sequence"] += 1
        observations.append(event("release-retry-1", 14, "ASSERTION_RELEASE", 41, {"success": False}))
        for event_id, seconds in (("daemon-exit", 43), ("recovery", 44), ("rollback", 45), ("remove", 46)):
            next(item for item in observations if item["event_id"] == event_id)["timestamp"] = f"{BASE}{seconds:02d}Z"
    elif name == "invalid_signature_evidence":
        by_type("SIGNATURE_ACCEPTANCE")["details"]["accepted"] = False
    elif name == "missing_signature_evidence":
        observations.remove(by_type("SIGNATURE_ACCEPTANCE"))
    elif name == "locked_screen_lan_failure":
        by_type("LAN_OBSERVATION")["details"]["tcp_22_reachable"] = False
    elif name == "tailscale_failure_despite_lan_success":
        pass
    elif name == "tailscale_relay_path":
        by_type("TAILSCALE_OBSERVATION")["details"]["ssh_authenticated"] = True
    elif name == "missing_operator_confirmation":
        by_type("LAN_OBSERVATION")["details"]["operator_confirmed_screen_state"] = False
    elif name == "missing_battery_observation":
        observations.remove(by_type("BATTERY_OBSERVATION"))
    elif name == "missing_thermal_observation":
        observations.remove(by_type("THERMAL_OBSERVATION"))
    elif name == "device_clock_discrepancy":
        by_type("DAEMON_EXIT")["timestamp"] = f"{BASE}20Z"
    elif name == "overlong_trial":
        session["trial"]["authorized_duration_seconds"] = 30
        by_type("ASSERTION_RELEASE")["timestamp"] = f"{BASE}45Z"
        by_type("DAEMON_EXIT")["timestamp"] = f"{BASE}46Z"
        by_type("PHYSICAL_RECOVERY")["timestamp"] = f"{BASE}47Z"
        by_type("ROLLBACK")["timestamp"] = f"{BASE}48Z"
        by_type("PACKAGE_REMOVAL")["timestamp"] = f"{BASE}49Z"
    elif name == "network_after_unlock":
        unlock = event("screen-unlock", 11, "SCREEN_UNLOCK", 14, {"screen_lock_status": "UNLOCKED"})
        observations.append(unlock)
        for item in observations:
            if item["sequence"] >= 11 and item["event_id"] != "screen-unlock":
                item["sequence"] += 1
    elif name == "invalid_event_ordering":
        by_type("EXPLICIT_STOP")["timestamp"] = f"{BASE}09Z"
    elif name == "missing_recovery":
        observations.remove(by_type("PHYSICAL_RECOVERY"))
    elif name == "restart_during_trial":
        restart = event("daemon-restart", 10, "DAEMON_LAUNCH", 20, {"success": True})
        observations.append(restart)
        for item in observations:
            if item["sequence"] >= 10 and item["event_id"] != "daemon-restart":
                item["sequence"] += 1
    elif name == "unavailable_daemon":
        by_type("DAEMON_LAUNCH")["details"]["success"] = False
    elif name == "incomplete_rollback":
        by_type("ROLLBACK")["details"]["success"] = False
        by_type("PACKAGE_REMOVAL")["details"]["success"] = False
    elif name == "sigterm_cleanup":
        stop = by_type("EXPLICIT_STOP")
        stop["event_id"] = "sigterm"
        stop["event_type"] = "SIGTERM"
    elif name in {"explicit_stop", "valid_simulated_bounded_trial", "locked_screen_lan_success"}:
        pass
    elif name in {"invalid_hashes", "corrupted_json", "path_traversal", "oversized_evidence"}:
        pass
    else:
        raise ValueError(f"unknown P009 fixture: {name}")

    package = write_package(root, session, {"evidence/operator-note.txt": b"SYNTHETIC test-only operator note\n"})
    if name == "invalid_hashes":
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    elif name == "corrupted_json":
        (package / "session.json").write_text("{this is not JSON\n")
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        entry = next(item for item in manifest["files"] if item["path"] == "session.json")
        raw = (package / "session.json").read_bytes()
        entry["size_bytes"] = len(raw)
        entry["sha256"] = hashlib.sha256(raw).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    elif name == "path_traversal":
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["path"] = "../escape.txt"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    elif name == "oversized_evidence":
        package = write_package(package, make_session(), {"evidence/large.bin": b"x" * (2 * 1024 * 1024 + 1)})
    return package
