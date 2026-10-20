#!/usr/bin/env python3
"""One-shot, attended SSH observation for the offline P012 research protocol."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

from p012_common import CONDITIONS, DEFAULT_PROTOCOL, P012Error, load_json, parse_utc, validate_protocol, valid_id

TARGET_RE = re.compile(r"^(?:[A-Za-z0-9._-]+@)?(?:[A-Za-z0-9][A-Za-z0-9.-]{0,252}|\[[0-9A-Fa-f:.]{2,45}\])$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def valid_destination(value: str) -> bool:
    if not TARGET_RE.fullmatch(value) or value.startswith("-"):
        return False
    host = value.rsplit("@", 1)[-1]
    if host.startswith("["):
        return True
    return all(label and len(label) <= 63 and not label.startswith("-") and not label.endswith("-") for label in host.rstrip(".").split("."))


def valid_target_id(value: str) -> bool:
    if not valid_id(value):
        return False
    try:
        ipaddress.ip_address(value)
        return False
    except ValueError:
        return True


def classify_stderr(stderr: str) -> str | None:
    """Classify common SSH errors without retaining or printing the raw log."""
    message = stderr.lower()
    if any(term in message for term in ("host key verification failed", "remote host identification has changed", "host key has changed", "no matching host key type found")):
        return "HOST_KEY_FAILURE"
    if "permission denied" in message or "too many authentication failures" in message:
        return "AUTHENTICATION_FAILURE"
    if "connection refused" in message:
        return "CONNECTION_REFUSED"
    if "connection timed out" in message or "operation timed out" in message:
        return "PROBE_TIMEOUT"
    if any(term in message for term in (
        "no route to host", "network is unreachable",
        "could not resolve hostname", "connection reset", "connection closed", "kex_exchange_identification",
        "connection to ",
    )):
        return "TRANSPORT_ERROR"
    return None


def classify_return(returncode: int, stderr: str = "") -> tuple[str, str, bool | None]:
    if returncode in {-signal.SIGINT, 130}:
        return "INTERRUPTED", "UNKNOWN", None
    if returncode == 0:
        return "AUTHENTICATED_SUCCESS", "SUCCESS", True
    mapped = classify_stderr(stderr)
    if mapped == "AUTHENTICATION_FAILURE":
        return mapped, "FAILURE", False
    if mapped == "PROBE_TIMEOUT":
        return mapped, "NOT_ESTABLISHED", None
    if mapped in {"HOST_KEY_FAILURE", "CONNECTION_REFUSED", "TRANSPORT_ERROR"}:
        return mapped, "NOT_ESTABLISHED", None
    if returncode == 255:
        return "TRANSPORT_ERROR", "UNKNOWN", None
    return "REMOTE_COMMAND_FAILURE", "SUCCESS", True


def _base_record(args: argparse.Namespace, *, started: datetime, ended: datetime, elapsed_ms: float,
                 timeout_seconds: int, result: str, auth: str, authenticated: bool | None,
                 exit_code: int | None, wall_elapsed_ms: float, discontinuity: bool) -> dict[str, Any]:
    return {
        "probe_version": 1,
        "trial_id": args.trial_id,
        "condition_id": args.condition_id,
        "repetition": args.repetition,
        "route": args.route,
        "target_id": args.target_id,
        "result": result,
        "authentication": auth,
        "authenticated": authenticated,
        "ssh_exit_code": exit_code,
        "started_at_utc": iso_utc(started),
        "ended_at_utc": iso_utc(ended),
        "elapsed_ms": round(max(0.0, elapsed_ms), 3),
        "wall_elapsed_ms": round(wall_elapsed_ms, 3),
        "clock_discontinuity": discontinuity,
        "timeout_seconds": timeout_seconds,
        "quiet_interval_seconds": args.quiet_interval_seconds,
        "quiet_period_confirmed": bool(args.quiet_interval_complete),
        "screen_lock_status": args.screen_lock_status,
        "screen_lock_confirmed": bool(args.screen_lock_confirmed),
        "operator_present": bool(args.operator_present),
        "p011_prerequisites_confirmed": all((args.p011_preflight_passed, args.package_installation_authorized, args.installed_runtime_verified, args.assertion_cleanup_verified)),
        "physical_recovery_confirmed": bool(args.physical_recovery_confirmed),
        "battery_thermal_approved": bool(args.battery_thermal_approved),
        "wifi_association_confirmed": bool(args.wifi_association_confirmed),
        "route_state_confirmed": bool(args.route_state_confirmed),
        "daemon_state_confirmed": bool(args.daemon_state_confirmed),
        "assertion_state_confirmed": bool(args.assertion_state_confirmed),
        "observer_timebase_id": args.timebase_id,
        "timing_uncertainty_ms": args.timing_uncertainty_ms,
    }


def run_probe(args: argparse.Namespace, *, protocol: dict[str, Any], ssh_path: str | None = None) -> dict[str, Any]:
    """Execute precisely one SSH command. Called only after the explicit attended gate."""
    ssh = ssh_path or shutil.which("ssh")
    started = utc_now()
    monotonic_start = time.monotonic_ns()
    timeout_seconds = args.timeout_seconds or protocol["probe"]["timeout_seconds"]
    if ssh is None:
        ended = utc_now()
        elapsed = (time.monotonic_ns() - monotonic_start) / 1_000_000
        return _base_record(args, started=started, ended=ended, elapsed_ms=elapsed, timeout_seconds=timeout_seconds,
                            result="SSH_CLIENT_MISSING", auth="UNKNOWN", authenticated=None, exit_code=None,
                            wall_elapsed_ms=(ended - started).total_seconds() * 1000, discontinuity=False)
    command = [
        ssh,
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout_seconds}",
        "-o", "ConnectionAttempts=1",
        "-o", "StrictHostKeyChecking=yes",
        "-p", str(args.port),
        args.destination,
        protocol["probe"]["remote_command"],
    ]
    result = "TRANSPORT_ERROR"
    auth = "UNKNOWN"
    authenticated: bool | None = None
    exit_code: int | None = None
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout_seconds + 2,
        )
        exit_code = completed.returncode
        result, auth, authenticated = classify_return(completed.returncode, completed.stderr or "")
    except subprocess.TimeoutExpired:
        result, auth, authenticated = "PROBE_TIMEOUT", "NOT_ESTABLISHED", None
    except FileNotFoundError:
        result, auth, authenticated = "SSH_CLIENT_MISSING", "UNKNOWN", None
    except KeyboardInterrupt:
        result, auth, authenticated = "INTERRUPTED", "UNKNOWN", None
    except OSError:
        result, auth, authenticated = "TRANSPORT_ERROR", "UNKNOWN", None
    ended = utc_now()
    monotonic_end = time.monotonic_ns()
    elapsed = max(0.0, (monotonic_end - monotonic_start) / 1_000_000)
    wall = (ended - started).total_seconds() * 1000
    threshold = max(5_000, args.timing_uncertainty_ms * 2)
    discontinuity = ended < started or abs(wall - elapsed) > threshold
    return _base_record(args, started=started, ended=ended, elapsed_ms=elapsed, timeout_seconds=timeout_seconds,
                        result=result, auth=auth, authenticated=authenticated, exit_code=exit_code,
                        wall_elapsed_ms=wall, discontinuity=discontinuity)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL), help="versioned P012 protocol JSON")
    parser.add_argument("--dry-run", action="store_true", help="print a sanitized plan; never run SSH")
    parser.add_argument("--run-attended", action="store_true", help="explicitly authorize one attended SSH probe")
    parser.add_argument("--destination", help="operator-supplied SSH host or user@host; never written to output")
    parser.add_argument("--target-id", help="sanitized target label recorded instead of the destination")
    parser.add_argument("--route", choices=("LAN", "TAILSCALE"), required=True)
    parser.add_argument("--condition-id", choices=tuple(CONDITIONS), required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--repetition", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--timebase-id", help="operator-supplied independent host-clock identifier")
    parser.add_argument("--timing-uncertainty-ms", type=int, help="operator-estimated UTC time uncertainty")
    parser.add_argument("--timeout-seconds", type=int, help="optional bounded override; defaults to protocol")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--quiet-interval-seconds", type=int)
    parser.add_argument("--quiet-interval-complete", action="store_true")
    parser.add_argument("--screen-lock-status", choices=("LOCKED", "UNLOCKED", "UNKNOWN"), default="UNKNOWN")
    parser.add_argument("--screen-lock-confirmed", action="store_true")
    parser.add_argument("--daemon-state", choices=("STOPPED", "RUNNING_IDLE", "RUNNING_HOLD", "UNKNOWN"), default="UNKNOWN")
    parser.add_argument("--daemon-state-confirmed", action="store_true")
    parser.add_argument("--assertion-state", choices=("INACTIVE", "ACTIVE", "EXPIRED_RELEASED", "UNKNOWN"), default="UNKNOWN")
    parser.add_argument("--assertion-state-confirmed", action="store_true")
    parser.add_argument("--operator-present", action="store_true")
    parser.add_argument("--p011-preflight-passed", action="store_true")
    parser.add_argument("--package-installation-authorized", action="store_true")
    parser.add_argument("--installed-runtime-verified", action="store_true")
    parser.add_argument("--assertion-cleanup-verified", action="store_true")
    parser.add_argument("--physical-recovery-confirmed", action="store_true")
    parser.add_argument("--battery-thermal-approved", action="store_true")
    parser.add_argument("--wifi-association-confirmed", action="store_true")
    parser.add_argument("--route-state-confirmed", action="store_true")
    return parser


def _preflight_errors(args: argparse.Namespace, protocol: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not args.run_attended:
        errors.append("--run-attended is required for any SSH connection")
    if args.dry_run:
        errors.append("--dry-run and --run-attended cannot be combined")
    if not args.destination or not valid_destination(args.destination):
        errors.append("a separate, syntactically safe --destination is required")
    if not valid_id(args.trial_id):
        errors.append("--trial-id must be a sanitized identifier")
    if not args.target_id or not valid_target_id(args.target_id):
        errors.append("a sanitized --target-id is required")
    if args.port < 1 or args.port > 65535:
        errors.append("--port must be in the range 1–65535")
    if not args.timebase_id or not valid_id(args.timebase_id):
        errors.append("a sanitized --timebase-id is required")
    if type(args.timing_uncertainty_ms) is not int or not 0 <= args.timing_uncertainty_ms <= 86_400_000:
        errors.append("--timing-uncertainty-ms must be explicitly supplied and bounded")
    timeout = args.timeout_seconds or protocol["probe"]["timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= protocol["probe"]["maximum_timeout_seconds"]:
        errors.append("SSH timeout is outside the protocol limit")
    quiet = protocol["quiet_period"]
    if type(args.quiet_interval_seconds) is not int or not quiet["minimum_seconds"] <= args.quiet_interval_seconds <= quiet["maximum_seconds"]:
        errors.append("--quiet-interval-seconds must stay within the reviewed protocol bounds")
    if not args.quiet_interval_complete:
        errors.append("--quiet-interval-complete is required; no probe may occur during the quiet interval")
    if args.screen_lock_status != "LOCKED" or not args.screen_lock_confirmed:
        errors.append("an operator-confirmed LOCKED screen is required")
    expected = CONDITIONS[args.condition_id]
    if not args.daemon_state_confirmed or args.daemon_state != expected[0]:
        errors.append("operator-confirmed daemon state does not match the selected condition")
    if not args.assertion_state_confirmed or args.assertion_state != expected[1]:
        errors.append("operator-confirmed assertion state does not match the selected condition")
    if not args.operator_present:
        errors.append("--operator-present is required")
    for flag, label in (
        (args.p011_preflight_passed, "P011 stable-package preflight PASS"),
        (args.package_installation_authorized, "separate package-installation authorization"),
        (args.installed_runtime_verified, "installed CLI/daemon verification"),
        (args.assertion_cleanup_verified, "confirmed assertion acquire/release cleanup"),
    ):
        if not flag:
            errors.append(f"{label} is not confirmed")
    if not args.physical_recovery_confirmed:
        errors.append("--physical-recovery-confirmed is required")
    for flag, label in (
        (args.battery_thermal_approved, "battery and thermal safety"),
        (args.wifi_association_confirmed, "Wi-Fi association"),
        (args.route_state_confirmed, "selected route state"),
    ):
        if not flag:
            errors.append(f"{label} must be confirmed")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        protocol = load_json(__import__("pathlib").Path(args.protocol))
    except P012Error as exc:
        parser.error(str(exc))
    protocol_issues = validate_protocol(protocol)
    if protocol_issues:
        parser.error("invalid protocol: " + "; ".join(protocol_issues))
    if not args.run_attended:
        output = {
            "mode": "DRY_RUN",
            "network_attempted": False,
            "power_state_changed": False,
            "route": args.route,
            "condition_id": args.condition_id,
            "trial_id": args.trial_id,
            "remote_command": protocol["probe"]["remote_command"],
            "requires_for_execution": ["--run-attended", "operator-supplied --destination", "P011/recovery prerequisites", "completed quiet interval", "confirmed locked screen", "confirmed condition state"],
        }
        print(json.dumps(output, sort_keys=True, indent=2))
        return 0
    errors = _preflight_errors(args, protocol)
    if errors:
        parser.error("probe refused: " + "; ".join(errors))
    record = run_probe(args, protocol=protocol)
    print(json.dumps(record, sort_keys=True, indent=2))
    return 130 if record["result"] == "INTERRUPTED" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(json.dumps({"result": "INTERRUPTED", "authentication": "UNKNOWN", "authenticated": None, "power_state_changed": False}, sort_keys=True))
        raise SystemExit(130)
