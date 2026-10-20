"""Shared, offline P012 protocol, trial, and P009 mapping helpers."""

from __future__ import annotations

import json
import ipaddress
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = ROOT / "experiments/p012/protocol-v1.json"
DEFAULT_PROTOCOL_SCHEMA = ROOT / "experiments/p012/protocol-v1.schema.json"
DEFAULT_TRIAL_SCHEMA = ROOT / "experiments/p012/trial-record-v1.schema.json"
MAX_JSON_BYTES = 1_048_576
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SECRET_KEY_RE = re.compile(r"(?:password|passwd|passphrase|secret|token|credential|private.?key|ssh.?key|auth.?key)", re.I)
SECRET_VALUE_RE = re.compile(
    r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PGP|PRIVATE) KEY-----|"
    r"\btskey-(?:auth|api)-[A-Za-z0-9_-]{8,}|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}",
    re.I,
)
SECRET_ASSIGNMENT_RE = re.compile(r"\b(?:password|passwd|passphrase|secret|token|auth[_ -]?key)\s*[:=]\s*\S+", re.I)
CONDITIONS = {
    "A": ("STOPPED", "INACTIVE"),
    "B": ("RUNNING_IDLE", "INACTIVE"),
    "C": ("RUNNING_HOLD", "ACTIVE"),
    "D": ("RUNNING_IDLE", "EXPIRED_RELEASED"),
}
ROUTES = ("LAN", "TAILSCALE")
SOURCE_CLASSES = {"SIMULATED", "MOCK", "CI", "DEVICE_REPORTED", "EXTERNAL_OBSERVER", "OPERATOR_RECORDED"}
PROBE_RESULTS = {
    "AUTHENTICATED_SUCCESS", "AUTHENTICATION_FAILURE", "PROBE_TIMEOUT", "CONNECTION_REFUSED",
    "HOST_KEY_FAILURE", "INTERRUPTED", "TRANSPORT_ERROR", "REMOTE_COMMAND_FAILURE", "SSH_CLIENT_MISSING",
}
AUTH_STATES = {"SUCCESS", "FAILURE", "NOT_ESTABLISHED", "UNKNOWN"}
TRIAL_KEYS = {
    "record_version", "evidence_origin", "trial_id", "repetition", "pair_id", "condition_id", "route",
    "condition_order_index", "route_order_index", "trial_started_at_utc", "trial_ended_at_utc",
    "observer_timebase_id", "timing_uncertainty_ms", "device_timebase_id", "device_clock_uncertainty_ms",
    "state", "operator_confirmations", "probe", "interrupted", "interruption_code",
}
STATE_KEYS = {
    "screen_lock_status", "screen_lock_observed_at_utc", "charging_state", "battery_percent",
    "battery_observed_at_utc", "thermal_state", "thermal_observed_at_utc", "wifi_association",
    "wifi_profile_id", "lan_route_state", "tailscale_route_state", "daemon_state", "assertion_state",
    "assertion_duration_seconds", "assertion_acquire_result", "assertion_acquire_started_at_utc",
    "assertion_acquired_at_utc", "assertion_release_result", "assertion_release_kind",
    "assertion_release_confirmed_at_utc", "quiet_start_at_utc", "quiet_end_at_utc",
    "quiet_interval_seconds", "quiet_period_confirmed", "quiet_period_contaminated",
    "quiet_incoming_probe_count", "quiet_operator_interaction_count",
    "elapsed_since_previous_trial_seconds", "reboot_or_respring_since_previous",
}
CONFIRMATION_KEYS = {
    "operator_present", "direct_recovery_available", "p011_stable_package_preflight_passed",
    "package_installation_separately_authorized", "installed_runtime_verified",
    "assertion_acquire_release_cleanup_verified", "battery_thermal_safe", "screen_locked",
    "wifi_association_confirmed", "route_state_confirmed", "daemon_state_confirmed",
    "assertion_state_confirmed", "trial_order_followed",
}
PROBE_KEYS = {
    "probe_version", "trial_id", "condition_id", "repetition", "route", "target_id", "result",
    "authentication", "authenticated", "ssh_exit_code", "started_at_utc", "ended_at_utc",
    "elapsed_ms", "wall_elapsed_ms", "clock_discontinuity", "timeout_seconds",
    "quiet_interval_seconds", "quiet_period_confirmed", "screen_lock_status",
    "screen_lock_confirmed", "operator_present", "p011_prerequisites_confirmed",
    "physical_recovery_confirmed", "battery_thermal_approved", "wifi_association_confirmed",
    "route_state_confirmed", "daemon_state_confirmed", "assertion_state_confirmed",
    "observer_timebase_id", "timing_uncertainty_ms",
}


class P012Error(ValueError):
    """Malformed or unsafe P012 data."""


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise P012Error("JSON contains a duplicate object key")
        out[key] = value
    return out


def _reject_constant(_: str) -> None:
    raise P012Error("JSON contains a non-standard numeric value")


def _parse_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise P012Error("JSON contains a non-finite number")
    return number


def parse_json_bytes(data: bytes) -> Any:
    if len(data) > MAX_JSON_BYTES:
        raise P012Error("JSON input exceeds the 1 MiB limit")
    try:
        return json.loads(
            data.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant, parse_float=_parse_float,
        )
    except P012Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise P012Error("input is not valid UTF-8 JSON") from exc


