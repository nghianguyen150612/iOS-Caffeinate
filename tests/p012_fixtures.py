"""Deterministic synthetic P012 records; never physical-device evidence."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from p012_common import CONFIRMATION_KEYS, CONDITIONS, load_json  # noqa: E402

PROTOCOL = load_json(ROOT / "experiments/p012/protocol-v1.json")


def _fmt(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_trial(
    condition: str = "A",
    route: str = "LAN",
    repetition: int = 1,
    *,
    result: str = "AUTHENTICATED_SUCCESS",
    quiet_seconds: int = 120,
    screen: str = "LOCKED",
    assertion_state: str | None = None,
    operator_confirmations: dict[str, bool | None] | None = None,
    contaminated: bool = False,
    quiet_confirmed: bool = True,
    clock_discontinuity: bool = False,
    success_latency_ms: int | float = 12.0,
) -> dict[str, Any]:
    condition_index = PROTOCOL["design"]["condition_order_by_repetition"][repetition - 1].index(condition) + 1
    route_index = PROTOCOL["design"]["route_order_by_repetition"][repetition - 1].index(route) + 1
    base = datetime(2037, 1, 1, tzinfo=timezone.utc) + timedelta(days=(repetition - 1) * 2 + condition_index / 10 + route_index / 100)
    start = base.replace(microsecond=0)
    probe_start = start + timedelta(seconds=quiet_seconds)
    latency = float(success_latency_ms)
    probe_end = probe_start + timedelta(milliseconds=latency)
    expected_daemon, expected_assertion = CONDITIONS[condition]
    assertion_state = assertion_state or expected_assertion
    if condition == "C":
        acquire_result, acquire_start, acquired = "SUCCESS", _fmt(start), _fmt(start)
        release_result, release_kind, release_at = "SUCCESS", "EXPIRED", _fmt(start + timedelta(seconds=178))
        actual_hold = 180
        trial_end = datetime.fromisoformat(release_at.replace("Z", "+00:00"))
    elif condition == "D":
        acquire_result, acquire_start, acquired = "NOT_APPLICABLE", None, None
        release_result, release_kind = "SUCCESS", "EXPIRED"
        release_at = _fmt(start - timedelta(seconds=1))
        actual_hold = 180
        trial_end = probe_end
    else:
        acquire_result, acquire_start, acquired = "NOT_APPLICABLE", None, None
        release_result, release_kind, release_at, actual_hold = "NOT_APPLICABLE", "NONE", None, None
        trial_end = probe_end
    quiet_end = probe_start
    device_clock = "synthetic-utc"
    host_clock = "synthetic-utc"
    p_started = probe_start
    p_ended = probe_end
    p_wall_elapsed = latency + (30_000 if clock_discontinuity else 0)
    if result == "AUTHENTICATED_SUCCESS":
        authentication, authenticated, exit_code = "SUCCESS", True, 0
    elif result == "AUTHENTICATION_FAILURE":
        authentication, authenticated, exit_code = "FAILURE", False, 255
    elif result == "REMOTE_COMMAND_FAILURE":
        authentication, authenticated, exit_code = "SUCCESS", True, 1
    elif result in {"CONNECTION_REFUSED", "HOST_KEY_FAILURE", "TRANSPORT_ERROR"}:
        authentication, authenticated, exit_code = "NOT_ESTABLISHED", None, 255
    elif result == "PROBE_TIMEOUT":
        authentication, authenticated, exit_code = "NOT_ESTABLISHED", None, None
    else:
        authentication, authenticated, exit_code = "UNKNOWN", None, None
    probe = {
        "probe_version": 1,
        "trial_id": f"sim-r{repetition}-{condition}-{route.lower()}",
        "condition_id": condition,
        "repetition": repetition,
        "route": route,
        "target_id": "synthetic-ipad",
        "result": result,
        "authentication": authentication,
        "authenticated": authenticated,
        "ssh_exit_code": exit_code,
        "started_at_utc": _fmt(p_started),
        "ended_at_utc": _fmt(p_ended),
        "elapsed_ms": latency,
        "wall_elapsed_ms": p_wall_elapsed,
        "clock_discontinuity": clock_discontinuity,
        "timeout_seconds": 8,
        "quiet_interval_seconds": quiet_seconds,
        "quiet_period_confirmed": quiet_confirmed,
        "screen_lock_status": screen,
        "screen_lock_confirmed": screen == "LOCKED",
        "operator_present": True,
        "p011_prerequisites_confirmed": True,
        "physical_recovery_confirmed": True,
        "battery_thermal_approved": True,
        "wifi_association_confirmed": True,
        "route_state_confirmed": True,
        "daemon_state_confirmed": True,
        "assertion_state_confirmed": True,
        "observer_timebase_id": host_clock,
        "timing_uncertainty_ms": 100,
    }
    state = {
        "screen_lock_status": screen,
        "screen_lock_observed_at_utc": _fmt(start),
        "charging_state": "NOT_CHARGING",
        "battery_percent": 80 - repetition,
        "battery_observed_at_utc": _fmt(start),
        "thermal_state": "COOL",
        "thermal_observed_at_utc": _fmt(start),
        "wifi_association": "ASSOCIATED",
        "wifi_profile_id": "synthetic-wifi",
        "lan_route_state": "AVAILABLE",
        "tailscale_route_state": "AVAILABLE",
        "daemon_state": expected_daemon,
        "assertion_state": assertion_state,
        "assertion_duration_seconds": actual_hold,
        "assertion_acquire_result": acquire_result,
        "assertion_acquire_started_at_utc": _fmt(start - timedelta(seconds=2)) if condition == "C" else acquire_start,
        "assertion_acquired_at_utc": _fmt(start - timedelta(seconds=2)) if condition == "C" else acquired,
        "assertion_release_result": release_result,
        "assertion_release_kind": release_kind,
        "assertion_release_confirmed_at_utc": release_at,
        "quiet_start_at_utc": _fmt(start),
        "quiet_end_at_utc": _fmt(quiet_end),
        "quiet_interval_seconds": quiet_seconds,
        "quiet_period_confirmed": quiet_confirmed,
        "quiet_period_contaminated": contaminated,
        "quiet_incoming_probe_count": 1 if contaminated else 0,
        "quiet_operator_interaction_count": 0,
        "elapsed_since_previous_trial_seconds": 900.0,
        "reboot_or_respring_since_previous": False,
    }
    confirmations = {key: True for key in CONFIRMATION_KEYS}
    if operator_confirmations:
        confirmations.update(operator_confirmations)
    return {
        "record_version": 1,
        "evidence_origin": "SIMULATED",
        "trial_id": probe["trial_id"],
        "repetition": repetition,
        "pair_id": f"sim-r{repetition}-{condition}",
        "condition_id": condition,
        "route": route,
        "condition_order_index": condition_index,
        "route_order_index": route_index,
        "trial_started_at_utc": _fmt(start - timedelta(seconds=2) if condition == "C" else start),
        "trial_ended_at_utc": _fmt(trial_end),
        "observer_timebase_id": host_clock,
        "timing_uncertainty_ms": 100,
        "device_timebase_id": device_clock,
        "device_clock_uncertainty_ms": 100,
        "state": state,
        "operator_confirmations": confirmations,
        "probe": probe,
        "interrupted": False,
        "interruption_code": None,
    }


def all_success_records() -> list[dict[str, Any]]:
    records = []
    for repetition in (1, 2, 3):
        for condition in ("A", "B", "C", "D"):
            for route in ("LAN", "TAILSCALE"):
                records.append(make_trial(condition, route, repetition, success_latency_ms=11 + repetition + (condition in {"C", "D"}) * 2))
    return records


def write_all_success_bundle(destination: Path) -> None:
    bundle = {"evidence_origin": "SIMULATED", "scenario": "SIMULATED_ALL_SUCCESS", "records": all_success_records()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(bundle, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Write synthetic test-only P012 input records")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--scenario", choices=("all-success",), default="all-success")
    arguments = parser.parse_args()
    write_all_success_bundle(arguments.destination)
