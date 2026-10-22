#!/usr/bin/env python3
"""Plan, validate, record, and report manually operated P012 research trials."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

from p012_common import (
    CONFIRMATION_KEYS, DEFAULT_PROTOCOL, PROBE_KEYS, STATE_KEYS, TRIAL_KEYS,
    P012Error, canonical_json, contains_sensitive, load_json, record_encoding_issues,
    normalize_trial, p009_observations, valid_id, validate_protocol, validate_trial,
)


def load_protocol(path: str) -> dict[str, Any]:
    protocol = load_json(Path(path))
    issues = validate_protocol(protocol)
    if issues:
        raise P012Error("protocol validation failed: " + "; ".join(issues))
    return protocol


def default_data_root() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "ios-caffeinate" / "p012"


def _secure_data_root(path: Path) -> Path:
    if path.is_symlink():
        raise P012Error("data root must not be a symbolic link")
    try:
        existed = path.exists()
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise P012Error("data root must be a regular directory")
        if existed and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise P012Error("existing data root permissions must exclude group and other users")
    except OSError as exc:
        raise P012Error("data root could not be created safely") from exc
    return path.resolve()


def write_record(record: dict[str, Any], root: Path) -> Path:
    trial_id = record.get("trial_id")
    if not valid_id(trial_id):
        raise P012Error("trial_id must be a sanitized identifier before recording")
    safe_root = _secure_data_root(root)
    target = safe_root / f"{trial_id}.json"
    if target.parent != safe_root or target.name != f"{trial_id}.json":
        raise P012Error("record path escapes the private data directory")
    temp_name: str | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(prefix=".p012-", suffix=".tmp", dir=safe_root)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(record))
            stream.flush()
            os.fsync(stream.fileno())
        # A hard link gives exclusive creation semantics and never overwrites a prior trial.
        os.link(temp_name, target, follow_symlinks=False)
        os.unlink(temp_name)
        temp_name = None
        directory_fd = os.open(safe_root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise P012Error("a record with this trial_id already exists; records are never overwritten") from exc
    except KeyboardInterrupt:
        raise
    except OSError as exc:
        raise P012Error("record could not be written atomically") from exc
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            except OSError:
                pass
    return target


def read_operator_record(args: argparse.Namespace) -> Any:
    if args.input and args.stdin:
        raise P012Error("choose either --input or --stdin")
    if args.input:
        return load_json(Path(args.input))
    if args.stdin:
        return __import__("p012_common").parse_json_bytes(sys.stdin.buffer.read(1_048_577))
    raise P012Error("record requires --input or --stdin")


def write_report(path: Path, content: str) -> None:
    if path.is_symlink():
        raise P012Error("refusing to write through a symbolic-link report path")
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    except FileExistsError as exc:
        raise P012Error("report destination already exists; reports are never overwritten") from exc
    except OSError as exc:
        raise P012Error("report could not be written safely") from exc


def _plan(protocol: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_id": protocol["protocol_id"],
        "protocol_version": protocol["protocol_version"],
        "status": protocol["protocol_status"],
        "hardware_prerequisite": protocol["p011_prerequisite"]["current_status"],
        "conditions": [
            {"id": item["id"], "name": item["name"], "daemon_state": item["daemon_state"], "assertion_state": item["assertion_state"]}
            for item in protocol["conditions"]
        ],
        "quiet_interval_seconds": protocol["quiet_period"]["seconds"],
        "assertion_hold_seconds": protocol["assertion"]["active_hold_seconds"],
        "planned_probe_trials": protocol["design"]["total_planned_probe_trials"],
        "pairing_rule": protocol["design"]["pairing_rule"],
        "physical_series_automated": protocol["design"]["automated_physical_trial_series"],
        "interpretation": "Exploratory only; P012 does not claim sleep prevention or long-duration reliability.",
    }


def _dry_run(protocol: dict[str, Any], condition: str, route: str) -> dict[str, Any]:
    condition_row = next(item for item in protocol["conditions"] if item["id"] == condition)
    return {
        "mode": "DRY_RUN",
        "network_attempted": False,
        "device_state_changed": False,
        "condition": condition_row,
        "route": route,
        "steps": [
            "Verify the P011 installed-package and direct-recovery prerequisites before any physical trial.",
            "Manually place the daemon and assertion in the condition's registered state.",
            f"Confirm the display is locked, then leave the device quiet for {protocol['quiet_period']['seconds']} seconds with no incoming SSH probes or operator interactions.",
            "Record battery, thermal, charging, Wi-Fi, route, clock, trial-order, and carryover observations.",
            "If all stop conditions are clear, issue at most one attended route-specific SSH probe.",
            "Record actual assertion release/expiry separately; this host controller does not infer cleanup.",
        ],
    }


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL), help="versioned P012 protocol JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="show registered conditions and safeguards")
    validate = subparsers.add_parser("validate", help="validate a protocol or trial record")
    validate.add_argument("--record", help="P012 trial JSON to validate")
    dry = subparsers.add_parser("dry-run", help="print manual instructions without network or device side effects")
    dry.add_argument("--condition", choices=("A", "B", "C", "D"), required=True)
    dry.add_argument("--route", choices=("LAN", "TAILSCALE"), required=True)
    record = subparsers.add_parser("record", help="save a sanitized operator-reported record without overwriting prior evidence")
    record.add_argument("--input", help="JSON trial record (or use --stdin)")
    record.add_argument("--stdin", action="store_true", help="read the trial JSON object from standard input")
    record.add_argument("--operator-recorded", action="store_true", help="acknowledge that submitted physical states are operator-reported")
    record.add_argument("--data-root", help="private evidence directory; defaults to the user's local data directory")
    report = subparsers.add_parser("report", help="run the offline grouped analysis on records")
    report.add_argument("inputs", nargs="+", help="P012 JSON files or a directory of trial records")
    report.add_argument("--format", choices=("json", "markdown"), default="markdown")
    report.add_argument("--output", help="optional report path")
    mapping = subparsers.add_parser("map-p009", help="emit timestamped P009 v1 event proposals only")
    mapping.add_argument("--record", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _make_parser()
    args = parser.parse_args(argv)
    try:
        protocol = load_protocol(args.protocol)
        if args.command == "plan":
            print(json.dumps(_plan(protocol), sort_keys=True, indent=2))
            return 0
        if args.command == "validate":
            if not args.record:
                print(json.dumps({"protocol_status": "VALID", "protocol_version": protocol["protocol_version"]}, sort_keys=True, indent=2))
                return 0
            raw = load_json(Path(args.record))
            if not isinstance(raw, dict):
                raise P012Error("trial record must be a JSON object")
            record = normalize_trial(raw)
            result = validate_trial(record, protocol)
            print(json.dumps(result, sort_keys=True, indent=2))
            return 0 if result["status"] == "VALID" else 1
        if args.command == "dry-run":
            print(json.dumps(_dry_run(protocol, args.condition, args.route), sort_keys=True, indent=2))
            return 0
        if args.command == "record":
            if not args.operator_recorded:
                raise P012Error("--operator-recorded is required; reports must preserve their source class")
            raw = read_operator_record(args)
            if not isinstance(raw, dict):
                raise P012Error("a single trial record object is required")
            if contains_sensitive(raw):
                raise P012Error("record contains a forbidden secret-like field or value; no data was written")
            if set(raw) - TRIAL_KEYS:
                raise P012Error("record contains unsupported fields; no data was written")
            if "state" in raw and not isinstance(raw["state"], dict):
                raise P012Error("record state must be an object; no data was written")
            if "operator_confirmations" in raw and not isinstance(raw["operator_confirmations"], dict):
                raise P012Error("operator confirmations must be an object; no data was written")
            if isinstance(raw.get("state"), dict) and set(raw["state"]) - STATE_KEYS:
                raise P012Error("record contains unsupported state fields; no data was written")
            if isinstance(raw.get("operator_confirmations"), dict) and set(raw["operator_confirmations"]) - CONFIRMATION_KEYS:
                raise P012Error("record contains unsupported confirmation fields; no data was written")
            if isinstance(raw.get("probe"), dict) and set(raw["probe"]) != PROBE_KEYS:
                raise P012Error("probe contains unsupported fields; no data was written")
            record = normalize_trial(raw)
            if record.get("evidence_origin") != "OPERATOR_RECORDED":
                raise P012Error("record source must be OPERATOR_RECORDED")
            if record_encoding_issues(record):
                raise P012Error("record contains malformed or unsafe field values; no data was written")
            path = write_record(record, Path(args.data_root).expanduser() if args.data_root else default_data_root())
            validation = validate_trial(record, protocol)
            print(json.dumps({"stored": True, "path": str(path), "source_class": "OPERATOR_RECORDED", "record_status": validation["status"], "issues": validation["issues"]}, sort_keys=True, indent=2))
            return 0
        if args.command == "map-p009":
            raw = load_json(Path(args.record))
            if not isinstance(raw, dict):
                raise P012Error("trial record must be a JSON object")
            record = normalize_trial(raw)
            validation = validate_trial(record, protocol)
            result = {
                "mapping_version": 1,
                "input_record_version": record.get("record_version"),
                "evidence_origin": record.get("evidence_origin"),
                "p012_trial_status": validation["status"],
                "acceptance_decision": "NOT_EVALUATED",
                "observations": p009_observations(record),
                "limitations": [
                    "This output contains event proposals only; it is not a complete P009 acceptance session.",
                    "P009 v1 cannot encode P012 quiet-interval contamination, route order, pairing, charging, Wi-Fi association, or trial validity.",
                    "Only explicitly timestamped and explicitly observed states are mapped; human review is required.",
                ],
            }
            print(json.dumps(result, sort_keys=True, indent=2))
            return 0
        if args.command == "report":
            from p012_analyze import build_report, render_markdown, load_trial_inputs
            records, input_issues = load_trial_inputs([Path(value) for value in args.inputs], protocol)
            report_value = build_report(records, input_issues, protocol)
            output = json.dumps(report_value, sort_keys=True, indent=2) + "\n" if args.format == "json" else render_markdown(report_value)
            if args.output:
                write_report(Path(args.output), output)
            else:
                print(output, end="")
            return 0
    except P012Error as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