def load_json(path: Path) -> Any:
    try:
        if path.is_symlink():
            raise P012Error("refusing to read a symbolic-link evidence file")
        info = path.stat()
        if not path.is_file() or info.st_size > MAX_JSON_BYTES:
            raise P012Error("input must be a regular JSON file no larger than 1 MiB")
        return parse_json_bytes(path.read_bytes())
    except FileNotFoundError as exc:
        raise P012Error("input file was not found") from exc
    except OSError as exc:
        raise P012Error("input file could not be read safely") from exc


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def valid_id(value: Any) -> bool:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        return False
    try:
        ipaddress.ip_address(value)
        return False
    except ValueError:
        return True


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def validate_json_schema(value: Any, schema: Any) -> list[str]:
    """Validate the JSON Schema subset used by the checked-in P012 v1 contracts."""
    if not isinstance(schema, dict):
        return ["schema document is not an object"]
    errors: list[str] = []

    def dereference(reference: str) -> Any:
        if not reference.startswith("#/"):
            raise P012Error("external JSON Schema references are not supported")
        current: Any = schema
        for component in reference[2:].split("/"):
            component = component.replace("~1", "/").replace("~0", "~")
            if not isinstance(current, dict) or component not in current:
                raise P012Error("JSON Schema contains an unresolved local reference")
            current = current[component]
        return current

    def matches_type(item: Any, expected: str) -> bool:
        return {
            "object": isinstance(item, dict),
            "array": isinstance(item, list),
            "string": isinstance(item, str),
            "integer": type(item) is int,
            "number": type(item) in (int, float) and math.isfinite(item),
            "boolean": type(item) is bool,
            "null": item is None,
        }.get(expected, False)

    def visit(item: Any, rule: Any, path: str, depth: int) -> list[str]:
        if depth > 64 or not isinstance(rule, dict):
            return [f"{path}: invalid or overly deep schema"]
        if "$ref" in rule:
            try:
                return visit(item, dereference(rule["$ref"]), path, depth + 1)
            except P012Error as exc:
                return [f"{path}: {exc}"]
        found: list[str] = []
        if "const" in rule and (type(item) is not type(rule["const"]) or item != rule["const"]):
            found.append(f"{path}: constant does not match")
        if "enum" in rule and not any(type(item) is type(candidate) and item == candidate for candidate in rule["enum"]):
            found.append(f"{path}: value is outside the allowed enumeration")
        if "type" in rule:
            expected = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
            if not any(matches_type(item, kind) for kind in expected):
                return found + [f"{path}: JSON type mismatch"]
        if "oneOf" in rule:
            results = [visit(item, candidate, path, depth + 1) for candidate in rule["oneOf"]]
            if sum(not result for result in results) != 1:
                found.append(f"{path}: value does not match exactly one schema alternative")
            return found
        if "format" in rule and isinstance(item, str):
            if rule["format"] == "date-time" and parse_utc(item) is None:
                found.append(f"{path}: invalid date-time format")
            elif rule["format"] == "date":
                try:
                    date.fromisoformat(item)
                except ValueError:
                    found.append(f"{path}: invalid date format")
        if isinstance(item, str):
            if len(item) < rule.get("minLength", 0) or len(item) > rule.get("maxLength", math.inf):
                found.append(f"{path}: string length is outside bounds")
            if "pattern" in rule and re.search(rule["pattern"], item) is None:
                found.append(f"{path}: string pattern does not match")
        if type(item) in (int, float) and not isinstance(item, bool):
            if item < rule.get("minimum", -math.inf) or item > rule.get("maximum", math.inf):
                found.append(f"{path}: number is outside bounds")
        if isinstance(item, list):
            if len(item) < rule.get("minItems", 0) or len(item) > rule.get("maxItems", math.inf):
                found.append(f"{path}: array length is outside bounds")
            if rule.get("uniqueItems") is True:
                encodings = [json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) for value in item]
                if len(encodings) != len(set(encodings)):
                    found.append(f"{path}: array items are not unique")
            if "items" in rule:
                for index, child in enumerate(item):
                    found.extend(visit(child, rule["items"], f"{path}[{index}]", depth + 1))
        if isinstance(item, dict):
            if len(item) < rule.get("minProperties", 0) or len(item) > rule.get("maxProperties", math.inf):
                found.append(f"{path}: object property count is outside bounds")
            missing = set(rule.get("required", [])) - set(item)
            if missing:
                found.append(f"{path}: required properties are missing")
            properties = rule.get("properties", {})
            if isinstance(properties, dict):
                for key, child in item.items():
                    child_schema = properties.get(key)
                    if child_schema is not None:
                        found.extend(visit(child, child_schema, f"{path}.{key}", depth + 1))
                    elif rule.get("additionalProperties") is False:
                        found.append(f"{path}: unexpected property")
                    elif isinstance(rule.get("additionalProperties"), dict):
                        found.extend(visit(child, rule["additionalProperties"], f"{path}.{key}", depth + 1))
        return found

    errors.extend(visit(value, schema, "$", 0))
    return errors


def contains_sensitive(value: Any, key: str = "") -> bool:
    if key and SECRET_KEY_RE.search(key):
        return True
    if isinstance(value, dict):
        return any(contains_sensitive(item, str(child_key)) for child_key, item in value.items())
    if isinstance(value, list):
        return any(contains_sensitive(item) for item in value)
    if isinstance(value, str):
        return bool(SECRET_VALUE_RE.search(value) or SECRET_ASSIGNMENT_RE.search(value))
    return False


