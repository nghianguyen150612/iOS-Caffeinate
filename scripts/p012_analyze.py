#!/usr/bin/env python3
"""Offline P012 trial grouping and conservative exploratory comparison."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from p012_common import DEFAULT_PROTOCOL, PROBE_RESULTS, P012Error, load_json, valid_id, validate_protocol, validate_trial

SOURCE_CLASSES = {"SIMULATED", "MOCK", "CI", "DEVICE_REPORTED", "EXTERNAL_OBSERVER", "OPERATOR_RECORDED"}


def _read_container(path: Path) -> list[Any]:
    value = load_json(path)
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("records"), list):
        origin = value.get("evidence_origin")
        if not isinstance(origin, str) or origin not in SOURCE_CLASSES:
            raise P012Error("record bundle has an invalid evidence_origin")
        for record in value["records"]:
            if isinstance(record, dict) and "evidence_origin" not in record:
                record["evidence_origin"] = value["evidence_origin"]
        return value["records"]
    return [value]


def load_trial_inputs(paths: list[Path], protocol: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    for source in paths:
        if source.is_dir() and not source.is_symlink():
            children = sorted(source.glob("*.json"))
            if not children:
                issues.append(f"empty input directory: {source.name}")
            for child in children:
                try:
                    for index, item in enumerate(_read_container(child)):
                        if isinstance(item, dict):
                            records.append(item)
                        else:
                            issues.append(f"{child.name} record {index + 1} is not an object")
                except P012Error as exc:
                    issues.append(f"{child.name}: {exc}")
        elif source.is_file() or source.is_symlink():
            try:
                for index, item in enumerate(_read_container(source)):
                    if isinstance(item, dict):
                        records.append(item)
                    else:
                        issues.append(f"{source.name} record {index + 1} is not an object")
            except P012Error as exc:
                issues.append(f"{source.name}: {exc}")
        else:
            issues.append(f"input path not found: {source.name}")
        if len(records) > 10_000:
            raise P012Error("analysis input exceeds 10,000 records")
    return records, issues


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("quantile requires values")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _probe(record: dict[str, Any]) -> dict[str, Any] | None:
    candidate = record.get("probe")
    if not isinstance(candidate, dict) or not isinstance(candidate.get("result"), str) or candidate.get("result") not in PROBE_RESULTS:
        return None
    elapsed = candidate.get("elapsed_ms")
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        return None
    return candidate


def _state(record: dict[str, Any]) -> dict[str, Any]:
    candidate = record.get("state")
    return candidate if isinstance(candidate, dict) else {}


def _safe_observed(states: list[dict[str, Any]], key: str) -> list[Any]:
    values = set()
    for state in states:
        value = state.get(key)
        if isinstance(value, str) or type(value) in (int, bool) or (type(value) is float and math.isfinite(value)):
            values.add(value)
    return sorted(values, key=lambda item: (type(item).__name__, str(item)))


def _cell_key(record: dict[str, Any]) -> tuple[str, str, str, int] | None:
    origin, condition, route, repetition = (
        record.get("evidence_origin"), record.get("condition_id"), record.get("route"), record.get("repetition")
    )
    if isinstance(origin, str) and origin in SOURCE_CLASSES and isinstance(condition, str) and condition in {"A", "B", "C", "D"} and isinstance(route, str) and route in {"LAN", "TAILSCALE"} and type(repetition) is int:
        return origin, condition, route, repetition
    return None


def _clock_flags(rows: list[dict[str, Any]]) -> list[str]:
    flags = []
    if any((_probe(row) or {}).get("clock_discontinuity") is True for row in rows):
        flags.append("CLOCK_DISCONTINUITY")
    observer_timebases = {row.get("observer_timebase_id") for row in rows if valid_id(row.get("observer_timebase_id"))}
    device_timebases = {row.get("device_timebase_id") for row in rows if valid_id(row.get("device_timebase_id"))}
    if len(observer_timebases) > 1:
        flags.append("MIXED_OBSERVER_TIMEBASES")
    if len(device_timebases) > 1:
        flags.append("MIXED_DEVICE_TIMEBASES")
    if any((_probe(row) or {}).get("timing_uncertainty_ms", 0) > 5_000 for row in rows):
        flags.append("HIGH_TIMING_UNCERTAINTY")
    if any(type(row.get("device_clock_uncertainty_ms")) is int and row["device_clock_uncertainty_ms"] > 5_000 for row in rows):
        flags.append("HIGH_DEVICE_CLOCK_UNCERTAINTY")
    return flags


def _cell_summary(rows: list[dict[str, Any]], protocol: dict[str, Any], origin: str, condition: str, route: str) -> dict[str, Any]:
    matching = [row for row in rows if row.get("evidence_origin") == origin and row.get("condition_id") == condition and row.get("route") == route]
    attempts = [row for row in matching if _probe(row) is not None]
    valid_attempts = [row for row in attempts if row.get("analysis_status") == "VALID"]
    results_all = Counter((_probe(row) or {}).get("result", "UNKNOWN") for row in attempts)
    results_valid = Counter((_probe(row) or {}).get("result", "UNKNOWN") for row in valid_attempts)
    successful_all = [row for row in attempts if (_probe(row) or {}).get("result") == "AUTHENTICATED_SUCCESS"]
    successful_valid = [row for row in valid_attempts if (_probe(row) or {}).get("result") == "AUTHENTICATED_SUCCESS"]
    latencies = [float((_probe(row) or {}).get("elapsed_ms")) for row in successful_valid if type((_probe(row) or {}).get("elapsed_ms")) in (int, float)]
    failures = {key: count for key, count in sorted(results_all.items()) if key not in {"AUTHENTICATED_SUCCESS"}}
    confounders: list[str] = []
    quiet = {_state(row).get("quiet_interval_seconds") for row in matching if type(_state(row).get("quiet_interval_seconds")) is int}
    quiet.discard(None)
    if len(quiet) > 1:
        confounders.append("UNEQUAL_QUIET_WINDOWS")
    confounders.extend(_clock_flags(matching))
    if any(row.get("analysis_status") != "VALID" for row in matching):
        confounders.append("INVALID_OR_INCOMPLETE_TRIALS_PRESENT")
    if any(_state(row).get("reboot_or_respring_since_previous") is True for row in matching):
        confounders.append("REBOOT_OR_RESPRING_REPORTED")
    if any(_state(row).get("charging_state") == "UNKNOWN" or _state(row).get("thermal_state") == "UNKNOWN" for row in matching):
        confounders.append("CHARGING_OR_THERMAL_STATE_UNKNOWN")
    expected = protocol["design"]["repetitions_per_condition_per_route"]
    return {
        "condition_id": condition,
        "condition_name": next(item["name"] for item in protocol["conditions"] if item["id"] == condition),
        "route": route,
        "evidence_origin": origin,
        "daemon_state": next(item["daemon_state"] for item in protocol["conditions"] if item["id"] == condition),
        "assertion_state": next(item["assertion_state"] for item in protocol["conditions"] if item["id"] == condition),
        "trials_total": len(matching),
        "trials_valid": sum(row.get("analysis_status") == "VALID" for row in matching),
        "trials_invalid": sum(row.get("analysis_status") == "INVALID" for row in matching),
        "trials_incomplete": sum(row.get("analysis_status") == "INCOMPLETE" for row in matching),
        "trials_interrupted": sum(row.get("analysis_status") == "INTERRUPTED" for row in matching),
        "planned_repetitions": expected,
        "missing_repetitions": max(0, expected - len({row.get("repetition") for row in matching if type(row.get("repetition")) is int})),
        "attempted_probes": len(attempts),
        "authenticated_successes": len(successful_all),
        "success_percent": round(100 * len(successful_all) / len(attempts), 2) if attempts else None,
        "valid_attempted_probes": len(valid_attempts),
        "valid_authenticated_successes": len(successful_valid),
        "valid_success_percent": round(100 * len(successful_valid) / len(valid_attempts), 2) if valid_attempts else None,
        "failure_categories": failures,
        "valid_failure_categories": {key: count for key, count in sorted(results_valid.items()) if key != "AUTHENTICATED_SUCCESS"},
        "successful_latency_ms": {
            "n": len(latencies),
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "p25": round(_quantile(latencies, 0.25), 3) if latencies else None,
            "p75": round(_quantile(latencies, 0.75), 3) if latencies else None,
            "min": round(min(latencies), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
            "measurement": "host monotonic SSH command elapsed time; successful probes only",
        },
        "confounder_flags": sorted(set(confounders)),
        "evidence_strength": "EXPLORATORY_ONLY",
    }


def _comparison(rows: list[dict[str, Any]], origin: str, route: str, left: str, right: str) -> dict[str, Any]:
    left_rows = {row.get("repetition"): row for row in rows if row.get("evidence_origin") == origin and row.get("condition_id") == left and row.get("route") == route and row.get("analysis_status") == "VALID" and _probe(row)}
    right_rows = {row.get("repetition"): row for row in rows if row.get("evidence_origin") == origin and row.get("condition_id") == right and row.get("route") == route and row.get("analysis_status") == "VALID" and _probe(row)}
    matched = sorted(set(left_rows) & set(right_rows))
    lsuccess = [(_probe(left_rows[key]) or {}).get("result") == "AUTHENTICATED_SUCCESS" for key in matched]
    rsuccess = [(_probe(right_rows[key]) or {}).get("result") == "AUTHENTICATED_SUCCESS" for key in matched]
    flags: list[str] = []
    if len(matched) < 3:
        flags.append("FEWER_THAN_THREE_VALID_MATCHED_REPETITIONS")
    pair_rows = [left_rows[key] for key in matched] + [right_rows[key] for key in matched]
    flags.extend(_clock_flags(pair_rows))
    for key in matched:
        lrow, rrow = left_rows[key], right_rows[key]
        lstate, rstate = _state(lrow), _state(rrow)
        lp, rp = _probe(lrow) or {}, _probe(rrow) or {}
        if lstate.get("quiet_interval_seconds") != rstate.get("quiet_interval_seconds"):
            flags.append("UNEQUAL_QUIET_WINDOWS")
        if lp.get("timeout_seconds") != rp.get("timeout_seconds"):
            flags.append("UNEQUAL_PROBE_TIMEOUTS")
        if lrow.get("timing_uncertainty_ms") != rrow.get("timing_uncertainty_ms"):
            flags.append("UNEQUAL_CLOCK_UNCERTAINTY")
        if lstate.get("charging_state") != rstate.get("charging_state"):
            flags.append("CHARGING_STATE_CHANGED")
        if lstate.get("thermal_state") != rstate.get("thermal_state"):
            flags.append("THERMAL_STATE_CHANGED")
        if lstate.get("wifi_profile_id") != rstate.get("wifi_profile_id") or lstate.get("wifi_association") != rstate.get("wifi_association"):
            flags.append("WIFI_STATE_CHANGED")
        if type(lstate.get("battery_percent")) is int and type(rstate.get("battery_percent")) is int and abs(lstate["battery_percent"] - rstate["battery_percent"]) > 5:
            flags.append("BATTERY_LEVEL_CHANGED_OVER_FIVE_POINTS")
        if lstate.get("reboot_or_respring_since_previous") != rstate.get("reboot_or_respring_since_previous"):
            flags.append("REBOOT_OR_RESPRING_STATE_DIFFERS")
    left_successes, right_successes = sum(lsuccess), sum(rsuccess)
    n = len(matched)
    left_rate = round(100 * left_successes / n, 2) if n else None
    right_rate = round(100 * right_successes / n, 2) if n else None
    equal_critical_windows = not any(flag in flags for flag in ("UNEQUAL_QUIET_WINDOWS", "UNEQUAL_PROBE_TIMEOUTS", "MIXED_OBSERVER_TIMEBASES", "CLOCK_DISCONTINUITY"))
    if n == 0:
        outcome = "NOT_IDENTIFIABLE"
        interpretation = "No matched, valid route-specific observations support this comparison."
    elif not equal_critical_windows:
        outcome = "NOT_IDENTIFIABLE"
        interpretation = "Unequal observation windows or timebase problems prevent an interpretable comparison."
    elif n < 3:
        outcome = "INSUFFICIENT_DATA"
        if left_rate == 100 and right_rate == 100:
            interpretation = f"Both conditions had 100% authenticated SSH success in the {n} observed matched trial(s); the tested conditions did not demonstrate an observable difference. The sample is below the preregistered exploratory repetition count, so the comparison remains inconclusive."
        else:
            interpretation = "The matched sample is below the preregistered exploratory repetition count."
    elif left_rate == 100 and right_rate == 100:
        outcome = "NO_OBSERVABLE_DIFFERENCE"
        interpretation = "Both conditions had 100% authenticated SSH success in the observed matched trials; the tested conditions did not demonstrate an observable difference. This does not establish equivalence or prove sleep prevention."
    elif right_rate is not None and left_rate is not None and right_rate > left_rate:
        outcome = "OBSERVED_ASSOCIATION"
        interpretation = f"Condition {right} showed a higher observed authenticated-SSH success percentage than {left}; this association is not causal evidence. Battery, thermal, route, operator, clock, carryover, and single-device alternatives remain."
    elif right_rate is not None and left_rate is not None and right_rate < left_rate:
        outcome = "OBSERVED_ASSOCIATION"
        interpretation = f"Condition {right} showed a lower observed authenticated-SSH success percentage than {left}; this association is not causal evidence."
    else:
        outcome = "INCONCLUSIVE"
        interpretation = "The observed outcomes do not establish a stable difference; do not infer causal improvement."
    if flags:
        interpretation += " Confounder flags require review: " + ", ".join(sorted(set(flags))) + "."
        if outcome not in {"NO_OBSERVABLE_DIFFERENCE", "NOT_IDENTIFIABLE", "INSUFFICIENT_DATA"}:
            outcome = "INCONCLUSIVE"
    return {
        "comparison": f"{left}_vs_{right}",
        "route": route,
        "evidence_origin": origin,
        "matched_repetitions": matched,
        "matched_pair_count": n,
        "left_successes": left_successes,
        "left_success_percent": left_rate,
        "right_successes": right_successes,
        "right_success_percent": right_rate,
        "outcome": outcome,
        "data_strength": "EXPLORATORY_ONLY" if n >= 3 else "INSUFFICIENT_DATA",
        "confounder_flags": sorted(set(flags)),
        "interpretation": interpretation,
        "statistical_significance_claimed": False,
    }


def _route_comparison(rows: list[dict[str, Any]], origin: str, condition: str) -> dict[str, Any]:
    route_rows: dict[str, dict[tuple[str, int], dict[str, Any]]] = {"LAN": {}, "TAILSCALE": {}}
    for row in rows:
        if row.get("evidence_origin") != origin or row.get("condition_id") != condition or row.get("analysis_status") != "VALID" or not _probe(row):
            continue
        pair_id, repetition = row.get("pair_id"), row.get("repetition")
        route = row.get("route")
        if valid_id(pair_id) and type(repetition) is int and isinstance(route, str) and route in route_rows:
            route_rows[route][(pair_id, repetition)] = row
    matched = sorted(set(route_rows["LAN"]) & set(route_rows["TAILSCALE"]))
    lan_rows = [route_rows["LAN"][key] for key in matched]
    tailscale_rows = [route_rows["TAILSCALE"][key] for key in matched]
    unmatched_lan = sorted(set(route_rows["LAN"]) - set(route_rows["TAILSCALE"]))
    unmatched_tailscale = sorted(set(route_rows["TAILSCALE"]) - set(route_rows["LAN"]))
    lan_success = [(_probe(row) or {}).get("result") == "AUTHENTICATED_SUCCESS" for row in lan_rows]
    tailscale_success = [(_probe(row) or {}).get("result") == "AUTHENTICATED_SUCCESS" for row in tailscale_rows]
    flags: list[str] = []
    if len(matched) < 3:
        flags.append("FEWER_THAN_THREE_VALID_MATCHED_REPETITIONS")
    if unmatched_lan or unmatched_tailscale:
        flags.append("UNMATCHED_ROUTE_PAIRS")
    flags.extend(_clock_flags(lan_rows + tailscale_rows))
    for lan, tailscale in zip(lan_rows, tailscale_rows):
        ls, ts = _state(lan), _state(tailscale)
        lp, tp = _probe(lan) or {}, _probe(tailscale) or {}
        if ls.get("quiet_interval_seconds") != ts.get("quiet_interval_seconds"):
            flags.append("UNEQUAL_QUIET_WINDOWS")
        if lp.get("timeout_seconds") != tp.get("timeout_seconds"):
            flags.append("UNEQUAL_PROBE_TIMEOUTS")
        if lp.get("timing_uncertainty_ms") != tp.get("timing_uncertainty_ms"):
            flags.append("UNEQUAL_CLOCK_UNCERTAINTY")
        if ls.get("charging_state") != ts.get("charging_state"):
            flags.append("CHARGING_STATE_CHANGED")
        if ls.get("thermal_state") != ts.get("thermal_state"):
            flags.append("THERMAL_STATE_CHANGED")
        if ls.get("battery_percent") is not None and ts.get("battery_percent") is not None and abs(ls["battery_percent"] - ts["battery_percent"]) > 5:
            flags.append("BATTERY_LEVEL_CHANGED_OVER_FIVE_POINTS")
        if ls.get("reboot_or_respring_since_previous") != ts.get("reboot_or_respring_since_previous"):
            flags.append("REBOOT_OR_RESPRING_STATE_DIFFERS")
    n = len(matched)
    lan_successes, tailscale_successes = sum(lan_success), sum(tailscale_success)
    lan_rate = round(100 * lan_successes / n, 2) if n else None
    tailscale_rate = round(100 * tailscale_successes / n, 2) if n else None
    equal_critical_windows = not any(flag in flags for flag in (
        "UNEQUAL_QUIET_WINDOWS", "UNEQUAL_PROBE_TIMEOUTS", "UNEQUAL_CLOCK_UNCERTAINTY",
        "MIXED_OBSERVER_TIMEBASES", "MIXED_DEVICE_TIMEBASES", "CLOCK_DISCONTINUITY",
    ))
    if n == 0:
        outcome = "NOT_IDENTIFIABLE"
        interpretation = "No matched valid LAN/Tailscale observations support this route comparison."
    elif not equal_critical_windows:
        outcome = "NOT_IDENTIFIABLE"
        interpretation = "Unequal observation windows or clock metadata prevent an interpretable route comparison."
    elif n < 3:
        outcome = "INSUFFICIENT_DATA"
        if lan_rate == 100 and tailscale_rate == 100:
            interpretation = f"Both routes had 100% authenticated SSH success in the {n} matched observation(s); the tested routes did not demonstrate an observable difference. The sample is below the preregistered exploratory repetition count, so the route comparison remains inconclusive."
        else:
            interpretation = "The matched route sample is below the preregistered exploratory repetition count."
    elif lan_rate == 100 and tailscale_rate == 100:
        outcome = "NO_OBSERVABLE_DIFFERENCE"
        interpretation = "Both routes had 100% authenticated SSH success in the matched observations; the tested routes did not demonstrate an observable difference. This does not establish route equivalence or long-duration reliability."
    elif lan_rate != tailscale_rate:
        outcome = "OBSERVED_ASSOCIATION"
        interpretation = "The observed LAN and Tailscale success percentages differ in the matched trials; route, host networking, radio state, and single-device alternatives remain, so this is not causal or general reliability evidence."
    else:
        outcome = "INCONCLUSIVE"
        interpretation = "The route-specific observations do not establish a stable difference."
    if flags:
        interpretation += " Confounder flags require review: " + ", ".join(sorted(set(flags))) + "."
        if outcome not in {"NO_OBSERVABLE_DIFFERENCE", "NOT_IDENTIFIABLE", "INSUFFICIENT_DATA"}:
            outcome = "INCONCLUSIVE"
    return {
        "condition_id": condition,
        "evidence_origin": origin,
        "route_comparison": "LAN_vs_TAILSCALE",
        "matched_pairs": [{"pair_id": pair_id, "repetition": repetition} for pair_id, repetition in matched],
        "unmatched_lan_pairs": [{"pair_id": pair_id, "repetition": repetition} for pair_id, repetition in unmatched_lan],
        "unmatched_tailscale_pairs": [{"pair_id": pair_id, "repetition": repetition} for pair_id, repetition in unmatched_tailscale],
        "matched_pair_count": n,
        "lan_successes": lan_successes,
        "lan_success_percent": lan_rate,
        "tailscale_successes": tailscale_successes,
        "tailscale_success_percent": tailscale_rate,
        "outcome": outcome,
        "data_strength": "EXPLORATORY_ONLY" if n >= 3 else "INSUFFICIENT_DATA",
        "confounder_flags": sorted(set(flags)),
        "interpretation": interpretation,
        "statistical_significance_claimed": False,
    }


def _source_sha() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=2, check=False)
        return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN"


def build_report(records: list[dict[str, Any]], input_issues: list[str], protocol: dict[str, Any], source_sha: str | None = None) -> dict[str, Any]:
    protocol_issues = validate_protocol(protocol)
    if protocol_issues:
        raise P012Error("analysis refused invalid protocol: " + "; ".join(protocol_issues))
    seen: dict[str, int] = Counter()
    seen_cells: dict[tuple[str, str, str, int], int] = Counter()
    for record in records:
        trial_id = record.get("trial_id")
        if isinstance(trial_id, str):
            seen[trial_id] += 1
        cell = _cell_key(record)
        if cell is not None:
            seen_cells[cell] += 1
    assessed: list[dict[str, Any]] = []
    for record in records:
        assessment = validate_trial(record, protocol)
        row = dict(record)
        row["analysis_status"] = assessment["status"]
        row["analysis_issues"] = list(assessment["issues"])
        if isinstance(row.get("trial_id"), str) and seen.get(row["trial_id"], 0) > 1:
            row["analysis_status"] = "INVALID"
            row["analysis_issues"].append("duplicate_trial_id")
        cell = _cell_key(row)
        if cell is not None and seen_cells.get(cell, 0) > 1:
            row["analysis_status"] = "INVALID"
            row["analysis_issues"].append("duplicate_repetition_cell")
        assessed.append(row)
    origins = sorted({row.get("evidence_origin") for row in assessed if isinstance(row.get("evidence_origin"), str) and row.get("evidence_origin") in SOURCE_CLASSES})
    groups = []
    comparisons = []
    route_comparisons = []
    for origin in origins:
        for condition in ("A", "B", "C", "D"):
            for route in ("LAN", "TAILSCALE"):
                groups.append(_cell_summary(assessed, protocol, origin, condition, route))
        for route in ("LAN", "TAILSCALE"):
            for left, right in (("A", "C"), ("B", "C"), ("C", "D")):
                comparisons.append(_comparison(assessed, origin, route, left, right))
        for condition in ("A", "B", "C", "D"):
            route_comparisons.append(_route_comparison(assessed, origin, condition))
    all_attempts = [row for row in assessed if _probe(row) is not None]
    valid = sum(row.get("analysis_status") == "VALID" for row in assessed)
    invalid = sum(row.get("analysis_status") == "INVALID" for row in assessed)
    incomplete = sum(row.get("analysis_status") == "INCOMPLETE" for row in assessed)
    interrupted = sum(row.get("analysis_status") == "INTERRUPTED" for row in assessed)
    p015_inputs = []
    for group in groups:
        cell = [row for row in assessed if row.get("evidence_origin") == group["evidence_origin"] and row.get("condition_id") == group["condition_id"] and row.get("route") == group["route"]]
        states = [_state(row) for row in cell]
        p015_inputs.append({
            "condition_id": group["condition_id"], "route": group["route"], "evidence_origin": group["evidence_origin"],
            "sample_count": group["valid_attempted_probes"], "success_percent": group["valid_success_percent"],
            "median_successful_ssh_elapsed_ms": group["successful_latency_ms"]["median"],
            "failure_categories": group["valid_failure_categories"],
            "quiet_interval_seconds_observed": _safe_observed(states, "quiet_interval_seconds"),
            "daemon_states_observed": _safe_observed(states, "daemon_state"),
            "assertion_states_observed": _safe_observed(states, "assertion_state"),
            "battery_percent_observed": _safe_observed(states, "battery_percent"),
            "charging_states_observed": _safe_observed(states, "charging_state"),
            "thermal_states_observed": _safe_observed(states, "thermal_state"),
            "route_states_observed": _safe_observed(states, "lan_route_state" if group["route"] == "LAN" else "tailscale_route_state"),
            "release_confirmed_trials": sum(state.get("assertion_release_result") == "SUCCESS" for state in states),
            "human_review_status": "NOT_REVIEWED",
            "policy_use": "research input only; no automatic policy recommendation",
        })
    return {
        "report_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_version": protocol["protocol_version"],
        "source_commit_sha": source_sha or _source_sha(),
        "evidence_origins": origins,
        "interpretation_scope": "offline descriptive analysis; LAN and Tailscale remain separate; no causal claim or sleep-prevention claim",
        "counts": {
            "records": len(assessed), "valid_trials": valid, "invalid_trials": invalid,
            "incomplete_trials": incomplete, "interrupted_trials": interrupted,
            "attempted_probes": len(all_attempts), "input_errors": len(input_issues),
        },
        "input_issues": sorted(input_issues),
        "trial_outcomes": [
            {"trial_id": row.get("trial_id") if valid_id(row.get("trial_id")) else None,
             "condition_id": row.get("condition_id") if isinstance(row.get("condition_id"), str) and row.get("condition_id") in {"A", "B", "C", "D"} else None,
             "route": row.get("route") if isinstance(row.get("route"), str) and row.get("route") in {"LAN", "TAILSCALE"} else None,
             "repetition": row.get("repetition") if type(row.get("repetition")) is int else None,
             "evidence_origin": row.get("evidence_origin") if isinstance(row.get("evidence_origin"), str) and row.get("evidence_origin") in SOURCE_CLASSES else None,
             "status": row.get("analysis_status"), "issues": sorted(set(row.get("analysis_issues", []))),
             "probe_result": (_probe(row) or {}).get("result")}
            for row in sorted(assessed, key=lambda item: (str(item.get("evidence_origin")), str(item.get("condition_id")), str(item.get("route")), str(item.get("repetition")), str(item.get("trial_id"))))
        ],
        "groups": groups,
        "comparisons": comparisons,
        "route_comparisons": route_comparisons,
        "evidence_strength": {
            "classification": "EXPLORATORY_ONLY",
            "strong_evidence_established": False,
            "uncertainty_intervals": "Not calculated: the small repeated single-device design does not justify independent-sample assumptions.",
            "statistical_significance_claimed": False,
            "correlated_observations": "Trials share one device and may share day, operator, radio, daemon, battery, thermal, and carryover conditions; do not count probes as independent Bernoulli evidence.",
        },
        "p015_policy_inputs": {
            "status": "EXPOSED_FOR_FUTURE_REVIEW_ONLY",
            "fields": p015_inputs,
            "note": "P012 does not implement or recommend a Server Mode policy; no automatic policy recommendation is produced. Human review and more evidence remain required.",
        },
        "hardware_claims": {
            "assertion_prevents_sleep": "NOT_ESTABLISHED",
            "daemon_only_improves_reachability": "NOT_ESTABLISHED",
            "post_expiry_effect": "NOT_ESTABLISHED",
            "long_duration_server_reliability": "NOT_VALIDATED",
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# P012 Offline Analysis Report", "",
        f"Evidence origins: {', '.join(report['evidence_origins']) if report['evidence_origins'] else 'none'}  ",
        f"Source SHA: `{report['source_commit_sha']}`  ",
        f"Trials: {report['counts']['records']} total; {report['counts']['valid_trials']} valid; {report['counts']['invalid_trials']} invalid; {report['counts']['incomplete_trials']} incomplete; {report['counts']['interrupted_trials']} interrupted.",
        "", "## Condition and route summaries", "",
        "| Origin | Condition | Route | Valid/total trials | All probes | Authenticated (all) | All success | Valid successes | Valid success | Median latency (ms) | Failures (all) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["groups"]:
        latency = row["successful_latency_ms"]["median"]
        lines.append(
            f"| {row['evidence_origin']} | {row['condition_id']} — {row['condition_name']} | {row['route']} | "
            f"{row['trials_valid']}/{row['trials_total']} | {row['attempted_probes']} | {row['authenticated_successes']} | "
            f"{row['success_percent'] if row['success_percent'] is not None else 'n/a'}% | "
            f"{row['valid_authenticated_successes']} | "
            f"{row['valid_success_percent'] if row['valid_success_percent'] is not None else 'n/a'}% | "
            f"{latency if latency is not None else 'n/a'} | {json.dumps(row['failure_categories'], sort_keys=True)} |"
        )
    lines.extend(["", "## Preregistered comparisons", "", "| Origin | Route | Comparison | Matched n | Outcome | Interpretation |", "|---|---|---|---:|---|---|"])
    for row in report["comparisons"]:
        lines.append(f"| {row['evidence_origin']} | {row['route']} | {row['comparison']} | {row['matched_pair_count']} | {row['outcome']} | {row['interpretation']} |")
    lines.extend(["", "## Matched LAN versus Tailscale summaries", "", "| Origin | Condition | Matched pairs | LAN success | Tailscale success | Outcome | Interpretation |", "|---|---|---:|---:|---:|---|---|"])
    for row in report["route_comparisons"]:
        lines.append(
            f"| {row['evidence_origin']} | {row['condition_id']} | {row['matched_pair_count']} | "
            f"{row['lan_success_percent'] if row['lan_success_percent'] is not None else 'n/a'}% | "
            f"{row['tailscale_success_percent'] if row['tailscale_success_percent'] is not None else 'n/a'}% | "
            f"{row['outcome']} | {row['interpretation']} |"
        )
    lines.extend([
        "", "## Limits", "",
        "LAN and Tailscale are analyzed separately. SSH attempts are not treated as independent samples; the report makes no statistical-significance, causal-improvement, OS-suspend, deep-sleep, or long-duration reliability claim.",
        "P012 comparisons remain exploratory and require human review of the underlying operator records.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", help="P012 JSON evidence files or directories; omitted means an empty analysis")
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", help="optional report destination")
    parser.add_argument("--source-sha", help="exact checked-out source SHA for deterministic CI artifacts")
    args = parser.parse_args(argv)
    try:
        protocol = load_json(Path(args.protocol))
        protocol_issues = validate_protocol(protocol)
        if protocol_issues:
            raise P012Error("analysis refused invalid protocol: " + "; ".join(protocol_issues))
        records, issues = load_trial_inputs([Path(path) for path in args.inputs], protocol) if args.inputs else ([], ["no trial data supplied"])
        report = build_report(records, issues, protocol, source_sha=args.source_sha)
        content = json.dumps(report, sort_keys=True, indent=2) + "\n" if args.format == "json" else render_markdown(report)
        if args.output:
            destination = Path(args.output)
            if destination.is_symlink():
                raise P012Error("refusing to write through a symbolic-link report path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as stream:
                stream.write(content)
        else:
            print(content, end="")
        return 0
    except P012Error as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
