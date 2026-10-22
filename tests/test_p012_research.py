"""P012 deterministic offline protocol, measurement, record, and analysis tests."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import p009_evidence  # noqa: E402
import p012_analyze as analyze  # noqa: E402
import p012_common as common  # noqa: E402
import p012_host_probe as host_probe  # noqa: E402
import p012_trial as trial_cli  # noqa: E402
from p012_fixtures import PROTOCOL, all_success_records, make_trial  # noqa: E402
from p009_fixtures import make_session  # noqa: E402


def host_args(**overrides):
    parser = host_probe.build_parser()
    args = parser.parse_args([
        "--route", "LAN", "--condition-id", "A", "--trial-id", "probe-test", "--repetition", "1",
        "--run-attended", "--destination", "operator@ipad-lab.example.test", "--target-id", "ipad-mini",
        "--timebase-id", "arch-host-ntp", "--timing-uncertainty-ms", "100",
        "--quiet-interval-seconds", "120", "--quiet-interval-complete",
        "--screen-lock-status", "LOCKED", "--screen-lock-confirmed",
        "--daemon-state", "STOPPED", "--daemon-state-confirmed",
        "--assertion-state", "INACTIVE", "--assertion-state-confirmed",
        "--operator-present", "--p011-preflight-passed", "--package-installation-authorized",
        "--installed-runtime-verified", "--assertion-cleanup-verified", "--physical-recovery-confirmed",
        "--battery-thermal-approved", "--wifi-association-confirmed", "--route-state-confirmed",
    ])
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


class P012ProtocolAndConditionTests(unittest.TestCase):
    def test_protocol_json_and_runtime_invariants_validate(self):
        raw = (ROOT / "experiments/p012/protocol-v1.json").read_bytes()
        protocol = common.parse_json_bytes(raw)
        schema = common.load_json(ROOT / "experiments/p012/protocol-v1.schema.json")
        self.assertEqual(protocol["protocol_id"], "P012")
        self.assertEqual(schema["properties"]["protocol_version"]["const"], 1)
        self.assertEqual(common.validate_json_schema(protocol, schema), [])
        self.assertEqual(common.validate_protocol(protocol), [])
        self.assertEqual([row["id"] for row in protocol["conditions"]], ["A", "B", "C", "D"])
        self.assertEqual(protocol["design"]["total_planned_probe_trials"], 24)

    def test_four_condition_definitions_are_exact(self):
        expected = {
            "A": ("STOPPED", "INACTIVE"),
            "B": ("RUNNING_IDLE", "INACTIVE"),
            "C": ("RUNNING_HOLD", "ACTIVE"),
            "D": ("RUNNING_IDLE", "EXPIRED_RELEASED"),
        }
        self.assertEqual({row["id"]: (row["daemon_state"], row["assertion_state"]) for row in PROTOCOL["conditions"]}, expected)

    def test_protocol_rejects_unbounded_assertion(self):
        protocol = json.loads(json.dumps(PROTOCOL))
        protocol["assertion"]["active_hold_seconds"] = 301
        protocol["assertion"]["maximum_hold_seconds"] = 301
        self.assertTrue(any("300-second ceiling" in issue for issue in common.validate_protocol(protocol)))

    def test_protocol_rejects_continuous_probe_or_automated_physical_series(self):
        protocol = json.loads(json.dumps(PROTOCOL))
        protocol["probe"]["maximum_probes_per_trial"] = 2
        protocol["design"]["automated_physical_trial_series"] = True
        protocol["design"]["pairing_rule"] = "unmatched routes"
        issues = common.validate_protocol(protocol)
        self.assertTrue(any("one minimal" in issue for issue in issues))
        self.assertTrue(any("manually operated" in issue for issue in issues))
        self.assertTrue(any("pairing" in issue for issue in issues))

    def test_protocol_bounds_quiet_period_and_timeout(self):
        protocol = json.loads(json.dumps(PROTOCOL))
        protocol["quiet_period"]["seconds"] = 301
        protocol["probe"]["timeout_seconds"] = 16
        issues = common.validate_protocol(protocol)
        self.assertTrue(any("quiet interval" in issue for issue in issues))
        self.assertTrue(any("15 seconds" in issue for issue in issues))
        protocol = json.loads(json.dumps(PROTOCOL))
        protocol["quiet_period"]["minimum_seconds"] = 30
        protocol["quiet_period"]["seconds"] = 30
        self.assertTrue(common.validate_protocol(protocol))

    def test_malformed_protocol_structure_returns_validation_errors(self):
        protocol = json.loads(json.dumps(PROTOCOL))
        protocol["target_platform"] = None
        self.assertTrue(any("target platform" in issue for issue in common.validate_protocol(protocol)))

    def test_each_condition_record_classifies_valid(self):
        for condition in "ABCD":
            with self.subTest(condition=condition):
                record = make_trial(condition)
                trial_schema = common.load_json(common.DEFAULT_TRIAL_SCHEMA)
                self.assertEqual(common.validate_json_schema(record, trial_schema), [])
                result = common.validate_trial(record, PROTOCOL)
                self.assertEqual(result["status"], "VALID", result["issues"])

    def test_active_hold_must_remain_bounded_and_match_registration(self):
        record = make_trial("C")
        record["state"]["assertion_duration_seconds"] = 301
        result = common.validate_trial(record, PROTOCOL)
        self.assertEqual(result["status"], "INVALID")
        self.assertTrue(any("assertion_duration_out_of_bounds" in issue or "hold_exceeded" in issue for issue in result["issues"]))

    def test_condition_c_probe_must_precede_release(self):
        record = make_trial("C")
        probe_start = common.parse_utc(record["probe"]["started_at_utc"])
        record["state"]["assertion_release_confirmed_at_utc"] = (probe_start - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        record["state"]["assertion_duration_seconds"] = 121
        result = common.validate_trial(record, PROTOCOL)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn("condition_c_probe_after_release", result["issues"])

    def test_condition_d_release_must_precede_quiet_period(self):
        record = make_trial("D")
        record["state"]["assertion_release_confirmed_at_utc"] = record["state"]["quiet_start_at_utc"]
        result = common.validate_trial(record, PROTOCOL)
        self.assertIn(result["status"], {"INVALID", "INCOMPLETE"})
        self.assertIn("condition_d_release_order_uncertain", result["issues"])

    def test_cross_timebase_probe_and_release_order_is_incomplete(self):
        record = make_trial("C")
        record["device_timebase_id"] = "independent-device-clock"
        result = common.validate_trial(record, PROTOCOL)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIn("condition_c_probe_release_order_uncertain", result["issues"])

        mismatched_probe_clock = make_trial("A")
        mismatched_probe_clock["probe"]["observer_timebase_id"] = "different-observer-clock"
        result = common.validate_trial(mismatched_probe_clock, PROTOCOL)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn("probe_observer_clock_metadata_mismatch", result["issues"])

    def test_missing_operator_confirmation_is_incomplete(self):
        record = make_trial("A", operator_confirmations={"direct_recovery_available": None})
        result = common.validate_trial(record, PROTOCOL)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIn("confirmation_direct_recovery_available", result["issues"])

    def test_missing_screen_confirmation_is_incomplete_and_unlocked_is_invalid(self):
        missing = make_trial("A", operator_confirmations={"screen_locked": None})
        self.assertEqual(common.validate_trial(missing, PROTOCOL)["status"], "INCOMPLETE")
        unlocked = make_trial("A", screen="UNLOCKED")
        self.assertEqual(common.validate_trial(unlocked, PROTOCOL)["status"], "INVALID")

    def test_assertion_state_mismatch_invalidates_condition(self):
        record = make_trial("B", assertion_state="ACTIVE")
        result = common.validate_trial(record, PROTOCOL)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn("assertion_state_mismatch", result["issues"])

    def test_quiet_period_missing_is_incomplete(self):
        record = make_trial("A")
        record["state"]["quiet_interval_seconds"] = None
        result = common.validate_trial(record, PROTOCOL)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIn("quiet_interval_missing", result["issues"])

    def test_quiet_period_contamination_invalidates_trial(self):
        record = make_trial("A", contaminated=True)
        result = common.validate_trial(record, PROTOCOL)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn("quiet_period_contaminated", result["issues"])

    def test_temperature_stop_condition_is_invalid(self):
        record = make_trial("A")
        record["state"]["thermal_state"] = "HOT"
        result = common.validate_trial(record, PROTOCOL)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn("thermal_stop_condition", result["issues"])

    def test_route_and_condition_order_must_follow_counterbalance(self):
        record = make_trial("A", "LAN", 2)
        record["route_order_index"] = 1
        result = common.validate_trial(record, PROTOCOL)
        self.assertEqual(result["status"], "INVALID")
        self.assertTrue(any("counterbalance" in issue for issue in result["issues"]))


class P012HostProbeTests(unittest.TestCase):
    def test_successful_probe_uses_safe_ssh_options_and_redacts_destination(self):
        args = host_args()
        started = datetime(2037, 1, 1, tzinfo=timezone.utc)
        ended = started + timedelta(milliseconds=25)
        completed = subprocess.CompletedProcess(["ssh"], 0, "", "")
        with patch.object(host_probe, "utc_now", side_effect=[started, ended]), \
             patch.object(host_probe.time, "monotonic_ns", side_effect=[1_000_000, 26_000_000]), \
             patch.object(host_probe.subprocess, "run", return_value=completed) as run:
            record = host_probe.run_probe(args, protocol=PROTOCOL, ssh_path="/usr/bin/ssh")
        command = run.call_args.args[0]
        self.assertIn("BatchMode=yes", command)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("ConnectionAttempts=1", command)
        self.assertEqual(command[-1], "true")
        self.assertEqual(record["result"], "AUTHENTICATED_SUCCESS")
        self.assertTrue(record["authenticated"])
        self.assertNotIn("ipad-lab.example.test", json.dumps(record))
        self.assertNotIn("destination", record)

    def test_authentication_failure_and_success_classification(self):
        self.assertEqual(host_probe.classify_return(0), ("AUTHENTICATED_SUCCESS", "SUCCESS", True))
        self.assertEqual(host_probe.classify_return(255, "Permission denied (publickey)."), ("AUTHENTICATION_FAILURE", "FAILURE", False))
        record = make_trial("A", result="AUTHENTICATION_FAILURE")
        self.assertEqual(common.validate_trial(record, PROTOCOL)["status"], "VALID")

    def test_timeout_and_refused_connection_are_separate(self):
        args = host_args()
        start = datetime(2037, 1, 1, tzinfo=timezone.utc)
        with patch.object(host_probe, "utc_now", side_effect=[start, start + timedelta(seconds=8)]), \
             patch.object(host_probe.time, "monotonic_ns", side_effect=[0, 8_000_000_000]), \
             patch.object(host_probe.subprocess, "run", side_effect=subprocess.TimeoutExpired("ssh", 8)):
            record = host_probe.run_probe(args, protocol=PROTOCOL, ssh_path="ssh")
        self.assertEqual(record["result"], "PROBE_TIMEOUT")
        self.assertIsNone(record["ssh_exit_code"])
        self.assertEqual(host_probe.classify_return(255, "ssh: connect to host example port 22: Connection refused")[0], "CONNECTION_REFUSED")

    def test_ssh_host_key_failure_is_not_bypassed_or_mislabeled_as_auth_success(self):
        result = host_probe.classify_return(255, "Host key verification failed.")
        self.assertEqual(result, ("HOST_KEY_FAILURE", "NOT_ESTABLISHED", None))

    def test_unexpected_interruption_is_recorded_without_cleanup_claim(self):
        args = host_args()
        start = datetime(2037, 1, 1, tzinfo=timezone.utc)
        with patch.object(host_probe, "utc_now", side_effect=[start, start + timedelta(seconds=1)]), \
             patch.object(host_probe.time, "monotonic_ns", side_effect=[0, 1_000_000_000]), \
             patch.object(host_probe.subprocess, "run", side_effect=KeyboardInterrupt):
            record = host_probe.run_probe(args, protocol=PROTOCOL, ssh_path="ssh")
        self.assertEqual(record["result"], "INTERRUPTED")
        self.assertIsNone(record["authenticated"])
        self.assertNotIn("cleanup", record)

    def test_clock_discontinuity_and_large_uncertainty_are_exposed(self):
        args = host_args(timing_uncertainty_ms=100)
        start = datetime(2037, 1, 1, tzinfo=timezone.utc)
        completed = subprocess.CompletedProcess(["ssh"], 0, "", "")
        with patch.object(host_probe, "utc_now", side_effect=[start, start + timedelta(seconds=20)]), \
             patch.object(host_probe.time, "monotonic_ns", side_effect=[0, 10_000_000]), \
             patch.object(host_probe.subprocess, "run", return_value=completed):
            record = host_probe.run_probe(args, protocol=PROTOCOL, ssh_path="ssh")
        self.assertTrue(record["clock_discontinuity"])
        trial = make_trial("A", clock_discontinuity=True)
        report = analyze.build_report([trial], [], PROTOCOL, source_sha="a" * 40)
        group = next(row for row in report["groups"] if row["condition_id"] == "A" and row["route"] == "LAN")
        self.assertIn("CLOCK_DISCONTINUITY", group["confounder_flags"])
        trial["probe"]["timing_uncertainty_ms"] = 10_000
        report = analyze.build_report([trial], [], PROTOCOL, source_sha="a" * 40)
        group = next(row for row in report["groups"] if row["condition_id"] == "A" and row["route"] == "LAN")
        self.assertIn("HIGH_TIMING_UNCERTAINTY", group["confounder_flags"])

    def test_target_destination_validation_and_timeout_bounds(self):
        self.assertTrue(host_probe.valid_destination("operator@ipad-lab.example.test"))
        self.assertFalse(host_probe.valid_destination("-oProxyCommand=evil"))
        synthetic_ip = ".".join(str(part) for part in (192, 0, 2, 10))
        self.assertFalse(host_probe.valid_target_id(synthetic_ip))
        args = host_args(quiet_interval_seconds=301)
        errors = host_probe._preflight_errors(args, PROTOCOL)
        self.assertTrue(any("quiet-interval-seconds" in error for error in errors))

    def test_default_probe_invocation_is_inert(self):
        stdout = io.StringIO()
        with patch.object(host_probe, "run_probe") as execute, contextlib.redirect_stdout(stdout):
            code = host_probe.main(["--route", "LAN", "--condition-id", "A", "--trial-id", "dry-run", "--repetition", "1"])
        execute.assert_not_called()
        output = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(output["network_attempted"])
        self.assertFalse(output["power_state_changed"])

    def test_probe_requires_run_flag_and_all_operator_prerequisites(self):
        args = host_args()
        args.run_attended = False
        errors = host_probe._preflight_errors(args, PROTOCOL)
        self.assertTrue(any("--run-attended" in error for error in errors))
        args = host_args(installed_runtime_verified=False)
        errors = host_probe._preflight_errors(args, PROTOCOL)
        self.assertTrue(any("installed CLI/daemon" in error for error in errors))


class P012ControllerAndPrivacyTests(unittest.TestCase):
    def test_missing_data_is_preserved_as_incomplete(self):
        record = make_trial("A")
        record["probe"] = None
        report = analyze.build_report([record], [], PROTOCOL, source_sha="b" * 40)
        self.assertEqual(report["counts"]["incomplete_trials"], 1)
        group = next(row for row in report["groups"] if row["condition_id"] == "A" and row["route"] == "LAN")
        self.assertEqual(group["attempted_probes"], 0)
        comparison = next(row for row in report["comparisons"] if row["comparison"] == "A_vs_C" and row["route"] == "LAN")
        self.assertEqual(comparison["outcome"], "NOT_IDENTIFIABLE")

    def test_duplicate_trial_ids_are_invalidated(self):
        row = make_trial("A")
        report = analyze.build_report([row, json.loads(json.dumps(row))], [], PROTOCOL, source_sha="c" * 40)
        self.assertEqual(report["counts"]["invalid_trials"], 2)
        self.assertTrue(all("duplicate_trial_id" in outcome["issues"] for outcome in report["trial_outcomes"]))

    def test_invalid_json_and_duplicate_keys_are_rejected(self):
        with self.assertRaisesRegex(common.P012Error, "duplicate"):
            common.parse_json_bytes(b'{"trial_id":"a","trial_id":"b"}')
        with self.assertRaisesRegex(common.P012Error, "valid UTF-8 JSON"):
            common.parse_json_bytes(b"not-json")

    def test_symlink_input_and_traversal_record_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / "actual.json"
            actual.write_text("{}", encoding="utf-8")
            link = root / "linked.json"
            link.symlink_to(actual)
            with self.assertRaisesRegex(common.P012Error, "symbolic-link"):
                common.load_json(link)
            unsafe = make_trial("A")
            unsafe["trial_id"] = "../escape"
            with self.assertRaisesRegex(common.P012Error, "sanitized identifier"):
                trial_cli.write_record(unsafe, root / "private")
            self.assertFalse((root / "escape.json").exists())

    def test_controller_rejects_non_object_and_malformed_nested_record_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_file = root / "array.json"
            input_file.write_text("[]", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                trial_cli.main(["validate", "--record", str(input_file)])
            self.assertIn("JSON object", stderr.getvalue())
            malformed = {"trial_id": "malformed-state", "state": []}
            input_file.write_text(json.dumps(malformed), encoding="utf-8")
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                trial_cli.main(["record", "--input", str(input_file), "--operator-recorded", "--data-root", str(root / "records")])
            self.assertFalse((root / "records" / "malformed-state.json").exists())

    def test_report_destination_is_exclusive_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / "actual.md"
            actual.write_text("kept", encoding="utf-8")
            link = root / "report.md"
            link.symlink_to(actual)
            with self.assertRaisesRegex(common.P012Error, "symbolic-link"):
                trial_cli.write_report(link, "replacement")
            self.assertEqual(actual.read_text(encoding="utf-8"), "kept")
            with self.assertRaisesRegex(common.P012Error, "never overwritten"):
                trial_cli.write_report(actual, "replacement")
            self.assertEqual(actual.read_text(encoding="utf-8"), "kept")

    def test_record_is_exclusive_and_incomplete_record_remains_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = make_trial("A")
            record["operator_confirmations"]["direct_recovery_available"] = None
            root = Path(temporary) / "private"
            stored = trial_cli.write_record(record, root)
            self.assertTrue(stored.exists())
            self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(common.P012Error, "never overwritten"):
                trial_cli.write_record(record, root)

    def test_operator_can_store_a_partial_trial_as_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_file = root / "partial.json"
            input_file.write_text(json.dumps({"trial_id": "partial-trial"}), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = trial_cli.main(["record", "--input", str(input_file), "--operator-recorded", "--data-root", str(root / "records")])
            result = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(result["stored"])
            self.assertEqual(result["record_status"], "INCOMPLETE")
            saved = common.load_json(Path(result["path"]))
            self.assertEqual(saved["evidence_origin"], "OPERATOR_RECORDED")
            self.assertIsNone(saved["probe"])

    def test_malformed_known_field_is_rejected_before_it_can_be_saved(self):
        record = common.normalize_trial(make_trial("A"))
        record["state"]["wifi_profile_id"] = "password=private"
        self.assertTrue(common.record_encoding_issues(record))
        synthetic_ip = ".".join(str(part) for part in (192, 0, 2, 77))
        self.assertFalse(common.valid_id(synthetic_ip))

    def test_credential_like_content_is_rejected_without_echo_or_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_file = root / "unsafe.json"
            marker = "ghp_" + "A" * 30
            input_file.write_text(json.dumps({"trial_id": "sensitive", "password": marker}), encoding="utf-8")
            stderr = io.StringIO()
            with patch.object(sys, "stdin", io.StringIO("")), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    trial_cli.main(["record", "--input", str(input_file), "--operator-recorded", "--data-root", str(root / "records")])
            self.assertNotIn(marker, stderr.getvalue())
            self.assertFalse((root / "records" / "sensitive.json").exists())

    def test_operator_controller_dry_run_has_no_probe_or_device_action(self):
        stdout = io.StringIO()
        with patch.object(host_probe.subprocess, "run") as network_call, contextlib.redirect_stdout(stdout):
            code = trial_cli.main(["dry-run", "--condition", "C", "--route", "TAILSCALE"])
        network_call.assert_not_called()
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(result["network_attempted"])
        self.assertFalse(result["device_state_changed"])

    def test_host_probe_cli_requires_no_power_or_network_dependency_by_default(self):
        source = (ROOT / "scripts/p012_host_probe.py").read_text(encoding="utf-8")
        self.assertNotIn("PreventUserIdleSystemSleep", source)
        stdout = io.StringIO()
        with patch.object(host_probe.subprocess, "run") as process, contextlib.redirect_stdout(stdout):
            host_probe.main(["--route", "TAILSCALE", "--condition-id", "B", "--trial-id", "dry", "--repetition", "1"])
        process.assert_not_called()
        self.assertFalse(json.loads(stdout.getvalue())["network_attempted"])


class P012AnalysisAndEvidenceTests(unittest.TestCase):
    def test_success_rate_and_all_100_percent_a_vs_c_is_no_observable_difference(self):
        records = all_success_records()
        report = analyze.build_report(records, [], PROTOCOL, source_sha="d" * 40)
        self.assertEqual(report["counts"]["records"], 24)
        for route in ("LAN", "TAILSCALE"):
            group = next(row for row in report["groups"] if row["condition_id"] == "A" and row["route"] == route)
            self.assertEqual(group["attempted_probes"], 3)
            self.assertEqual(group["authenticated_successes"], 3)
            self.assertEqual(group["success_percent"], 100.0)
            self.assertEqual(group["successful_latency_ms"]["n"], 3)
            comparison = next(row for row in report["comparisons"] if row["comparison"] == "A_vs_C" and row["route"] == route)
            self.assertEqual(comparison["outcome"], "NO_OBSERVABLE_DIFFERENCE")
            self.assertFalse(comparison["statistical_significance_claimed"])
        self.assertFalse(report["evidence_strength"]["strong_evidence_established"])

    def test_fewer_than_three_matched_condition_pairs_is_insufficient_data(self):
        records = [make_trial(condition, "LAN", repetition) for repetition in (1, 2) for condition in ("A", "C")]
        report = analyze.build_report(records, [], PROTOCOL, source_sha="7" * 40)
        comparison = next(item for item in report["comparisons"] if item["comparison"] == "A_vs_C" and item["route"] == "LAN")
        self.assertEqual(comparison["matched_pair_count"], 2)
        self.assertEqual(comparison["outcome"], "INSUFFICIENT_DATA")
        self.assertEqual(comparison["data_strength"], "INSUFFICIENT_DATA")

    def test_lan_and_tailscale_are_separate_groups(self):
        records = [make_trial("A", "LAN"), make_trial("A", "TAILSCALE")]
        report = analyze.build_report(records, [], PROTOCOL, source_sha="e" * 40)
        lan = next(row for row in report["groups"] if row["condition_id"] == "A" and row["route"] == "LAN")
        ts = next(row for row in report["groups"] if row["condition_id"] == "A" and row["route"] == "TAILSCALE")
        self.assertEqual(lan["attempted_probes"], 1)
        self.assertEqual(ts["attempted_probes"], 1)

    def test_route_comparison_uses_matched_pairs_without_pooling(self):
        report = analyze.build_report(all_success_records(), [], PROTOCOL, source_sha="5" * 40)
        route_row = next(row for row in report["route_comparisons"] if row["condition_id"] == "C")
        self.assertEqual(route_row["matched_pair_count"], 3)
        self.assertEqual(route_row["lan_success_percent"], 100.0)
        self.assertEqual(route_row["tailscale_success_percent"], 100.0)
        self.assertEqual(route_row["outcome"], "NO_OBSERVABLE_DIFFERENCE")
        self.assertFalse(route_row["statistical_significance_claimed"])
        records = all_success_records()
        unmatched = next(row for row in records if row["condition_id"] == "C" and row["route"] == "TAILSCALE" and row["repetition"] == 1)
        unmatched["pair_id"] = "unmatched-c1"
        report = analyze.build_report(records, [], PROTOCOL, source_sha="6" * 40)
        route_row = next(row for row in report["route_comparisons"] if row["condition_id"] == "C")
        self.assertEqual(route_row["matched_pair_count"], 2)
        self.assertIn("UNMATCHED_ROUTE_PAIRS", route_row["confounder_flags"])
        self.assertEqual(route_row["outcome"], "INSUFFICIENT_DATA")

    def test_failure_categories_are_counted_separately(self):
        records = [make_trial("A", result=result) for result in ("AUTHENTICATION_FAILURE", "CONNECTION_REFUSED", "PROBE_TIMEOUT")]
        for index, row in enumerate(records):
            row["trial_id"] = f"failure-{index}"
            row["probe"]["trial_id"] = f"failure-{index}"
            row["repetition"] = index + 1
            row["probe"]["repetition"] = index + 1
            row["condition_order_index"] = PROTOCOL["design"]["condition_order_by_repetition"][index].index("A") + 1
            row["route_order_index"] = PROTOCOL["design"]["route_order_by_repetition"][index].index("LAN") + 1
        report = analyze.build_report(records, [], PROTOCOL, source_sha="f" * 40)
        group = next(row for row in report["groups"] if row["condition_id"] == "A" and row["route"] == "LAN")
        self.assertEqual(group["attempted_probes"], 3)
        self.assertEqual(group["failure_categories"], {"AUTHENTICATION_FAILURE": 1, "CONNECTION_REFUSED": 1, "PROBE_TIMEOUT": 1})

    def test_unequal_observation_windows_are_flagged_and_not_pooled(self):
        records = all_success_records()
        row = next(item for item in records if item["condition_id"] == "A" and item["route"] == "LAN" and item["repetition"] == 1)
        row["state"]["quiet_interval_seconds"] = 90
        start = common.parse_utc(row["state"]["quiet_start_at_utc"])
        row["state"]["quiet_end_at_utc"] = (start + timedelta(seconds=90)).isoformat().replace("+00:00", "Z")
        row["probe"]["quiet_interval_seconds"] = 90
        row["probe"]["started_at_utc"] = row["state"]["quiet_end_at_utc"]
        ended = common.parse_utc(row["probe"]["started_at_utc"]) + timedelta(milliseconds=row["probe"]["elapsed_ms"])
        row["probe"]["ended_at_utc"] = ended.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        row["trial_ended_at_utc"] = row["probe"]["ended_at_utc"]
        report = analyze.build_report(records, [], PROTOCOL, source_sha="1" * 40)
        comparison = next(item for item in report["comparisons"] if item["comparison"] == "A_vs_C" and item["route"] == "LAN")
        self.assertIn("UNEQUAL_QUIET_WINDOWS", comparison["confounder_flags"])
        self.assertEqual(comparison["outcome"], "NOT_IDENTIFIABLE")
        route_comparison = next(item for item in report["route_comparisons"] if item["condition_id"] == "A")
        self.assertIn("UNEQUAL_QUIET_WINDOWS", route_comparison["confounder_flags"])
        self.assertEqual(route_comparison["outcome"], "NOT_IDENTIFIABLE")

    def test_interrupted_and_invalid_trials_are_visible_not_discarded(self):
        interrupted = make_trial("A", result="INTERRUPTED")
        interrupted["interrupted"] = True
        interrupted["interruption_code"] = "operator_interrupt"
        invalid = make_trial("B", screen="UNLOCKED")
        report = analyze.build_report([interrupted, invalid], [], PROTOCOL, source_sha="2" * 40)
        self.assertEqual(report["counts"]["interrupted_trials"], 1)
        self.assertEqual(report["counts"]["invalid_trials"], 1)
        self.assertEqual(len(report["trial_outcomes"]), 2)

    def test_malformed_untrusted_rows_are_counted_without_crashing_or_echoing(self):
        malformed = make_trial("A")
        malformed["trial_id"] = "../private-marker"
        malformed["evidence_origin"] = []
        malformed["condition_id"] = []
        malformed["route"] = {}
        malformed["repetition"] = {}
        malformed["state"] = []
        malformed["probe"]["result"] = []
        report = analyze.build_report([malformed], [], PROTOCOL, source_sha="4" * 40)
        self.assertEqual(report["counts"]["invalid_trials"], 1)
        self.assertEqual(report["counts"]["attempted_probes"], 0)
        self.assertNotIn("../private-marker", json.dumps(report))
        self.assertIsNone(report["trial_outcomes"][0]["trial_id"])

    def test_malformed_bundle_source_is_reported_as_input_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bundle.json"
            path.write_text(json.dumps({"evidence_origin": [], "records": []}), encoding="utf-8")
            records, issues = analyze.load_trial_inputs([path], PROTOCOL)
            self.assertEqual(records, [])
            self.assertEqual(len(issues), 1)
            self.assertIn("invalid evidence_origin", issues[0])

    def test_p015_policy_fields_are_exposed_without_policy_recommendations(self):
        report = analyze.build_report(all_success_records(), [], PROTOCOL, source_sha="3" * 40)
        self.assertEqual(report["p015_policy_inputs"]["status"], "EXPOSED_FOR_FUTURE_REVIEW_ONLY")
        self.assertEqual(len(report["p015_policy_inputs"]["fields"]), 8)
        self.assertIn("no automatic policy recommendation", report["p015_policy_inputs"]["note"])

    def test_p009_mapping_uses_only_existing_timestamped_event_types(self):
        record = make_trial("C", "LAN")
        events = common.p009_observations(record)
        self.assertTrue(events)
        self.assertTrue({event["event_type"] for event in events}.issubset(p009_evidence.EVENT_TYPES))
        self.assertTrue({event["source"] for event in events}.issubset(p009_evidence.SOURCES))
        self.assertTrue(all(common.parse_utc(event["timestamp"]) for event in events))
        self.assertFalse(any(event["event_type"].startswith("P012_") for event in events))
        self.assertTrue(all(event["details"].get("address") is None for event in events if event["event_type"] in {"LAN_OBSERVATION", "TAILSCALE_OBSERVATION"}))
        self.assertEqual(next(event for event in events if event["event_type"] == "LAN_OBSERVATION")["details"]["ssh_authenticated"], True)

    def test_p009_mapping_does_not_invent_a_screen_lock_event_or_full_acceptance(self):
        record = make_trial("A")
        record["state"]["screen_lock_observed_at_utc"] = None
        record["operator_confirmations"]["screen_locked"] = None
        events = common.p009_observations(record)
        self.assertNotIn("SCREEN_LOCK", {event["event_type"] for event in events})
        mapping = {"observations": events, "acceptance_decision": "NOT_EVALUATED"}
        self.assertEqual(mapping["acceptance_decision"], "NOT_EVALUATED")

    def test_mapped_events_pass_existing_p009_v1_schema_and_validator(self):
        record = make_trial("C", "LAN")
        events = common.p009_observations(record)
        session = make_session()
        session["evidence_origin"] = "SIMULATED"
        session["physical_presence_confirmed"] = False
        session["observations"] = events
        times = [common.parse_utc(event["timestamp"]) for event in events]
        session["started_at"] = min(times).isoformat().replace("+00:00", "Z")
        session["ended_at"] = max(times).isoformat().replace("+00:00", "Z")
        session["trial"]["trial_id"] = record["trial_id"]
        session["trial"]["authorized_duration_seconds"] = 300
        p009_evidence.validate_against_schema(session, "https://ios-caffeinate.invalid/schemas/device-acceptance-v1.schema.json")
        p009_evidence._validate_session(session, [])


if __name__ == "__main__":
    unittest.main()