def validate_protocol(protocol: Any) -> list[str]:
    issues: list[str] = []
    if not isinstance(protocol, dict):
        return ["protocol must be a JSON object"]
    try:
        schema = load_json(DEFAULT_PROTOCOL_SCHEMA)
        issues.extend("schema: " + item for item in validate_json_schema(protocol, schema))
    except P012Error as exc:
        issues.append("protocol schema unavailable or invalid: " + str(exc))
    if protocol.get("protocol_id") != "P012" or protocol.get("protocol_version") != 1:
        issues.append("unsupported protocol identity or version")
    expected_top = {
        "protocol_id", "protocol_version", "protocol_status", "preregistered_on", "target_platform", "research_questions",
        "conditions", "assertion", "quiet_period", "probe", "design", "required_operator_confirmations",
        "inclusion_criteria", "exclusion_criteria", "stop_conditions", "recovery_requirements", "data_retention",
        "p011_prerequisite", "known_sources_of_bias", "evidence_source_classes", "p009_mapping",
    }
    if set(protocol) != expected_top:
        issues.append("protocol fields do not match the protocol-v1 format")
    if protocol.get("protocol_status") != "PREREGISTERED_PROPOSAL":
        issues.append("protocol must remain an explicitly preregistered proposal")
    try:
        date.fromisoformat(protocol.get("preregistered_on", ""))
    except (TypeError, ValueError):
        issues.append("preregistered_on must be a calendar date")
    target_platform = protocol.get("target_platform")
    if not isinstance(target_platform, dict) or set(target_platform) != {"device", "soc", "ios", "bootstrap"}:
        issues.append("target platform fields are malformed")
    if protocol.get("research_questions") != ["RQ1", "RQ2", "RQ3", "RQ4"]:
        issues.append("research question identifiers are incomplete or reordered")
    try:
        expected_conditions = ["A", "B", "C", "D"]
        conditions = protocol["conditions"]
        if not isinstance(conditions, list) or [item.get("id") for item in conditions] != expected_conditions:
            issues.append("conditions must be exactly A, B, C, and D in the registered order")
        else:
            for item in conditions:
                if set(item) != {"id", "name", "daemon_state", "assertion_state", "definition"}:
                    issues.append(f"condition {item.get('id')} fields do not match protocol v1")
                if (item.get("daemon_state"), item.get("assertion_state")) != CONDITIONS[item["id"]]:
                    issues.append(f"condition {item['id']} does not match its fixed state definition")
    except (KeyError, TypeError, AttributeError):
        issues.append("condition definitions are malformed")
    try:
        assertion = protocol["assertion"]
        if set(assertion) != {"active_hold_seconds", "maximum_hold_seconds", "measurement_must_precede_expiry", "actual_acquisition_and_release_confirmation_required"}:
            issues.append("assertion fields do not match protocol v1")
        hold = assertion["active_hold_seconds"]
        maximum = assertion["maximum_hold_seconds"]
        if type(hold) is not int or type(maximum) is not int or not 1 <= hold <= maximum <= 300:
            issues.append("assertion hold must be positive and bounded by the 300-second ceiling")
        if assertion.get("measurement_must_precede_expiry") is not True:
            issues.append("Condition C measurement must precede expiry")
        if assertion.get("actual_acquisition_and_release_confirmation_required") is not True:
            issues.append("actual assertion acquisition and release confirmation is required")
    except (KeyError, TypeError):
        issues.append("assertion settings are malformed")
    try:
        quiet = protocol["quiet_period"]
        if set(quiet) != {"seconds", "minimum_seconds", "maximum_seconds", "required_before_each_probe", "incoming_ssh_probes_allowed", "operator_interactions_allowed"}:
            issues.append("quiet-period fields do not match protocol v1")
        seconds, minimum, maximum = quiet["seconds"], quiet["minimum_seconds"], quiet["maximum_seconds"]
        if any(type(value) is not int for value in (seconds, minimum, maximum)) or not 60 <= minimum <= seconds <= maximum <= 180:
            issues.append("quiet interval must be configurable within the preregistered 60–180 second reviewed bound")
        if quiet.get("required_before_each_probe") is not True or quiet.get("incoming_ssh_probes_allowed") is not False:
            issues.append("a quiet interval with no incoming probes is required before every probe")
    except (KeyError, TypeError):
        issues.append("quiet-period settings are malformed")
    try:
        probe = protocol["probe"]
        if set(probe) != {"timeout_seconds", "maximum_timeout_seconds", "maximum_probes_per_trial", "remote_command", "ssh_options"}:
            issues.append("probe fields do not match protocol v1")
        if type(probe["timeout_seconds"]) is not int or not 1 <= probe["timeout_seconds"] <= probe["maximum_timeout_seconds"] <= 15:
            issues.append("SSH timeout must be bounded to at most 15 seconds")
        if probe.get("maximum_probes_per_trial") != 1 or probe.get("remote_command") != "true":
            issues.append("each trial must issue one minimal read-only SSH command")
        options = set(probe["ssh_options"])
        if not {"BatchMode=yes", "ConnectionAttempts=1", "StrictHostKeyChecking=yes"}.issubset(options):
            issues.append("SSH must use batch mode, one attempt, and host-key verification")
    except (KeyError, TypeError):
        issues.append("probe settings are malformed")
    try:
        design = protocol["design"]
        if set(design) != {"repetitions_per_condition_per_route", "routes", "one_route_per_trial", "pairing_rule", "total_planned_probe_trials", "route_order_by_repetition", "condition_order_by_repetition", "automated_physical_trial_series", "interpretation"}:
            issues.append("design fields do not match protocol v1")
        if design.get("routes") != ["LAN", "TAILSCALE"] or design.get("one_route_per_trial") is not True:
            issues.append("LAN and Tailscale must use separate one-route trials")
        if design.get("pairing_rule") != "Pair route trials by condition and repetition using one sanitized pair_id; assign a distinct trial_id to each route trial.":
            issues.append("route pairing must use matching condition/repetition pair IDs and distinct trial IDs")
        if design.get("repetitions_per_condition_per_route") != 3 or design.get("total_planned_probe_trials") != 24:
            issues.append("exploratory design must define three repetitions per condition and route")
        if design.get("automated_physical_trial_series") is not False:
            issues.append("physical trial series must remain manually operated")
        route_orders = design.get("route_order_by_repetition")
        if not isinstance(route_orders, list) or len(route_orders) != 3 or any(sorted(row) != ["LAN", "TAILSCALE"] for row in route_orders):
            issues.append("route order must counterbalance both routes across three repetitions")
        condition_orders = design.get("condition_order_by_repetition")
        if not isinstance(condition_orders, list) or len(condition_orders) != 3 or any(sorted(row) != ["A", "B", "C", "D"] for row in condition_orders):
            issues.append("condition order must contain each condition once in every repetition")
    except (KeyError, TypeError):
        issues.append("trial design settings are malformed")
    prerequisite = protocol.get("p011_prerequisite")
    if not isinstance(prerequisite, dict) or prerequisite.get("required_before_hardware_trials") is not True:
        issues.append("P011 hardware prerequisites must gate physical trials")
    mapping = protocol.get("p009_mapping")
    if not isinstance(mapping, dict) or mapping.get("do_not_create_full_acceptance_session") is not True:
        issues.append("P012 mapping must not synthesize a complete P009 acceptance session")
    if contains_sensitive(protocol):
        issues.append("protocol contains a forbidden secret-like key or value")
    return issues


def normalize_trial(record: dict[str, Any]) -> dict[str, Any]:
    """Fill absent observational fields with unknowns so incomplete trials remain recordable."""
    output = dict(record)
    state = output.get("state") if isinstance(output.get("state"), dict) else {}
    defaults: dict[str, Any] = {
        "screen_lock_status": "UNKNOWN", "screen_lock_observed_at_utc": None,
        "charging_state": "UNKNOWN", "battery_percent": None, "battery_observed_at_utc": None,
        "thermal_state": "UNKNOWN", "thermal_observed_at_utc": None,
        "wifi_association": "UNKNOWN", "wifi_profile_id": None,
        "lan_route_state": "UNKNOWN", "tailscale_route_state": "UNKNOWN",
        "daemon_state": "UNKNOWN", "assertion_state": "UNKNOWN", "assertion_duration_seconds": None,
        "assertion_acquire_result": "UNKNOWN", "assertion_acquire_started_at_utc": None,
        "assertion_acquired_at_utc": None, "assertion_release_result": "UNKNOWN",
        "assertion_release_kind": "UNKNOWN", "assertion_release_confirmed_at_utc": None,
        "quiet_start_at_utc": None, "quiet_end_at_utc": None, "quiet_interval_seconds": None,
        "quiet_period_confirmed": None, "quiet_period_contaminated": None,
        "quiet_incoming_probe_count": None, "quiet_operator_interaction_count": None,
        "elapsed_since_previous_trial_seconds": None, "reboot_or_respring_since_previous": "UNKNOWN",
    }
    output["state"] = {**defaults, **state}
    confirmations = output.get("operator_confirmations") if isinstance(output.get("operator_confirmations"), dict) else {}
    output["operator_confirmations"] = {key: confirmations.get(key) for key in sorted(CONFIRMATION_KEYS)}
    output.setdefault("record_version", 1)
    output.setdefault("evidence_origin", "OPERATOR_RECORDED")
    output.setdefault("pair_id", None)
    output.setdefault("repetition", None)
    output.setdefault("condition_id", None)
    output.setdefault("route", None)
    output.setdefault("condition_order_index", None)
    output.setdefault("route_order_index", None)
    output.setdefault("trial_started_at_utc", None)
    output.setdefault("trial_ended_at_utc", None)
    output.setdefault("observer_timebase_id", None)
    output.setdefault("timing_uncertainty_ms", None)
    output.setdefault("device_timebase_id", None)
    output.setdefault("device_clock_uncertainty_ms", None)
    output.setdefault("probe", None)
    output.setdefault("interrupted", False)
    output.setdefault("interruption_code", None)
    return output


