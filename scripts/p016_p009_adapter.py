#!/usr/bin/env python3
"""Convert one current P016 CLI observation to a P009 v1 event fragment."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone


SOURCE_CLASSES = {
    "SIMULATED", "MOCK", "CI", "DEVICE_REPORTED", "EXTERNAL_OBSERVER", "OPERATOR_RECORDED"
}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TRIAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TIMEBASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CONDITIONS = {"A", "B", "C", "D"}


class AdapterError(ValueError):
    pass


class ObservationUnavailable(AdapterError):
    pass


def parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line or "=" not in line:
            raise AdapterError(f"input line {line_number} is not a key/value field")
        key, value = line.split("=", 1)
        if not key or key in fields or any(ord(char) < 0x20 for char in key + value):
            raise AdapterError(f"input line {line_number} has an invalid or duplicate field")
        fields[key] = value
    return fields


def field(fields: dict[str, str], key: str) -> str:
    value = fields.get(key)
    if value is None:
        raise AdapterError(f"missing P016 field: {key}")
    return value


def integer(fields: dict[str, str], key: str, maximum: int) -> int:
    value = field(fields, key)
    if not value or not value.isascii() or not value.isdigit():
        raise AdapterError(f"P016 field is not a nonnegative integer: {key}")
    parsed = int(value)
    if parsed > maximum:
        raise AdapterError(f"P016 field is outside its supported range: {key}")
    return parsed


def yes_no(fields: dict[str, str], key: str) -> bool:
    value = field(fields, key)
    if value == "yes":
        return True
    if value == "no":
        return False
    raise AdapterError(f"P016 field is not yes/no: {key}")


def observation_event(
    fields: dict[str, str], kind: str, event_id: str, sequence: int,
    trial_id: str | None = None, condition_id: str | None = None,
) -> dict[str, object]:
    if kind not in {"battery", "thermal"}:
        raise AdapterError("event kind must be battery or thermal")
    if not ID_RE.fullmatch(event_id):
        raise AdapterError("event ID must use the P009 identifier format")
    if type(sequence) is not int or sequence < 0 or sequence > 2**32 - 1:
        raise AdapterError("sequence must be an integer between 0 and 2^32-1")
    if (trial_id is None) != (condition_id is None):
        raise AdapterError("trial ID and condition ID must be supplied together")
    if trial_id is not None:
        if not TRIAL_ID_RE.fullmatch(trial_id):
            raise AdapterError("trial ID must use the P012 identifier format")
        if condition_id not in CONDITIONS:
            raise AdapterError("condition ID must be A, B, C, or D")

    prefix = "battery.percentage_observation" if kind == "battery" else "thermal.observation"
    if field(fields, f"{prefix}.status") != "AVAILABLE":
        raise ObservationUnavailable("unavailable telemetry cannot produce a P009 observation event")
    if field(fields, f"{prefix}.freshness") != "CURRENT":
        raise ObservationUnavailable("stale or unproven telemetry cannot produce a P009 observation event")
    if not yes_no(fields, f"{prefix}.source_detected"):
        raise AdapterError("P009 observation event requires a detected source")
    if not yes_no(fields, f"{prefix}.measurement_acquired"):
        raise AdapterError("P009 observation event requires an acquired measurement")
    if not yes_no(fields, f"{prefix}.value_valid"):
        raise AdapterError("P009 observation event requires a valid value")

    source_class = field(fields, f"{prefix}.source_class")
    if source_class not in SOURCE_CLASSES:
        raise AdapterError("P016 source class is not supported by P009 v1")
    source_name = field(fields, f"{prefix}.source")
    if not source_name or len(source_name) > 128:
        raise AdapterError("P016 source identity is empty or oversized")
    timebase_id = field(fields, f"{prefix}.timebase_id")
    if not TIMEBASE_RE.fullmatch(timebase_id) or timebase_id == "UNKNOWN":
        raise ObservationUnavailable("P009 event requires a valid, known timebase identity")
    observed_at = integer(fields, f"{prefix}.observed_at_utc", 253402300799)
    if observed_at == 0:
        raise ObservationUnavailable("P009 event requires a positive UTC observation time")
    uncertainty = integer(fields, f"{prefix}.clock_uncertainty_ms", 86400000)
    if field(fields, f"{prefix}.age_seconds") == "UNAVAILABLE":
        raise ObservationUnavailable("P009 event requires a bounded observation age")
    age = integer(fields, f"{prefix}.age_seconds", 2**63 - 1)
    confidence = field(fields, f"{prefix}.confidence")
    if confidence not in {"LOW", "MEDIUM", "HIGH"}:
        raise ObservationUnavailable("P009 event requires an explicit confidence value")
    try:
        timestamp = datetime.fromtimestamp(observed_at, timezone.utc).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        raise AdapterError("P016 UTC timestamp cannot be represented in P009 v1") from None

    details: dict[str, object] = {
        "observed": True,
        "p016_schema_version": 1,
        "source_name": source_name,
        "source_detected": True,
        "measurement_acquired": True,
        "value_valid": True,
        "freshness": "CURRENT",
        "age_seconds": age,
        "confidence": confidence,
        "physical_source_verified": yes_no(fields, f"{prefix}.physical_source_verified"),
        "safety_interpretation_reviewed": yes_no(fields, f"{prefix}.safety_interpretation_reviewed"),
        "p009_evidence_accepted": yes_no(fields, f"{prefix}.p009_evidence_accepted"),
    }
    event_type = "BATTERY_OBSERVATION" if kind == "battery" else "THERMAL_OBSERVATION"
    if kind == "battery":
        percentage = integer(fields, "battery.percentage", 100)
        charging = field(fields, "battery.charging")
        if charging not in {"YES", "NO", "FULL", "UNKNOWN"}:
            raise AdapterError("charging state is not recognized")
        details.update({"percentage": percentage, "charging": charging})
    else:
        state = field(fields, "thermal.state")
        raw_state = field(fields, "thermal.raw_platform_state")
        if state not in {"NOMINAL", "ELEVATED", "CRITICAL"}:
            raise AdapterError("unknown thermal state cannot produce an observation event")
        if raw_state not in {"NOMINAL", "FAIR", "SERIOUS", "CRITICAL"}:
            raise AdapterError("unrecognized raw thermal state cannot produce an event")
        details.update({"state": state, "raw_platform_state": raw_state,
                        "temperature_celsius": None})
    if trial_id is not None:
        details.update({"trial_id": trial_id, "condition_id": condition_id,
                        "sampling_window": "OPERATOR_ASSERTED_OUTSIDE_QUIET_INTERVAL"})
    return {
        "event_id": event_id,
        "sequence": sequence,
        "event_type": event_type,
        "timestamp": timestamp,
        "source": source_class,
        "timebase_id": timebase_id,
        "uncertainty_ms": uncertainty,
        "details": details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert one current `ic health battery|thermal` output to a P009 v1 event fragment."
    )
    parser.add_argument("kind", choices=("battery", "thermal"))
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--sequence", required=True, type=int)
    parser.add_argument("--trial-id")
    parser.add_argument("--condition-id")
    parser.add_argument("--outside-quiet-interval", action="store_true")
    args = parser.parse_args(argv)
    if (args.trial_id is None) != (args.condition_id is None) or (
        args.trial_id is not None and not args.outside_quiet_interval
    ) or (args.outside_quiet_interval and args.trial_id is None):
        print("trial association requires trial ID, condition ID, and --outside-quiet-interval",
              file=sys.stderr)
        return 2
    try:
        fields = parse_fields(sys.stdin.read())
        event = observation_event(fields, args.kind, args.event_id, args.sequence,
                                  args.trial_id, args.condition_id)
    except ObservationUnavailable as exc:
        print(f"P009 event unavailable: {exc}", file=sys.stderr)
        return 3
    except AdapterError as exc:
        print(f"P009 event unavailable: {exc}", file=sys.stderr)
        return 1
    json.dump(event, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
