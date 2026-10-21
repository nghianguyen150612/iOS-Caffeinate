"""P019 schema, analysis, evidence-compatibility, and safety-boundary tests."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import p009_evidence  # noqa: E402
import p012_common  # noqa: E402
import p018_validate_export  # noqa: E402
import p019_session as p019  # noqa: E402
from create_p018_fixture_bundle import create_bundle as create_p018_fixture  # noqa: E402
from p009_fixtures import make_session as make_p009_session, write_package as write_p009_package  # noqa: E402
from p012_fixtures import all_success_records, make_trial  # noqa: E402
from p019_fixtures import FIXTURE_CASES, make_candidate, make_cycles, make_session, pass_prerequisites  # noqa: E402


class P019ProtocolAndSchemaTests(unittest.TestCase):
    def test_protocol_and_schemas_validate_strictly(self):
        protocol, p012_protocol, issues = p019.load_protocol()
        self.assertEqual(issues, [])
        self.assertEqual(protocol["protocol_id"], "P019")
        self.assertEqual(protocol["p012_reference"]["planned_probe_trials"], 24)
        self.assertEqual(protocol["endurance_plan"]["planned_bounded_cycles"], 12)
        self.assertEqual(p012_protocol["protocol_id"], "P012")
        for schema_path in (p019.PROTOCOL_SCHEMA_PATH, p019.SESSION_SCHEMA_PATH, p019.RESULT_SCHEMA_PATH):
            schema = p019._load_schema(schema_path)
            self.assertIsInstance(schema["$id"], str)
        session = make_session()
        self.assertEqual(p019.validate_session(session, protocol, p012_protocol), [])

    def test_plan_is_inert_and_preregistered_values_are_visible(self):
        protocol, p012_protocol, _ = p019.load_protocol()
        plan = p019.build_plan(protocol, p012_protocol)
        self.assertTrue(plan["cloud_only"])
        self.assertFalse(plan["device_actions_started"])
        self.assertEqual(plan["p012_matrix"]["planned_probe_trials"], 24)
        self.assertEqual(plan["p012_matrix"]["quiet_interval_seconds"], 120)
        self.assertEqual(plan["repeated_bounded_sessions"]["planned_bounded_cycles"], 12)

    def test_all_48_requested_fixture_scenarios_are_present(self):
        self.assertEqual(len(FIXTURE_CASES), 48)
        self.assertEqual(len(set(FIXTURE_CASES)), 48)


class P019FixtureMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol, self.p012_protocol, _ = p019.load_protocol()

    def analyze(self, session):
        return p019.analyze_session(session, self.protocol, self.p012_protocol)

    def test_empty_template_reports_not_started(self):
        result = self.analyze(make_session())
        self.assertEqual(result["status"], "NOT_STARTED")
        self.assertEqual(result["hardware_acceptance"], "NOT_ESTABLISHED")

    def test_operator_confirmation_records_unreconciled_host_clock(self):
        session = make_session()
        with tempfile.TemporaryDirectory(prefix="ioscaf-p019-confirmation-") as temporary:
            root = Path(temporary)
            session_path = root / "session.json"
            output_path = root / "session-confirmed.json"
            session_path.write_text(json.dumps(session), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                result_code = p019.main([
                    "record-confirmation", "--session", str(session_path), "--key", "operator_present",
                    "--value", "CONFIRMED", "--operator-id", "operator-1", "--note", "attended",
                    "--output", str(output_path),
                ])
            self.assertEqual(result_code, 0)
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            confirmation = saved["operator_confirmations"][0]
            self.assertEqual(confirmation["source_class"], "OPERATOR_RECORDED")
            self.assertEqual(confirmation["timebase_id"], "host-clock-unreconciled")
            self.assertIsNone(confirmation["uncertainty_ms"])

    def test_all_prerequisites_satisfied(self):
        session = make_session()
        make_candidate(session)
        pass_prerequisites(session, "MOCK")
        result = self.analyze(session)
        self.assertEqual(result["status"], "PREREQUISITES_BLOCKED")
        self.assertTrue(any(gate["status"] == "BLOCKED" for gate in result["gates"]))

    def test_missing_p011_package_acceptance(self):
        result = self.analyze(make_session())
        gate = next(item for item in result["gates"] if item["gate_id"] == "p011_stable_package_acceptance")
        self.assertEqual(gate["status"], "PENDING")

    def test_missing_exact_ldid_provenance(self):
        session = make_session()
        make_candidate(session)
        session["candidate"]["ldid_sha256"] = "1" * 64
        self.assertTrue(any("exact P010 ldid" in issue for issue in p019.validate_session(session, self.protocol, self.p012_protocol)))

    def test_package_hash_mismatch(self):
        session = make_session()
        session["candidate"].update(artifact_role="STABLE_V0.1.0", package_sha256="0" * 64, package_identifier="com.ioscaffeinate.cli", package_version="0.1.0-1")
        self.assertTrue(any("pinned P011 package" in issue for issue in p019.validate_session(session, self.protocol, self.p012_protocol)))

    def test_signed_candidate_with_device_validation_pending(self):
        session = make_session()
        make_candidate(session)
        result = self.analyze(session)
        self.assertEqual(result["status"], "PREREQUISITES_BLOCKED")
        self.assertNotEqual(result["status"], "READY_FOR_ATTENDED_TEST")

    def test_incorrect_binary_or_build_identity(self):
        session = make_session()
        make_candidate(session)
        session["candidate"]["cli_binary_sha256"] = None
        issues = p019.validate_session(session, self.protocol, self.p012_protocol)
        self.assertTrue(any("candidate identity is incomplete" in issue for issue in issues))

    def test_missing_installed_runtime(self):
        session = make_session()
        item = next(item for item in session["prerequisites"] if item["gate_id"] == "installed_candidate_identity")
        item.update(status="PENDING", reason="Installed paths have not been checked.")
        result = self.analyze(session)
        self.assertEqual(next(g["status"] for g in result["gates"] if g["gate_id"] == "installed_candidate_identity"), "PENDING")

    def test_p013_launchd_compatibility_unverified_remains_out_of_scope(self):
        session = make_session()
        item = next(item for item in session["prerequisites"] if item["gate_id"] == "p013_launchd_mutation_compatibility")
        item.update(status="NOT_APPLICABLE", source_class="CI", evidence_ref="ci://p013-guard", reason="Launchd mutation remains unverified and is not run.")
        result = self.analyze(session)
        self.assertEqual(next(g["status"] for g in result["gates"] if g["gate_id"] == "p013_launchd_mutation_compatibility"), "NOT_APPLICABLE")
        self.assertIn("automatic restart", " ".join(result["excluded_scope"]))

    def test_p014_cleanup_unresolved(self):
        session = make_session()
        item = next(item for item in session["prerequisites"] if item["gate_id"] == "p014_journal_and_assertion_state_safe")
        item.update(status="BLOCKED", source_class="OPERATOR_RECORDED", evidence_ref="operator:cleanup", reason="Journal state is unresolved.")
        result = self.analyze(session)
        self.assertEqual(result["status"], "PREREQUISITES_BLOCKED")
        self.assertIn("p014_journal_and_assertion_state_safe", result["metrics"]["remaining_acceptance_gates"])

    def test_p014_recovery_journal_corruption(self):
        session = make_session()
        session["incidents"].append({"incident_id": "journal-1", "code": "P014_JOURNAL_CORRUPT", "severity": "STOP", "occurred_at_utc": "2037-01-01T00:00:00Z", "source_class": "SIMULATED", "timebase_id": "simulated-clock", "uncertainty_ms": 1000, "disposition": "OPEN", "summary": "Synthetic fault injection."})
        self.assertEqual(self.analyze(session)["status"], "FAILED_SAFETY")

    def test_unsupported_automatic_restart_is_not_claimed(self):
        session = make_session()
        item = next(item for item in session["prerequisites"] if item["gate_id"] == "p014_automatic_restart_executor")
        item.update(status="NOT_APPLICABLE", source_class="CI", evidence_ref="ci://p014-policy", reason="No production restart executor exists.")
        result = self.analyze(session)
        self.assertIn("automatic restart", " ".join(result["excluded_scope"]))
        self.assertNotEqual(result["hardware_acceptance"], "SERVER_24_7_READY")

    def test_p015_unattended_operation_denial(self):
        session = make_session()
        item = next(item for item in session["prerequisites"] if item["gate_id"] == "p015_unattended_server_mode")
        item.update(status="NOT_APPLICABLE", source_class="CI", evidence_ref="ci://p015-deny", reason="P015 denies unattended execution.")
        result = self.analyze(session)
        self.assertEqual(next(g["status"] for g in result["gates"] if g["gate_id"] == "p015_unattended_server_mode"), "NOT_APPLICABLE")
        self.assertIn("unattended schedule execution", " ".join(result["excluded_scope"]))

    def test_p016_battery_unavailable_is_not_zero(self):
        session = make_session(full=True)
        session["resource_observations"].append({"observation_id": "battery-unavailable", "trial_id": None, "field": "battery_percent", "availability": "UNAVAILABLE", "value": None, "source_class": "SIMULATED", "observed_at_utc": "2037-01-01T10:00:00Z", "timebase_id": "fixture-clock", "uncertainty_ms": 100})
        self.assertEqual(p019.validate_session(session, self.protocol, self.p012_protocol), [])
        self.assertEqual(session["resource_observations"][0]["value"], None)

    def test_p016_thermal_unavailable_is_not_nominal(self):
        session = make_session(full=True)
        session["resource_observations"].append({"observation_id": "thermal-unavailable", "trial_id": None, "field": "thermal_state", "availability": "UNAVAILABLE", "value": None, "source_class": "SIMULATED", "observed_at_utc": "2037-01-01T10:00:00Z", "timebase_id": "fixture-clock", "uncertainty_ms": 100})
        self.assertEqual(p019.validate_session(session, self.protocol, self.p012_protocol), [])
        self.assertIsNone(session["resource_observations"][0]["value"])

    def test_p017_schedule_execution_is_unauthorized(self):
        session = make_session()
        item = next(item for item in session["prerequisites"] if item["gate_id"] == "p017_schedule_execution_disabled")
        item.update(status="NOT_APPLICABLE", source_class="CI", evidence_ref="ci://p017-deny", reason="Schedule execution remains unauthorized.")
        self.assertIn("unattended schedule execution", " ".join(self.analyze(session)["excluded_scope"]))

    def test_successful_bounded_acquisition_release(self):
        session = make_session(full=True)
        result = self.analyze(session)
        self.assertEqual(result["metrics"]["successful_bounded_holds"], 12)
        self.assertEqual(result["metrics"]["confirmed_releases"], 12)
        self.assertEqual(result["status"], "PREREQUISITES_BLOCKED")

    def test_cycle_without_duration_timebase_stays_incomplete(self):
        session = make_session(full=True)
        session["bounded_cycles"][0]["duration_timebase_id"] = None
        session["bounded_cycles"][0]["duration_uncertainty_ms"] = None
        result = self.analyze(session)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["metrics"]["successful_bounded_holds"], 11)

    def test_assertion_release_failure_is_safety_failure(self):
        session = make_session(full=True)
        session["bounded_cycles"][0]["release"] = "FAILED"
        session["bounded_cycles"][0]["cleanup_state"] = "UNRESOLVED"
        self.assertEqual(self.analyze(session)["status"], "FAILED_SAFETY")

    def test_unexpected_daemon_exit_is_safety_failure(self):
        session = make_session(full=True)
        session["bounded_cycles"][0]["daemon_exit"] = "UNEXPECTED"
        self.assertEqual(self.analyze(session)["status"], "FAILED_SAFETY")

    def test_interrupted_trial_remains_incomplete(self):
        session = make_session(full=True)
        session["trial_records"][0]["interrupted"] = True
        session["trial_records"][0]["probe"]["result"] = "INTERRUPTED"
        self.assertEqual(self.analyze(session)["status"], "INCOMPLETE")

    def test_missing_screen_lock_evidence_is_incomplete(self):
        session = make_session(full=True)
        session["trial_records"][0]["state"]["screen_lock_status"] = "UNKNOWN"
        session["trial_records"][0]["probe"]["screen_lock_status"] = "UNKNOWN"
        session["trial_records"][0]["probe"]["screen_lock_confirmed"] = False
        self.assertEqual(self.analyze(session)["status"], "INCOMPLETE")

    def test_missing_independent_observer_keeps_review_pending(self):
        session = make_session(full=True)
        session["review"]["status"] = "PENDING"
        result = self.analyze(session)
        self.assertNotEqual(result["status"], "ACCEPTED_FOR_TESTED_SCOPE")
        self.assertEqual(next(g["status"] for g in result["gates"] if g["gate_id"] == "independent_evidence_review"), "PENDING")

    def test_lan_only_success_is_not_pooled_with_tailscale(self):
        session = make_session()
        session["trial_records"] = [row for row in all_success_records() if row["route"] == "LAN"]
        result = self.analyze(session)
        self.assertEqual(result["metrics"]["lan_authenticated_successes"], 12)
        self.assertEqual(result["metrics"]["tailscale_authenticated_successes"], 0)
        self.assertEqual(result["metrics"]["tailscale_authenticated_failures"], 0)

    def test_tailscale_only_success_is_not_pooled_with_lan(self):
        session = make_session()
        session["trial_records"] = [row for row in all_success_records() if row["route"] == "TAILSCALE"]
        result = self.analyze(session)
        self.assertEqual(result["metrics"]["tailscale_authenticated_successes"], 12)
        self.assertEqual(result["metrics"]["lan_authenticated_successes"], 0)

    def test_authentication_failure_is_a_route_outcome(self):
        session = make_session()
        records = all_success_records()
        records[0] = make_trial("A", "LAN", 1, result="AUTHENTICATION_FAILURE")
        session["trial_records"] = records
        result = self.analyze(session)
        self.assertEqual(result["metrics"]["lan_authenticated_failures"], 1)

    def test_ssh_timeout_is_a_route_outcome(self):
        session = make_session()
        records = all_success_records()
        records[0] = make_trial("A", "LAN", 1, result="PROBE_TIMEOUT")
        session["trial_records"] = records
        self.assertEqual(self.analyze(session)["metrics"]["lan_authenticated_failures"], 1)

    def test_host_key_failure_stops_testing(self):
        session = make_session()
        records = all_success_records()
        records[0] = make_trial("A", "LAN", 1, result="HOST_KEY_FAILURE")
        session["trial_records"] = records
        self.assertEqual(self.analyze(session)["status"], "FAILED_SAFETY")

    def test_invalid_observer_timestamps_remain_visible(self):
        session = make_session(full=True)
        session["trial_records"][0]["trial_started_at_utc"] = "not-a-time"
        self.assertEqual(self.analyze(session)["status"], "INCOMPLETE")

    def test_clock_disagreement_marks_comparisons_inconclusive(self):
        session = make_session(full=True)
        row = session["trial_records"][0]
        row["observer_timebase_id"] = "unreconciled-host-clock"
        row["probe"]["observer_timebase_id"] = "unreconciled-host-clock"
        result = self.analyze(session)
        self.assertTrue(any(item["outcome"] in {"INCONCLUSIVE", "NOT_IDENTIFIABLE"} for item in result["analysis"]["comparisons"]))

    def test_cross_timebase_uncertainty_does_not_prove_probe_order(self):
        session = make_session(full=True)
        for row in session["trial_records"]:
            if row["condition_id"] == "C":
                row["device_timebase_id"] = "unreconciled-device-boot"
        result = self.analyze(session)
        self.assertTrue(any(item["outcome"] in {"INCONCLUSIVE", "NOT_IDENTIFIABLE"} for item in result["analysis"]["comparisons"]))

    def test_quiet_interval_contamination_invalidates_trial(self):
        session = make_session(full=True)
        session["trial_records"][0]["state"]["quiet_period_contaminated"] = True
        session["trial_records"][0]["state"]["quiet_incoming_probe_count"] = 1
        self.assertEqual(self.analyze(session)["status"], "INCOMPLETE")

    def test_invalid_sample_count_is_reported_with_denominator(self):
        session = make_session(full=True)
        session["trial_records"] = session["trial_records"][:-1]
        result = self.analyze(session)
        self.assertEqual(result["metrics"]["planned_trials"], 24)
        self.assertEqual(result["metrics"]["attempted_trials"], 23)
        self.assertNotEqual(result["status"], "ACCEPTED_FOR_TESTED_SCOPE")

    def test_duplicate_trial_ids_are_rejected(self):
        session = make_session(full=True)
        session["trial_records"][1]["trial_id"] = session["trial_records"][0]["trial_id"]
        self.assertTrue(any("duplicate P012 trial ID" in issue for issue in p019.validate_session(session, self.protocol, self.p012_protocol)))

    def test_physical_label_cannot_promote_simulated_records(self):
        session = make_session(full=True)
        session["evidence_class"] = "DEVICE_REPORTED"
        self.assertTrue(any("cannot promote simulated" in issue for issue in p019.validate_session(session, self.protocol, self.p012_protocol)))
        self.assertNotEqual(self.analyze(session)["status"], "ACCEPTED_FOR_TESTED_SCOPE")

    def test_p009_malformed_event_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "p009"
            raw = make_p009_session()
            raw["observations"][0]["event_type"] = "UNKNOWN_EVENT"
            write_p009_package(root, raw)
            with self.assertRaises(p009_evidence.EvidenceError):
                p009_evidence.load_package(root)

    def test_tampered_p009_evidence_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "p009"
            write_p009_package(root, make_p009_session())
            (root / "evidence/operator-note.txt").write_text("changed after manifest\n", encoding="utf-8")
            with self.assertRaises(p009_evidence.EvidenceError):
                p009_evidence.load_package(root)

    def test_missing_p009_manifest_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "p009"
            write_p009_package(root, make_p009_session())
            (root / "evidence/operator-note.txt").unlink()
            with self.assertRaises(p009_evidence.EvidenceError):
                p009_evidence.load_package(root)

    def test_privacy_filtered_export_is_valid_but_not_hardware_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            result = create_p018_fixture(bundle, "a" * 40)
            self.assertEqual(result["validation"], "VALID")
            self.assertEqual(result["hardware_evidence_accepted"], "NOT_ESTABLISHED")

    def test_export_privacy_rejection_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            create_p018_fixture(bundle, "a" * 40)
            target = bundle / "evidence/ci/mock-source.json"
            raw = b'{"source_class":"MOCK","note":"192.0.2.44"}\n'
            target.write_bytes(raw)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in manifest["files"]:
                if entry["path"] == "evidence/ci/mock-source.json":
                    entry["size_bytes"] = len(raw)
                    entry["sha256"] = hashlib.sha256(raw).hexdigest()
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            with self.assertRaises(p018_validate_export.ExportValidationError):
                p018_validate_export.validate_bundle(bundle)

    def test_unreviewed_evidence_cannot_accept(self):
        session = make_session(full=True)
        session["review"]["status"] = "PENDING"
        result = self.analyze(session)
        self.assertNotEqual(result["status"], "ACCEPTED_FOR_TESTED_SCOPE")

    def test_simulated_session_cannot_claim_acceptance(self):
        session = make_session(full=True)
        make_candidate(session)
        pass_prerequisites(session, "MOCK")
        session["review"].update(status="REVIEWED", reviewer_id="reviewer", operator_id="operator", independent=True, reviewed_at_utc="2037-01-04T00:00:00Z", reviewed_p009_session_sha256="1" * 64, checked_source_hashes=["1" * 64], decision="ACCEPT")
        result = self.analyze(session)
        self.assertEqual(result["status"], "PREREQUISITES_BLOCKED")
        self.assertEqual(result["hardware_acceptance"], "NOT_ESTABLISHED")

    def test_report_after_incomplete_session_keeps_counts(self):
        session = make_session(full=True)
        session["trial_records"] = session["trial_records"][:4]
        result = self.analyze(session)
        self.assertEqual(result["status"], "PREREQUISITES_BLOCKED")
        self.assertEqual(result["metrics"]["attempted_trials"], 4)
        self.assertNotEqual(result["hardware_acceptance"], "ACCEPTED_FOR_TESTED_SCOPE")

    def test_unsafe_cancellation_is_a_safety_failure(self):
        session = make_session(full=True)
        session["session_state"] = "CANCELLED"
        session["supervision"].update(attendance="ABSENT", independent_recovery="UNAVAILABLE")
        self.assertEqual(self.analyze(session)["status"], "FAILED_SAFETY")

    def test_no_automatic_ssh_probing(self):
        tree = ast.parse((ROOT / "scripts/p019_session.py").read_text(encoding="utf-8"))
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imports.update(node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module)
        self.assertFalse(imports & {"socket", "paramiko", "asyncssh"})
        self.assertNotIn("probe", p019.build_parser()._subparsers._group_actions[0].choices)

    def test_no_launchd_mutation(self):
        source = (ROOT / "scripts/p019_session.py").read_text(encoding="utf-8")
        self.assertNotIn("launchctl", source)
        self.assertNotIn("os.system", source)

    def test_no_iokit_acquisition(self):
        source = (ROOT / "scripts/p019_session.py").read_text(encoding="utf-8")
        self.assertNotIn("power_acquire", source)
        self.assertNotIn("IOPMLib", source)
        self.assertNotIn("IOKit.framework", source)

    def test_no_unattended_execution(self):
        protocol, _, _ = p019.load_protocol()
        self.assertFalse(protocol["endurance_plan"]["automated_runner"])
        self.assertFalse(protocol["endurance_plan"]["overnight_or_unattended_execution"])

    def test_no_auto_installation_or_rollback(self):
        source = (ROOT / "scripts/p019_session.py").read_text(encoding="utf-8")
        self.assertNotIn("dpkg -i", source)
        self.assertNotIn("dpkg --remove", source)
        self.assertNotIn("rollback --", source)

    def test_no_fabricated_reliability_claim(self):
        result = self.analyze(make_session(full=True))
        self.assertNotEqual(result["status"], "ACCEPTED_FOR_TESTED_SCOPE")
        self.assertNotIn("SERVER_24_7_READY", json.dumps(result))
        self.assertIn("Finite attended trials do not imply 24/7 reliability.", result["provenance_limits"])

    def test_generated_result_matches_versioned_result_schema(self):
        result = self.analyze(make_session(full=True))
        issues = p012_common.validate_json_schema(result, p019._load_schema(p019.RESULT_SCHEMA_PATH))
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