def record_encoding_issues(record: Any) -> list[str]:
    """Reject malformed free-form values before storing operator JSON; missing facts remain nullable."""
    issues: list[str] = []
    if not isinstance(record, dict) or set(record) != TRIAL_KEYS:
        return ["record object fields do not match P012 v1"]
    if type(record.get("record_version")) is not int or record.get("record_version") != 1 or not isinstance(record.get("evidence_origin"), str) or record.get("evidence_origin") not in SOURCE_CLASSES:
        issues.append("record version or evidence origin is invalid")
    for key in ("trial_id", "pair_id", "observer_timebase_id", "device_timebase_id"):
        value = record.get(key)
        if value is not None and not valid_id(value):
            issues.append("record contains an unsafe identifier")
    if not valid_id(record.get("trial_id")):
        issues.append("trial ID is required and must be sanitized")
    if (record.get("condition_id") is not None and (not isinstance(record.get("condition_id"), str) or record.get("condition_id") not in CONDITIONS)) or (record.get("route") is not None and (not isinstance(record.get("route"), str) or record.get("route") not in ROUTES)):
        issues.append("condition or route has an invalid value")
    if record.get("repetition") is not None and (type(record["repetition"]) is not int or not 1 <= record["repetition"] <= 3):
        issues.append("repetition has an invalid value")
    for key, maximum in (("condition_order_index", 4), ("route_order_index", 2)):
        value = record.get(key)
        if value is not None and (type(value) is not int or not 1 <= value <= maximum):
            issues.append("trial order contains an invalid value")
    for key in ("trial_started_at_utc", "trial_ended_at_utc"):
        if record.get(key) is not None and parse_utc(record[key]) is None:
            issues.append("trial contains an invalid UTC timestamp")
    for key in ("timing_uncertainty_ms", "device_clock_uncertainty_ms"):
        value = record.get(key)
        if value is not None and (type(value) is not int or not 0 <= value <= 86_400_000):
            issues.append("trial contains invalid clock uncertainty")
    state = record.get("state")
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        issues.append("trial state fields are malformed")
        state = {}
    enum_fields = {
        "screen_lock_status": {"LOCKED", "UNLOCKED", "UNKNOWN"},
        "charging_state": {"CHARGING", "NOT_CHARGING", "UNKNOWN"},
        "thermal_state": {"COOL", "WARM", "HOT", "UNKNOWN"},
        "wifi_association": {"ASSOCIATED", "DISCONNECTED", "UNKNOWN"},
        "lan_route_state": {"AVAILABLE", "UNAVAILABLE", "UNKNOWN"},
        "tailscale_route_state": {"AVAILABLE", "UNAVAILABLE", "UNKNOWN"},
        "daemon_state": {"STOPPED", "RUNNING_IDLE", "RUNNING_HOLD", "UNKNOWN"},
        "assertion_state": {"INACTIVE", "ACTIVE", "EXPIRED_RELEASED", "UNKNOWN"},
        "assertion_acquire_result": {"SUCCESS", "FAILURE", "NOT_APPLICABLE", "UNKNOWN"},
        "assertion_release_result": {"SUCCESS", "FAILURE", "NOT_APPLICABLE", "UNKNOWN"},
        "assertion_release_kind": {"EXPIRED", "EXPLICIT", "NONE", "UNKNOWN"},
        "reboot_or_respring_since_previous": {True, False, "UNKNOWN"},
    }
    for key, allowed in enum_fields.items():
        value = state.get(key)
        if key == "reboot_or_respring_since_previous":
            valid_value = type(value) is bool or value == "UNKNOWN"
        else:
            valid_value = isinstance(value, str) and value in allowed
        if not valid_value:
            issues.append("trial contains an invalid state enumeration")
    for key in ("screen_lock_observed_at_utc", "battery_observed_at_utc", "thermal_observed_at_utc", "assertion_acquire_started_at_utc", "assertion_acquired_at_utc", "assertion_release_confirmed_at_utc", "quiet_start_at_utc", "quiet_end_at_utc"):
        if state.get(key) is not None and parse_utc(state[key]) is None:
            issues.append("trial state contains an invalid UTC timestamp")
    for key in ("quiet_period_confirmed", "quiet_period_contaminated"):
        if not _valid_bool_or_none(state.get(key)):
            issues.append("trial state contains an invalid boolean")
    for key in ("battery_percent", "assertion_duration_seconds", "quiet_interval_seconds", "quiet_incoming_probe_count", "quiet_operator_interaction_count"):
        value = state.get(key)
        if value is not None and type(value) is not int:
            issues.append("trial state contains an invalid integer")
    for key in ("quiet_incoming_probe_count", "quiet_operator_interaction_count"):
        value = state.get(key)
        if value is not None and value < 0:
            issues.append("trial state contains an invalid count")
    elapsed = state.get("elapsed_since_previous_trial_seconds")
    if elapsed is not None and (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0):
        issues.append("trial state contains invalid elapsed time")
    if state.get("wifi_profile_id") is not None and not valid_id(state.get("wifi_profile_id")):
        issues.append("trial contains an unsafe Wi-Fi profile identifier")
    confirmations = record.get("operator_confirmations")
    if not isinstance(confirmations, dict) or set(confirmations) != CONFIRMATION_KEYS or any(not _valid_bool_or_none(value) for value in (confirmations.values() if isinstance(confirmations, dict) else [])):
        issues.append("operator-confirmation values are malformed")
    if type(record.get("interrupted")) is not bool or (record.get("interruption_code") is not None and not valid_id(record.get("interruption_code"))):
        issues.append("interruption fields are malformed")
    probe = record.get("probe")
    if probe is not None:
        if not isinstance(probe, dict) or set(probe) != PROBE_KEYS:
            issues.append("host-probe fields are malformed")
        else:
            for key in ("trial_id", "target_id", "observer_timebase_id"):
                if not valid_id(probe.get(key)):
                    issues.append("host-probe contains an unsafe identifier")
            if not isinstance(probe.get("condition_id"), str) or probe.get("condition_id") not in CONDITIONS or not isinstance(probe.get("route"), str) or probe.get("route") not in ROUTES or not isinstance(probe.get("result"), str) or probe.get("result") not in PROBE_RESULTS or not isinstance(probe.get("authentication"), str) or probe.get("authentication") not in AUTH_STATES:
                issues.append("host-probe contains an invalid result enumeration")
            if not _valid_bool_or_none(probe.get("authenticated")) or type(probe.get("ssh_exit_code")) not in (int, type(None)):
                issues.append("host-probe authentication or exit fields are malformed")
            for key in ("clock_discontinuity", "quiet_period_confirmed", "screen_lock_confirmed", "operator_present", "p011_prerequisites_confirmed", "physical_recovery_confirmed", "battery_thermal_approved", "wifi_association_confirmed", "route_state_confirmed", "daemon_state_confirmed", "assertion_state_confirmed"):
                if type(probe.get(key)) is not bool:
                    issues.append("host-probe confirmation fields are malformed")
            for key in ("started_at_utc", "ended_at_utc"):
                if parse_utc(probe.get(key)) is None:
                    issues.append("host-probe timestamp fields are malformed")
            for key in ("elapsed_ms", "wall_elapsed_ms"):
                value = probe.get(key)
                if type(value) not in (int, float) or not math.isfinite(value):
                    issues.append("host-probe elapsed time is malformed")
            for key in ("repetition", "timeout_seconds", "quiet_interval_seconds", "timing_uncertainty_ms"):
                if type(probe.get(key)) is not int:
                    issues.append("host-probe numeric fields are malformed")
    return list(dict.fromkeys(issues))


def _valid_bool_or_none(value: Any) -> bool:
    return value is None or type(value) is bool


