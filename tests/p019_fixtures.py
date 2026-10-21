"""Deterministic P019 fixtures. Every generated observation is SIMULATED or MOCK."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import p019_session  # noqa: E402
from p012_fixtures import all_success_records  # noqa: E402


FIXTURE_CASES = [
    "all_prerequisites_satisfied",
    "missing_p011_package_acceptance",
    "missing_exact_ldid_provenance",
    "package_hash_mismatch",
    "signed_candidate_device_validation_pending",
    "incorrect_binary_build_identity",
    "missing_installed_runtime",
    "p013_launchd_compatibility_unverified",
    "p014_cleanup_unresolved",
    "p014_recovery_journal_corruption",
    "unsupported_automatic_restart",
    "p015_unattended_operation_denial",
    "p016_battery_unavailable",
    "p016_thermal_unavailable",
    "p017_schedule_execution_unauthorized",
    "successful_bounded_acquisition_release",
    "assertion_release_failure",
    "unexpected_daemon_exit",
    "interrupted_trial",
    "missing_screen_lock_evidence",
    "missing_independent_observer",
    "lan_only_success",
    "tailscale_only_success",
    "authentication_failure",
    "ssh_timeout",
    "host_key_failure",
    "invalid_observer_timestamps",
    "clock_disagreement",
    "cross_timebase_uncertainty",
    "quiet_interval_contamination",
    "invalid_sample_count",
    "duplicate_trial_ids",
    "incorrect_source_provenance",
    "p009_malformed_event",
    "tampered_p009_evidence_file",
    "missing_p009_manifest_member",
    "privacy_filtered_export",
    "export_privacy_rejection",
    "unreviewed_evidence",
    "simulated_session_cannot_claim_acceptance",
    "report_after_incomplete_session",
    "unsafe_cancellation",
    "no_automatic_ssh_probing",
    "no_launchd_mutation",
    "no_iokit_acquisition",
    "no_unattended_execution",
    "no_auto_install_or_rollback",
    "no_fabricated_reliability_claim",
]


def make_session(source_sha: str = "a" * 40, *, full: bool = False) -> dict[str, Any]:
    protocol, _p012, issues = p019_session.load_protocol()
    if issues:
        raise AssertionError(issues)
    session = p019_session.create_session("p019-simulated-case", source_sha, protocol)
    session["evidence_class"] = "SIMULATED"
    if full:
        session["session_state"] = "ENDED"
        session["trial_records"] = all_success_records()
        session["bounded_cycles"] = make_cycles()
    return session


def make_candidate(session: dict[str, Any]) -> None:
    session["candidate"] = {
        "artifact_role": "DEVELOPMENT_CANDIDATE",
        "source_commit_sha": session["source_commit_sha"],
        "build_id": "mock-build-p019",
        "package_identifier": "com.ioscaffeinate.cli",
        "package_version": "0.2.0~dev-1",
        "package_sha256": "d" * 64,
        "cli_binary_sha256": "e" * 64,
        "daemon_binary_sha256": "f" * 64,
        "profile_id": p019_session.PROFILE_ID,
        "profile_sha256": p019_session.PROFILE_SHA256,
        "ldid_version": p019_session.RECORDED_LDID_VERSION,
        "ldid_sha256": p019_session.RECORDED_LDID_SHA256,
        "signature_validation": "PASS",
        "installed_paths_verified": True,
        "rollback_artifact_sha256": "c" * 64,
    }


def pass_prerequisites(session: dict[str, Any], source_class: str = "MOCK") -> None:
    for item in session["prerequisites"]:
        if item["gate_id"] in {"p013_launchd_mutation_compatibility", "p014_automatic_restart_executor", "p015_unattended_server_mode"}:
            item.update(status="NOT_APPLICABLE", source_class="CI", evidence_ref="ci://policy-limit", reason="Feature remains outside the P019 tested scope.")
        else:
            item.update(status="PASS", source_class=source_class, evidence_ref="ci://simulated-prerequisite", reason="Deterministic fixture only.")


def make_cycles(source_class: str = "SIMULATED") -> list[dict[str, Any]]:
    cycles = []
    for period in (1, 2, 3):
        day = datetime(2037, 1, period, 10, 0, tzinfo=timezone.utc)
        for cycle_number in (1, 2, 3, 4):
            start = day + timedelta(minutes=10 * (cycle_number - 1))
            end = start + timedelta(seconds=180)
            cycles.append({
                "cycle_id": f"sim-p{period}-c{cycle_number}",
                "observation_period": period,
                "cycle_number": cycle_number,
                "started_at_utc": start.isoformat().replace("+00:00", "Z"),
                "ended_at_utc": end.isoformat().replace("+00:00", "Z"),
                "source_class": source_class,
                "observer_timebase_id": f"simulated-host-boot-{period}",
                "observer_monotonic_elapsed_seconds": float(780 * (cycle_number - 1)),
                "timestamp_uncertainty_ms": 1000,
                "device_timebase_id": f"simulated-device-boot-{period}",
                "device_boot_identity": f"simulated-device-boot-{period}",
                "device_monotonic_elapsed_seconds": float(780 * (cycle_number - 1)),
                "device_clock_uncertainty_ms": 1000,
                "duration_method": "DEVICE_MONOTONIC",
                "duration_timebase_id": f"simulated-device-boot-{period}",
                "duration_uncertainty_ms": 1000,
                "attended": True,
                "assertion_duration_seconds": 180,
                "acquisition": "CONFIRMED",
                "release": "CONFIRMED",
                "daemon_exit": "EXPECTED",
                "unexpected_restart": False,
                "cleanup_state": "SAFE",
                "rest_before_seconds": 0 if cycle_number == 1 else 300,
                "charging_state": "UNKNOWN",
                "battery_api_state": "UNAVAILABLE",
                "battery_operator_state": "DOCUMENTED_SAFE",
                "thermal_api_state": "UNAVAILABLE",
                "thermal_operator_state": "DOCUMENTED_SAFE",
                "deviation_ids": [],
            })
    return cycles