def validate_probe(probe: Any, protocol: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not isinstance(probe, dict):
        return ["probe must be an object"]
    if set(probe) != PROBE_KEYS:
        issues.append("probe fields do not match the P012 host-probe v1 format")
        return issues
    if probe.get("probe_version") != 1:
        issues.append("unsupported host-probe version")
    if not valid_id(probe.get("trial_id")) or not valid_id(probe.get("target_id")) or not valid_id(probe.get("observer_timebase_id")):
        issues.append("probe identifiers are invalid")
    if probe.get("condition_id") not in CONDITIONS or probe.get("route") not in ROUTES or probe.get("result") not in PROBE_RESULTS:
        issues.append("probe condition, route, or result is invalid")
    if probe.get("authentication") not in AUTH_STATES or not _valid_bool_or_none(probe.get("authenticated")):
        issues.append("probe authentication result is invalid")
    if type(probe.get("ssh_exit_code")) not in (int, type(None)):
        issues.append("SSH exit code must be an integer or null")
    if type(probe.get("elapsed_ms")) not in (int, float) or isinstance(probe.get("elapsed_ms"), bool) or probe.get("elapsed_ms", -1) < 0:
        issues.append("probe monotonic elapsed time is invalid")
    if type(probe.get("wall_elapsed_ms")) not in (int, float) or isinstance(probe.get("wall_elapsed_ms"), bool):
        issues.append("probe wall-clock elapsed time is invalid")
    for key in ("clock_discontinuity", "quiet_period_confirmed", "screen_lock_confirmed", "operator_present", "p011_prerequisites_confirmed", "physical_recovery_confirmed", "battery_thermal_approved", "wifi_association_confirmed", "route_state_confirmed", "daemon_state_confirmed", "assertion_state_confirmed"):
        if type(probe.get(key)) is not bool:
            issues.append(f"probe {key} must be boolean")
    if probe.get("screen_lock_status") not in {"LOCKED", "UNLOCKED", "UNKNOWN"}:
        issues.append("probe screen-lock status is invalid")
    if type(probe.get("timeout_seconds")) is not int or not 1 <= probe.get("timeout_seconds", 0) <= protocol.get("probe", {}).get("maximum_timeout_seconds", 15):
        issues.append("probe timeout is outside the protocol bound")
    if type(probe.get("quiet_interval_seconds")) is not int or not protocol.get("quiet_period", {}).get("minimum_seconds", 30) <= probe.get("quiet_interval_seconds", 0) <= protocol.get("quiet_period", {}).get("maximum_seconds", 300):
        issues.append("probe quiet interval is outside the protocol bound")
    if type(probe.get("timing_uncertainty_ms")) is not int or not 0 <= probe.get("timing_uncertainty_ms", -1) <= 86_400_000:
        issues.append("probe timing uncertainty is invalid")
    started, ended = parse_utc(probe.get("started_at_utc")), parse_utc(probe.get("ended_at_utc"))
    if started is None or ended is None or ended < started:
        issues.append("probe UTC timestamps are invalid or reversed")
    else:
        delta = (ended - started).total_seconds() * 1000
        if delta - probe.get("elapsed_ms", 0) > max(5_000, probe.get("timing_uncertainty_ms", 0) * 2):
            issues.append("probe shows a UTC/monotonic clock discontinuity")
    result = probe.get("result")
    if result == "AUTHENTICATED_SUCCESS" and (probe.get("authenticated") is not True or probe.get("authentication") != "SUCCESS" or probe.get("ssh_exit_code") != 0):
        issues.append("successful SSH classification conflicts with its authentication or exit status")
    if result == "AUTHENTICATION_FAILURE" and (probe.get("authenticated") is not False or probe.get("authentication") != "FAILURE"):
        issues.append("SSH authentication-failure classification is inconsistent")
    if result not in {"AUTHENTICATED_SUCCESS", "AUTHENTICATION_FAILURE", "REMOTE_COMMAND_FAILURE"} and probe.get("authenticated") is True:
        issues.append("non-authenticated transport result is marked authenticated")
    if probe.get("quiet_period_confirmed") is not True or probe.get("screen_lock_confirmed") is not True or probe.get("screen_lock_status") != "LOCKED":
        issues.append("host probe lacks confirmed quiet-period or locked-screen state")
    if any(probe.get(key) is not True for key in ("operator_present", "p011_prerequisites_confirmed", "physical_recovery_confirmed", "battery_thermal_approved", "wifi_association_confirmed", "route_state_confirmed", "daemon_state_confirmed", "assertion_state_confirmed")):
        issues.append("host probe lacks required attended P011/recovery confirmations")
    if contains_sensitive(probe):
        issues.append("probe contains a forbidden secret-like key or value")
    return issues


def _timestamp_issue(state: dict[str, Any], field: str, required: bool = False) -> str | None:
    value = state.get(field)
    if value is None and not required:
        return None
    if parse_utc(value) is None:
        return f"{field} is missing or is not an ISO-8601 UTC timestamp"
    return None


def _definitely_before(
    first: Any, first_uncertainty_ms: Any, first_timebase: Any,
    second: Any, second_uncertainty_ms: Any, second_timebase: Any,
) -> bool | None:
    left, right = parse_utc(first), parse_utc(second)
    if (
        left is None or right is None
        or type(first_uncertainty_ms) is not int or type(second_uncertainty_ms) is not int
        or not valid_id(first_timebase) or not valid_id(second_timebase) or first_timebase != second_timebase
    ):
        return None
    delta_ms = (right - left).total_seconds() * 1000
    uncertainty = max(0, first_uncertainty_ms) + max(0, second_uncertainty_ms)
    if delta_ms > uncertainty:
        return True
    if delta_ms < -uncertainty:
        return False
    return None


def _validate_trial_record(record: Any, protocol: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    incomplete_codes: list[str] = []
    invalid_codes: list[str] = []
    if not isinstance(record, dict):
        return {"status": "INVALID", "issues": ["trial must be a JSON object"]}
    if set(record) != TRIAL_KEYS:
        issues.append("trial fields do not match the P012 trial-record v1 format")
        (invalid_codes if set(record) - TRIAL_KEYS else incomplete_codes).append("trial_fields_mismatch")
    if contains_sensitive(record):
        issues.append("trial contains a forbidden secret-like key or value")
        invalid_codes.append("sensitive_content_rejected")
    if type(record.get("record_version")) is not int or record.get("record_version") != 1:
        issues.append("unsupported P012 trial-record version")
        invalid_codes.append("record_version_invalid")
    if not isinstance(record.get("evidence_origin"), str) or record.get("evidence_origin") not in SOURCE_CLASSES:
        issues.append("evidence origin is not a P009 source class")
        invalid_codes.append("evidence_origin_invalid")
    for key in ("trial_id", "pair_id", "observer_timebase_id", "device_timebase_id"):
        if record.get(key) is None and key != "trial_id":
            incomplete_codes.append(f"{key}_missing")
        elif not valid_id(record.get(key)):
            issues.append(f"{key} is missing or unsafe")
            invalid_codes.append(f"{key}_invalid")
    condition, route = record.get("condition_id"), record.get("route")
    repetition = record.get("repetition")
    if condition is None or route is None or repetition is None:
        incomplete_codes.append("condition_route_or_repetition_missing")
    elif not isinstance(condition, str) or condition not in CONDITIONS or not isinstance(route, str) or route not in ROUTES or type(repetition) is not int or not 1 <= repetition <= 3:
        issues.append("condition, route, or repetition is outside the preregistered design")
        invalid_codes.append("condition_route_or_repetition_invalid")
    if record.get("condition_order_index") is None:
        incomplete_codes.append("condition_order_missing")
    elif type(record.get("condition_order_index")) is not int or not 1 <= record.get("condition_order_index", 0) <= 4:
        issues.append("condition order index is invalid")
        invalid_codes.append("condition_order_invalid")
    if record.get("route_order_index") is None:
        incomplete_codes.append("route_order_missing")
    elif type(record.get("route_order_index")) is not int or record.get("route_order_index") not in (1, 2):
        issues.append("route order index is invalid")
        invalid_codes.append("route_order_invalid")
    for key in ("timing_uncertainty_ms", "device_clock_uncertainty_ms"):
        if record.get(key) is None:
            incomplete_codes.append(f"{key}_missing")
        elif type(record.get(key)) is not int or not 0 <= record.get(key, -1) <= 86_400_000:
            issues.append(f"{key} must be recorded as an integer from 0 to 86400000")
            invalid_codes.append(f"{key}_invalid")
    start, end = parse_utc(record.get("trial_started_at_utc")), parse_utc(record.get("trial_ended_at_utc"))
    if start is None or end is None:
        if record.get("trial_started_at_utc") is not None or record.get("trial_ended_at_utc") is not None:
            issues.append("trial start/end UTC timestamps are invalid")
            invalid_codes.append("trial_timestamps_invalid")
        else:
            issues.append("trial start/end UTC timestamps are missing")
            incomplete_codes.append("trial_timestamps_missing")
    elif end < start:
        issues.append("trial end UTC timestamp precedes trial start")
        invalid_codes.append("trial_timestamps_reversed")
    state = record.get("state")
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        issues.append("state fields do not match the P012 trial-record v1 format")
        (invalid_codes if isinstance(state, dict) and set(state) - STATE_KEYS else incomplete_codes).append("state_fields_mismatch")
        state = state if isinstance(state, dict) else {}
    confirmations = record.get("operator_confirmations")
    if not isinstance(confirmations, dict) or set(confirmations) != CONFIRMATION_KEYS or any(not _valid_bool_or_none(value) for value in (confirmations.values() if isinstance(confirmations, dict) else [])):
        issues.append("operator-confirmation fields are incomplete or malformed")
        (invalid_codes if isinstance(confirmations, dict) and set(confirmations) - CONFIRMATION_KEYS or isinstance(confirmations, dict) and any(not _valid_bool_or_none(value) for value in confirmations.values()) else incomplete_codes).append("operator_confirmation_shape_invalid")
        confirmations = confirmations if isinstance(confirmations, dict) else {}
    probe = record.get("probe")
    for key in CONFIRMATION_KEYS:
        value = confirmations.get(key)
        if value is not True:
            (invalid_codes if value is False else incomplete_codes).append(f"confirmation_{key}")
    expected = CONDITIONS.get(condition)
    if expected and state.get("daemon_state") in {"UNKNOWN", None}:
        incomplete_codes.append("daemon_state_unknown")
    elif expected and state.get("daemon_state") != expected[0]:
        invalid_codes.append("daemon_state_mismatch")
    if expected and state.get("assertion_state") in {"UNKNOWN", None}:
        incomplete_codes.append("assertion_state_unknown")
    elif expected and state.get("assertion_state") != expected[1]:
        invalid_codes.append("assertion_state_mismatch")
    screen = state.get("screen_lock_status")
    if screen == "UNLOCKED":
        invalid_codes.append("screen_unlocked")
    elif screen == "UNKNOWN":
        incomplete_codes.append("screen_lock_unknown")
    elif screen != "LOCKED":
        invalid_codes.append("screen_lock_status_invalid")
    if state.get("screen_lock_observed_at_utc") is None:
        incomplete_codes.append("screen_lock_timestamp_missing")
    elif (issue := _timestamp_issue(state, "screen_lock_observed_at_utc")):
        invalid_codes.append(issue)
    if state.get("charging_state") not in {"CHARGING", "NOT_CHARGING", "UNKNOWN"}:
        invalid_codes.append("charging_state_invalid")
    if state.get("battery_percent") is None:
        incomplete_codes.append("battery_level_missing")
    elif type(state.get("battery_percent")) is not int or not 0 <= state.get("battery_percent", -1) <= 100:
        invalid_codes.append("battery_level_invalid")
    if state.get("thermal_state") not in {"COOL", "WARM", "HOT", "UNKNOWN"}:
        invalid_codes.append("thermal_state_invalid")
    elif state.get("thermal_state") == "HOT":
        invalid_codes.append("thermal_stop_condition")
    elif state.get("thermal_state") == "UNKNOWN":
        incomplete_codes.append("thermal_state_unknown")
    if state.get("wifi_association") not in {"ASSOCIATED", "DISCONNECTED", "UNKNOWN"}:
        invalid_codes.append("wifi_association_invalid")
    elif state.get("wifi_association") != "ASSOCIATED":
        (invalid_codes if state.get("wifi_association") == "DISCONNECTED" else incomplete_codes).append("wifi_not_associated")
    if state.get("wifi_profile_id") is not None and not valid_id(state.get("wifi_profile_id")):
        invalid_codes.append("wifi_profile_id_unsafe")
    for route_key in ("lan_route_state", "tailscale_route_state"):
        route_state = state.get(route_key)
        if route_state not in {"AVAILABLE", "UNAVAILABLE", "UNKNOWN"}:
            invalid_codes.append(f"{route_key}_invalid")
        elif route_state == "UNKNOWN":
            incomplete_codes.append(f"{route_key}_unknown")
    if route == "LAN" and state.get("lan_route_state") == "UNAVAILABLE":
        invalid_codes.append("selected_lan_route_unavailable")
    if route == "TAILSCALE" and state.get("tailscale_route_state") == "UNAVAILABLE":
        invalid_codes.append("selected_tailscale_route_unavailable")
    quiet = state.get("quiet_interval_seconds")
    protocol_quiet = protocol.get("quiet_period", {})
    if type(quiet) is not int:
        incomplete_codes.append("quiet_interval_missing")
    elif not protocol_quiet.get("minimum_seconds", 0) <= quiet <= protocol_quiet.get("maximum_seconds", 0):
        invalid_codes.append("quiet_interval_out_of_bounds")
    if state.get("quiet_period_confirmed") is not True:
        (invalid_codes if state.get("quiet_period_confirmed") is False else incomplete_codes).append("quiet_period_not_confirmed")
    if state.get("quiet_period_contaminated") is True or state.get("quiet_incoming_probe_count", 0) not in (0, None) or state.get("quiet_operator_interaction_count", 0) not in (0, None):
        invalid_codes.append("quiet_period_contaminated")
    elif state.get("quiet_period_contaminated") is None or state.get("quiet_incoming_probe_count") is None or state.get("quiet_operator_interaction_count") is None:
        incomplete_codes.append("quiet_contamination_unrecorded")
    for count_key in ("quiet_incoming_probe_count", "quiet_operator_interaction_count"):
        count_value = state.get(count_key)
        if count_value is not None and (type(count_value) is not int or count_value < 0):
            invalid_codes.append(f"{count_key}_invalid")
    for field in ("quiet_start_at_utc", "quiet_end_at_utc"):
        issue = _timestamp_issue(state, field, required=True)
        if issue:
            incomplete_codes.append(issue)
    quiet_start = parse_utc(state.get("quiet_start_at_utc"))
    quiet_end = parse_utc(state.get("quiet_end_at_utc"))
    if quiet_start is not None and quiet_end is not None and quiet_end < quiet_start:
        invalid_codes.append("quiet_interval_timestamps_reversed")
    elif quiet_start is not None and quiet_end is not None and type(quiet) is int:
        observed_quiet = (quiet_end - quiet_start).total_seconds()
        uncertainty_ms = record.get("timing_uncertainty_ms", 0) + record.get("device_clock_uncertainty_ms", 0)
        if abs(observed_quiet - quiet) > max(2, uncertainty_ms / 500):
            invalid_codes.append("quiet_interval_duration_mismatch")
    if type(state.get("elapsed_since_previous_trial_seconds")) not in (int, float) or isinstance(state.get("elapsed_since_previous_trial_seconds"), bool) or state.get("elapsed_since_previous_trial_seconds", -1) < 0:
        incomplete_codes.append("carryover_elapsed_time_missing")
    if state.get("reboot_or_respring_since_previous") not in {True, False}:
        incomplete_codes.append("reboot_respring_state_unknown")
    if state.get("assertion_duration_seconds") is not None and (type(state.get("assertion_duration_seconds")) is not int or not 0 <= state.get("assertion_duration_seconds", -1) <= 300):
        invalid_codes.append("assertion_duration_out_of_bounds")
    if state.get("assertion_acquire_result") not in {"SUCCESS", "FAILURE", "NOT_APPLICABLE", "UNKNOWN"}:
        invalid_codes.append("assertion_acquire_result_invalid")
    if state.get("assertion_release_result") not in {"SUCCESS", "FAILURE", "NOT_APPLICABLE", "UNKNOWN"}:
        invalid_codes.append("assertion_release_result_invalid")
    if state.get("assertion_release_kind") not in {"EXPIRED", "EXPLICIT", "NONE", "UNKNOWN"}:
        invalid_codes.append("assertion_release_kind_invalid")
    if condition == "C":
        if state.get("assertion_acquire_result") == "FAILURE":
            invalid_codes.append("condition_c_acquisition_failed")
        elif state.get("assertion_acquire_result") != "SUCCESS" or state.get("assertion_acquired_at_utc") is None:
            incomplete_codes.append("condition_c_acquisition_unconfirmed")
        if state.get("assertion_release_result") != "SUCCESS" or state.get("assertion_release_confirmed_at_utc") is None:
            if state.get("assertion_release_result") == "FAILURE":
                invalid_codes.append("condition_c_release_failed")
            else:
                incomplete_codes.append("condition_c_release_unconfirmed")
        elif state.get("assertion_release_kind") not in {"EXPIRED", "EXPLICIT"}:
            incomplete_codes.append("condition_c_release_kind_unconfirmed")
        duration = state.get("assertion_duration_seconds")
        if duration is not None and duration > protocol.get("assertion", {}).get("maximum_hold_seconds", 300):
            invalid_codes.append("condition_c_hold_exceeded_protocol")
        if duration is not None and duration != protocol.get("assertion", {}).get("active_hold_seconds"):
            invalid_codes.append("condition_c_hold_duration_mismatch")
        acquire_order = _definitely_before(
            state.get("assertion_acquired_at_utc"), record.get("device_clock_uncertainty_ms", 0),
            record.get("device_timebase_id"), state.get("quiet_start_at_utc"),
            record.get("device_clock_uncertainty_ms", 0), record.get("device_timebase_id"),
        )
        if acquire_order is False:
            invalid_codes.append("condition_c_acquired_after_quiet_start")
        elif acquire_order is None:
            incomplete_codes.append("condition_c_acquisition_order_uncertain")
        if isinstance(probe, dict):
            release_order = _definitely_before(
                probe.get("ended_at_utc"), probe.get("timing_uncertainty_ms", 0), probe.get("observer_timebase_id"),
                state.get("assertion_release_confirmed_at_utc"), record.get("device_clock_uncertainty_ms", 0), record.get("device_timebase_id"),
            )
            if release_order is False:
                invalid_codes.append("condition_c_probe_after_release")
            elif release_order is None:
                incomplete_codes.append("condition_c_probe_release_order_uncertain")
    elif condition == "D":
        if state.get("assertion_release_result") == "FAILURE":
            invalid_codes.append("condition_d_release_failed")
        elif state.get("assertion_release_result") != "SUCCESS" or state.get("assertion_release_confirmed_at_utc") is None:
            incomplete_codes.append("condition_d_release_unconfirmed")
        if state.get("assertion_release_kind") not in {"EXPIRED", "EXPLICIT"}:
            incomplete_codes.append("condition_d_release_kind_unconfirmed")
        release_order = _definitely_before(
            state.get("assertion_release_confirmed_at_utc"), record.get("device_clock_uncertainty_ms", 0),
            record.get("device_timebase_id"), state.get("quiet_start_at_utc"),
            record.get("device_clock_uncertainty_ms", 0), record.get("device_timebase_id"),
        )
        if release_order is False:
            invalid_codes.append("condition_d_quiet_started_before_release_confirmation")
        elif release_order is None:
            incomplete_codes.append("condition_d_release_order_uncertain")
    elif condition in {"A", "B"}:
        if state.get("assertion_acquire_result") not in {"NOT_APPLICABLE", "UNKNOWN"}:
            invalid_codes.append("inactive_condition_has_acquisition")
        if state.get("assertion_release_result") not in {"NOT_APPLICABLE", "UNKNOWN"}:
            invalid_codes.append("inactive_condition_has_release_event")
    if condition is None or route is None or repetition is None or record.get("condition_order_index") is None or record.get("route_order_index") is None:
        incomplete_codes.append("counterbalance_order_missing")
    else:
        order_issue = validate_order(record, protocol)
        if order_issue:
            invalid_codes.append(order_issue)
    if probe is None:
        incomplete_codes.append("probe_missing")
    else:
        probe_issues = validate_probe(probe, protocol)
        issues.extend(probe_issues)
        if probe_issues:
            invalid_codes.extend(probe_issues)
        if probe.get("trial_id") != record.get("trial_id") or probe.get("condition_id") != condition or probe.get("route") != route or probe.get("repetition") != repetition:
            invalid_codes.append("probe_trial_identity_mismatch")
        if (
            probe.get("observer_timebase_id") != record.get("observer_timebase_id")
            or probe.get("timing_uncertainty_ms") != record.get("timing_uncertainty_ms")
        ):
            invalid_codes.append("probe_observer_clock_metadata_mismatch")
        if quiet is not None and probe.get("quiet_interval_seconds") != quiet:
            invalid_codes.append("probe_trial_quiet_interval_mismatch")
        if probe.get("result") == "INTERRUPTED":
            incomplete_codes.append("probe_interrupted")
    if record.get("interrupted") is True:
        incomplete_codes.append("trial_interrupted")
    elif record.get("interrupted") is not False:
        invalid_codes.append("interrupted_flag_invalid")
    if record.get("interruption_code") is not None and not valid_id(record.get("interruption_code")):
        invalid_codes.append("interruption_code_invalid")
    if not isinstance(record.get("state"), dict) or not isinstance(record.get("operator_confirmations"), dict):
        invalid_codes.extend(issues)
    issues.extend(invalid_codes)
    issues.extend(incomplete_codes)
    # Keep a stable, useful list while removing duplicate diagnostics.
    issues = list(dict.fromkeys(issues))
    if record.get("interrupted") is True or (isinstance(probe, dict) and probe.get("result") == "INTERRUPTED"):
        status = "INTERRUPTED"
    elif invalid_codes:
        status = "INVALID"
    elif incomplete_codes or any("fields do not match" in issue for issue in issues):
        status = "INCOMPLETE"
    else:
        status = "VALID"
    return {"status": status, "issues": issues}


def validate_trial(record: Any, protocol: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on malformed values while preserving missing observations as incomplete."""
    try:
        return _validate_trial_record(record, protocol)
    except (TypeError, AttributeError, KeyError, OverflowError):
        return {"status": "INVALID", "issues": ["trial contains malformed value types"]}


def validate_order(record: dict[str, Any], protocol: dict[str, Any]) -> str | None:
    repetition = record.get("repetition")
    if type(repetition) is not int or not 1 <= repetition <= 3:
        return "repetition is outside the preregistered order"
    design = protocol.get("design", {})
    try:
        expected_condition = design["condition_order_by_repetition"][repetition - 1]
        expected_route = design["route_order_by_repetition"][repetition - 1]
    except (KeyError, IndexError, TypeError):
        return "protocol counterbalance schedule is malformed"
    condition_index = record.get("condition_order_index")
    route_index = record.get("route_order_index")
    if not isinstance(expected_condition, list) or not isinstance(expected_route, list):
        return "protocol counterbalance schedule is malformed"
    condition = record.get("condition_id")
    route = record.get("route")
    if condition not in expected_condition or condition_index != expected_condition.index(condition) + 1:
        return "condition order differs from the preregistered counterbalance"
    if route not in expected_route or route_index != expected_route.index(route) + 1:
        return "route order differs from the preregistered counterbalance"
    return None


def p009_observations(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only timestamped P009-v1 event proposals; never creates a full session."""
    events: list[dict[str, Any]] = []
    state = record.get("state", {})
    confirmations = record.get("operator_confirmations", {})
    trial_id = record.get("trial_id", "unknown-trial")
    safe_trial = trial_id if valid_id(trial_id) else "unknown-trial"
    timebase = record.get("observer_timebase_id")
    uncertainty = record.get("timing_uncertainty_ms") if type(record.get("timing_uncertainty_ms")) is int else 0

    def add(event_type: str, timestamp: Any, details: dict[str, Any], *, source: str = "OPERATOR_RECORDED", base: str | None = None, uncertainty_ms: int | None = None) -> str | None:
        selected_timebase = base or timebase
        if parse_utc(timestamp) is None or not valid_id(selected_timebase):
            return None
        event_id = f"p012-{safe_trial}-{len(events) + 1}"
        events.append({
            "event_id": event_id, "sequence": len(events), "event_type": event_type,
            "timestamp": timestamp, "source": source, "timebase_id": selected_timebase,
            "uncertainty_ms": uncertainty if uncertainty_ms is None else uncertainty_ms,
            "details": {**details, "trial_id": safe_trial},
        })
        return event_id

    screen_id = None
    if state.get("screen_lock_status") == "LOCKED" and confirmations.get("screen_locked") is True:
        screen_id = add("SCREEN_LOCK", state.get("screen_lock_observed_at_utc"), {"screen_lock_status": "LOCKED"}, base=record.get("device_timebase_id"), uncertainty_ms=record.get("device_clock_uncertainty_ms"))

    acquisition_at = state.get("assertion_acquired_at_utc")
    acquire_result = state.get("assertion_acquire_result")
    if acquisition_at and acquire_result in {"SUCCESS", "FAILURE"}:
        add("ASSERTION_ACQUIRE_ATTEMPT", state.get("assertion_acquire_started_at_utc"), {}, base=record.get("device_timebase_id"), uncertainty_ms=record.get("device_clock_uncertainty_ms"))
        add("ASSERTION_ACQUIRE_SUCCESS" if acquire_result == "SUCCESS" else "ASSERTION_ACQUIRE_FAILURE", acquisition_at, {"success": acquire_result == "SUCCESS"}, base=record.get("device_timebase_id"), uncertainty_ms=record.get("device_clock_uncertainty_ms"))

    release_at = state.get("assertion_release_confirmed_at_utc")
    release_result = state.get("assertion_release_result")
    if release_at and release_result in {"SUCCESS", "FAILURE"}:
        event_type = "NATURAL_EXPIRY" if state.get("assertion_release_kind") == "EXPIRED" else "ASSERTION_RELEASE"
        add(event_type, release_at, {"success": release_result == "SUCCESS"}, base=record.get("device_timebase_id"), uncertainty_ms=record.get("device_clock_uncertainty_ms"))

    for name, event_type, timestamp_key in (
        ("battery", "BATTERY_OBSERVATION", "battery_observed_at_utc"),
        ("thermal", "THERMAL_OBSERVATION", "thermal_observed_at_utc"),
    ):
        timestamp = state.get(timestamp_key)
        if timestamp:
            details: dict[str, Any] = {"observed": True}
            if name == "battery" and type(state.get("battery_percent")) is int:
                details["level_percent"] = state["battery_percent"]
            if name == "thermal" and state.get("thermal_state") in {"COOL", "WARM", "HOT", "UNKNOWN"}:
                details["state"] = state["thermal_state"]
            add(event_type, timestamp, details, base=record.get("device_timebase_id"), uncertainty_ms=record.get("device_clock_uncertainty_ms"))

    probe = record.get("probe")
    if isinstance(probe, dict) and parse_utc(probe.get("started_at_utc")) is not None:
        success = probe.get("result") == "AUTHENTICATED_SUCCESS"
        auth_failure = probe.get("result") == "AUTHENTICATION_FAILURE"
        details = {
            "address": None,
            "ssh_authenticated": True if success else False if auth_failure else None,
            "latency_ms": probe.get("elapsed_ms"),
            "screen_lock_status": state.get("screen_lock_status", "UNKNOWN"),
            "operator_confirmed_screen_state": confirmations.get("screen_locked") is True and state.get("screen_lock_status") == "LOCKED",
        }
        if screen_id:
            details["screen_lock_event_id"] = screen_id
        if probe.get("route") == "LAN":
            result = probe.get("result")
            details["tcp_22_reachable"] = True if result in {"AUTHENTICATED_SUCCESS", "AUTHENTICATION_FAILURE", "REMOTE_COMMAND_FAILURE"} else False if result == "CONNECTION_REFUSED" else None
            event_type = "LAN_OBSERVATION"
        else:
            # SSH success is not a separate Tailscale peer-status observation.
            details["peer_connected"] = None
            details["path"] = "UNKNOWN"
            event_type = "TAILSCALE_OBSERVATION"
        add(event_type, probe.get("started_at_utc"), details, source="EXTERNAL_OBSERVER", base=probe.get("observer_timebase_id"), uncertainty_ms=probe.get("timing_uncertainty_ms"))
    return events


def condition_description(protocol: dict[str, Any], condition_id: str) -> dict[str, Any] | None:
    for condition in protocol.get("conditions", []):
        if condition.get("id") == condition_id:
            return condition
    return None
