"""P009 offline schema, integrity, replay, and safety regression tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/p009_evidence.py"
FIXTURES = ROOT / "tests/p009_fixtures.py"
spec = importlib.util.spec_from_file_location("p009_evidence", SCRIPT)
p009 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = p009
spec.loader.exec_module(p009)
fixture_spec = importlib.util.spec_from_file_location("p009_fixtures", FIXTURES)
fixture_tools = importlib.util.module_from_spec(fixture_spec)
assert fixture_spec.loader is not None
sys.modules[fixture_spec.name] = fixture_tools
fixture_spec.loader.exec_module(fixture_tools)


class P009Evidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p009-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package_path = fixture_tools.build_fixture(self.root / "valid", "valid_simulated_bounded_trial")

    def load(self, path=None):
        return p009.load_package(path or self.package_path)

    def report(self, package=None, analysis=None, **kwargs):
        package = package or self.load()
        analysis = analysis or p009.replay(package["session"])
        return p009.readiness_report(package, analysis, **kwargs)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=ROOT, text=True, capture_output=True, timeout=10)

    def rewrite_session(self, mutate):
        session_path = self.package_path / "session.json"
        session = json.loads(session_path.read_text())
        mutate(session)
        session_path.write_text(json.dumps(session, indent=2, sort_keys=True) + "\n")
        manifest_path = self.package_path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        raw = session_path.read_bytes()
        entry = next(item for item in manifest["files"] if item["path"] == "session.json")
        entry["size_bytes"] = len(raw)
        entry["sha256"] = hashlib.sha256(raw).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def test_versioned_schemas_are_valid_json_and_reference_p006_contract(self):
        acceptance = json.loads((ROOT / "docs/schemas/device-acceptance-v1.schema.json").read_text())
        p006 = json.loads((ROOT / "docs/schemas/connectivity-evidence-v1.schema.json").read_text())
        registry = json.loads((ROOT / "docs/schemas/device-acceptance-gates-v1.json").read_text())
        self.assertEqual(acceptance["properties"]["connectivity_evidence"]["$ref"], p006["$id"])
        self.assertEqual(registry["maximum_trial_seconds"], 300)
        self.assertEqual(len(registry["gates"]), 22)

    def test_all_documented_synthetic_fixtures_are_deterministic_and_handled(self):
        fixture_set = json.loads((ROOT / "tests/fixtures/p009/cases.json").read_text())
        self.assertIn("synthetic", fixture_set["fixture_set"].lower())
        invalid = {"invalid_hashes", "corrupted_json", "path_traversal", "oversized_evidence"}
        for name in fixture_set["cases"]:
            with self.subTest(fixture=name):
                path = fixture_tools.build_fixture(self.root / name, name)
                if name in invalid:
                    with self.assertRaises(p009.EvidenceError):
                        self.load(path)
                else:
                    package = self.load(path)
                    self.assertEqual(package["session"]["evidence_origin"], "SIMULATED")
                    p009.replay(package["session"])

    def test_existing_p006_connectivity_shape_remains_compatible(self):
        connectivity = {
            "version": 1,
            "lan": {"local_address": "192.0.2.10", "tcp_22_reachable": True, "ssh_authenticated": True, "latency_ms": 12.0, "timestamp": "2026-07-02T12:00:15Z", "screen_lock_status": "LOCKED"},
            "tailscale": {"tailnet_address": None, "peer_connected": None, "path": "UNKNOWN", "ssh_authenticated": None, "latency_ms": None, "timestamp": None, "screen_lock_status": "UNKNOWN"},
        }
        self.rewrite_session(lambda session: session.update(connectivity_evidence=connectivity))
        package = self.load()
        replay = p009.replay(package["session"])
        self.assertIn("LAN_OBSERVATION", {event["event_type"] for event in replay["timeline"]})
        self.assertEqual(package["session"]["connectivity_evidence"]["version"], 1)

    def test_valid_fixture_is_simulated_and_never_hardware_pass(self):
        package = self.load()
        report = self.report(package)
        self.assertEqual(package["session"]["evidence_origin"], "SIMULATED")
        self.assertEqual(report["structural_validation"], "PASS")
        self.assertEqual(report["decision"]["hardware_acceptance"], "PENDING")
        self.assertFalse(report["decision"]["unattended_operation_authorized"])
        self.assertTrue(all(gate["status"] != "PASS" for gate in report["gates"]))

    def test_mock_evidence_cannot_pass_physical_gates(self):
        path = fixture_tools.build_fixture(self.root / "mock", "valid_simulated_bounded_trial", origin="MOCK")
        report = self.report(self.load(path))
        self.assertTrue(all(gate["status"] == "BLOCKED" for gate in report["gates"]))

    def test_ci_evidence_cannot_pass_physical_gates(self):
        path = fixture_tools.build_fixture(self.root / "ci", "valid_simulated_bounded_trial", origin="CI")
        report = self.report(self.load(path))
        self.assertTrue(all(gate["status"] == "BLOCKED" for gate in report["gates"]))

    def test_session_review_claim_does_not_approve_gate(self):
        package = self.load()
        report = self.report(package)
        self.assertEqual(package["session"]["review_status"], "REVIEWED")
        self.assertNotIn("PASS", {gate["status"] for gate in report["gates"]})

    def test_explicit_human_review_is_required_for_candidate_gate(self):
        path = fixture_tools.build_fixture(self.root / "physical-candidate", "valid_simulated_bounded_trial", origin="OPERATOR_RECORDED")
        package = self.load(path)
        analysis = p009.replay(package["session"])
        candidates = p009.gate_candidates(package["session"], analysis)
        self.assertEqual(candidates["iokit_acquire_verified"][0], "REVIEW_REQUIRED")
        unchanged = p009.readiness_report(package, analysis)
        self.assertNotEqual(next(g["status"] for g in unchanged["gates"] if g["id"] == "iokit_acquire_verified"), "PASS")
        reviewed = p009.readiness_report(package, analysis, {"iokit_acquire_verified": "PASS"}, "operator-1")
        self.assertEqual(next(g["status"] for g in reviewed["gates"] if g["id"] == "iokit_acquire_verified"), "PASS")
        self.assertEqual(reviewed["human_review"]["cryptographic_authenticity"], "NOT_ESTABLISHED")

    def test_human_review_cannot_override_an_event_order_contradiction(self):
        path = fixture_tools.build_fixture(self.root / "physical-bad-order", "invalid_event_ordering", origin="OPERATOR_RECORDED")
        package = self.load(path)
        analysis = p009.replay(package["session"])
        candidate_ids = [gate["id"] for gate in p009.readiness_report(package, analysis)["gates"] if gate["status"] == "REVIEW_REQUIRED"]
        reviewed = p009.readiness_report(package, analysis, {gate_id: "PASS" for gate_id in candidate_ids}, "reviewer-1")
        self.assertNotIn("PASS", {gate["status"] for gate in reviewed["gates"]})

    def test_missing_assertion_release_is_reported_and_blocks_cleanup(self):
        path = fixture_tools.build_fixture(self.root / "missing-release", "missing_assertion_release")
        package = self.load(path)
        analysis = p009.replay(package["session"])
        self.assertIn("ASSERTION_RELEASE_MISSING", {item["code"] for item in analysis["findings"]})
        report = p009.readiness_report(package, analysis)
        self.assertEqual(next(g["status"] for g in report["gates"] if g["id"] == "no_unresolved_assertion"), "BLOCKED")

    def test_explicit_stop_is_replayed(self):
        path = fixture_tools.build_fixture(self.root / "stop", "explicit_stop")
        analysis = p009.replay(self.load(path)["session"])
        event_types = {event["event_type"] for event in analysis["timeline"]}
        self.assertIn("EXPLICIT_STOP", event_types)

    def test_natural_expiry_is_separate_from_stop(self):
        path = fixture_tools.build_fixture(self.root / "expiry", "natural_expiry", origin="OPERATOR_RECORDED")
        report = self.report(self.load(path))
        states = {gate["id"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(states["natural_expiry_verified"], "REVIEW_REQUIRED")
        self.assertEqual(states["explicit_stop_verified"], "INSUFFICIENT_EVIDENCE")

    def test_release_failure_fails_release_and_unresolved_assertion(self):
        path = fixture_tools.build_fixture(self.root / "release-failed", "release_failure", origin="OPERATOR_RECORDED")
        package = self.load(path)
        analysis = p009.replay(package["session"])
        self.assertIn("RELEASE_FAILURE", {item["code"] for item in analysis["findings"]})
        report = p009.readiness_report(package, analysis)
        states = {gate["id"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(states["iokit_release_verified"], "FAIL")
        self.assertEqual(states["no_unresolved_assertion"], "FAIL")

    def test_release_retry_only_clears_failure_when_later_release_is_observed(self):
        path = fixture_tools.build_fixture(self.root / "retry-recovered", "recovered_release_failure", origin="OPERATOR_RECORDED")
        package = self.load(path)
        analysis = p009.replay(package["session"])
        codes = {item["code"] for item in analysis["findings"]}
        self.assertIn("RELEASE_RETRY_RECOVERED", codes)
        self.assertNotIn("RELEASE_FAILURE", codes)
        candidates = p009.gate_candidates(package["session"], analysis)
        self.assertEqual(candidates["no_unresolved_assertion"][0], "REVIEW_REQUIRED")

    def test_unverified_signature_cannot_pass_acceptance(self):
        path = fixture_tools.build_fixture(self.root / "signature", "invalid_signature_evidence", origin="OPERATOR_RECORDED")
        report = self.report(self.load(path))
        self.assertEqual(next(g["status"] for g in report["gates"] if g["id"] == "signature_acceptance_verified"), "FAIL")

    def test_absent_signature_evidence_remains_incomplete(self):
        path = fixture_tools.build_fixture(self.root / "signature-missing", "missing_signature_evidence", origin="OPERATOR_RECORDED")
        package = self.load(path)
        candidates = p009.gate_candidates(package["session"], p009.replay(package["session"]))
        self.assertEqual(candidates["signature_acceptance_verified"][0], "INSUFFICIENT_EVIDENCE")

    def test_lan_and_tailscale_are_evaluated_independently(self):
        path = fixture_tools.build_fixture(self.root / "physical-lan", "tailscale_failure_despite_lan_success", origin="OPERATOR_RECORDED")
        package = self.load(path)
        candidates = p009.gate_candidates(package["session"], p009.replay(package["session"]))
        self.assertEqual(candidates["screen_locked_lan_verified"][0], "REVIEW_REQUIRED")
        self.assertEqual(candidates["screen_locked_tailscale_verified"][0], "FAIL")

    def test_tailscale_evidence_does_not_substitute_for_lan(self):
        path = fixture_tools.build_fixture(self.root / "physical-ts", "tailscale_relay_path", origin="OPERATOR_RECORDED")
        package = self.load(path)
        session = package["session"]
        session["observations"] = [event for event in session["observations"] if event["event_type"] != "LAN_OBSERVATION"]
        candidates = p009.gate_candidates(session, p009.replay(session))
        self.assertEqual(candidates["screen_locked_lan_verified"][0], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(candidates["screen_locked_tailscale_verified"][0], "REVIEW_REQUIRED")

    def test_relay_path_can_be_recorded_without_becoming_a_lan_result(self):
        path = fixture_tools.build_fixture(self.root / "relay", "tailscale_relay_path", origin="OPERATOR_RECORDED")
        report = self.report(self.load(path))
        self.assertEqual(report["networking"]["tailscale"]["path"], "RELAY")
        self.assertEqual(report["networking"]["lan"]["gate_status"], "REVIEW_REQUIRED")

    def test_missing_operator_screen_confirmation_keeps_lan_gate_incomplete(self):
        path = fixture_tools.build_fixture(self.root / "operator-confirm", "missing_operator_confirmation", origin="OPERATOR_RECORDED")
        package = self.load(path)
        candidates = p009.gate_candidates(package["session"], p009.replay(package["session"]))
        self.assertEqual(candidates["screen_locked_lan_verified"][0], "INSUFFICIENT_EVIDENCE")

    def test_missing_battery_and_thermal_remain_insufficient(self):
        battery_path = fixture_tools.build_fixture(self.root / "no-battery", "missing_battery_observation", origin="OPERATOR_RECORDED")
        thermal_path = fixture_tools.build_fixture(self.root / "no-thermal", "missing_thermal_observation", origin="OPERATOR_RECORDED")
        battery = p009.gate_candidates(self.load(battery_path)["session"], p009.replay(self.load(battery_path)["session"]))
        thermal = p009.gate_candidates(self.load(thermal_path)["session"], p009.replay(self.load(thermal_path)["session"]))
        self.assertEqual(battery["battery_observation_available"][0], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(thermal["thermal_observation_available"][0], "INSUFFICIENT_EVIDENCE")

    def test_clock_discrepancy_is_preserved_as_a_timeline_finding(self):
        path = fixture_tools.build_fixture(self.root / "clock", "device_clock_discrepancy")
        codes = {item["code"] for item in p009.replay(self.load(path)["session"])["findings"]}
        self.assertIn("TIMESTAMP_SEQUENCE_CONTRADICTION", codes)

    def test_trial_duration_overrun_fails_bounded_hold_gate(self):
        path = fixture_tools.build_fixture(self.root / "overlong", "overlong_trial", origin="OPERATOR_RECORDED")
        package = self.load(path)
        analysis = p009.replay(package["session"])
        self.assertIn("TRIAL_DURATION_EXCEEDED", {item["code"] for item in analysis["findings"]})
        self.assertEqual(p009.gate_candidates(package["session"], analysis)["bounded_hold_verified"][0], "FAIL")

    def test_clock_uncertainty_cannot_be_used_to_pass_duration_ceiling(self):
        path = fixture_tools.build_fixture(self.root / "uncertain-duration", "valid_simulated_bounded_trial", origin="OPERATOR_RECORDED")
        package = self.load(path)
        session = package["session"]
        session["trial"]["authorized_duration_seconds"] = 30
        for item in session["observations"]:
            if item["event_type"] in {"ASSERTION_ACQUIRE_SUCCESS", "ASSERTION_RELEASE"}:
                item["uncertainty_ms"] = 10_000
        analysis = p009.replay(session)
        self.assertIn("TRIAL_DURATION_UNCERTAIN", {item["code"] for item in analysis["findings"]})
        self.assertEqual(p009.gate_candidates(session, analysis)["bounded_hold_verified"][0], "INSUFFICIENT_EVIDENCE")

    def test_connectivity_after_unlock_is_reported(self):
        path = fixture_tools.build_fixture(self.root / "unlocked", "network_after_unlock")
        codes = {item["code"] for item in p009.replay(self.load(path)["session"])["findings"]}
        self.assertIn("CONNECTIVITY_AFTER_UNLOCK", codes)

    def test_stop_before_acquire_is_detected(self):
        path = fixture_tools.build_fixture(self.root / "bad-order", "invalid_event_ordering")
        codes = {item["code"] for item in p009.replay(self.load(path)["session"])["findings"]}
        self.assertIn("STOP_BEFORE_ACQUIRE", codes)

    def test_cross_timebase_order_is_not_inferred(self):
        self.rewrite_session(lambda session: [event.update(timebase_id="observer-clock") for event in session["observations"] if event["event_type"] in {"LAN_OBSERVATION", "TAILSCALE_OBSERVATION"}])
        package = self.load()
        result = p009.replay(package["session"])
        self.assertIn("CROSS_TIMEBASE_ORDER_UNCERTAIN", {item["code"] for item in result["findings"]})

    def test_missing_recovery_is_reported(self):
        path = fixture_tools.build_fixture(self.root / "no-recovery", "missing_recovery")
        codes = {item["code"] for item in p009.replay(self.load(path)["session"])["findings"]}
        self.assertIn("RECOVERY_NOT_CONFIRMED", codes)

    def test_restart_during_trial_is_reported(self):
        path = fixture_tools.build_fixture(self.root / "restart", "restart_during_trial")
        codes = {item["code"] for item in p009.replay(self.load(path)["session"])["findings"]}
        self.assertIn("RESTART_DURING_TRIAL", codes)

    def test_unavailable_daemon_is_reported(self):
        path = fixture_tools.build_fixture(self.root / "daemon-unavailable", "unavailable_daemon")
        codes = {item["code"] for item in p009.replay(self.load(path)["session"])["findings"]}
        self.assertIn("DAEMON_UNAVAILABLE", codes)

    def test_incomplete_rollback_is_reported(self):
        path = fixture_tools.build_fixture(self.root / "rollback", "incomplete_rollback", origin="OPERATOR_RECORDED")
        codes = {item["code"] for item in p009.replay(self.load(path)["session"])["findings"]}
        self.assertIn("ROLLBACK_INCOMPLETE", codes)
        self.assertEqual(next(g["status"] for g in self.report(self.load(path))["gates"] if g["id"] == "rollback_verified"), "FAIL")

    def test_tailscale_reachability_without_authenticated_ssh_is_not_success(self):
        path = fixture_tools.build_fixture(self.root / "ts-no-ssh", "tailscale_failure_despite_lan_success", origin="OPERATOR_RECORDED")
        report = self.report(self.load(path))
        self.assertEqual(report["networking"]["tailscale"]["authenticated_ssh"], False)
        self.assertNotEqual(report["networking"]["tailscale"]["gate_status"], "PASS")

    def test_scheduled_awake_does_not_pass_scheduled_wake(self):
        report = self.report()
        self.assertEqual(report["decision"]["scheduled_wake"], "UNVERIFIED")
        self.assertEqual(next(g["status"] for g in report["gates"] if g["id"] == "scheduled_wake_verified"), "BLOCKED")

    def test_sigterm_release_and_exit_require_correlated_order(self):
        path = fixture_tools.build_fixture(self.root / "sigterm", "sigterm_cleanup", origin="OPERATOR_RECORDED")
        package = self.load(path)
        candidates = p009.gate_candidates(package["session"], p009.replay(package["session"]))
        self.assertEqual(candidates["sigterm_cleanup_verified"][0], "REVIEW_REQUIRED")

    def test_trial_authorization_cannot_exceed_five_minutes(self):
        self.rewrite_session(lambda session: session["trial"].update(authorized_duration_seconds=301))
        with self.assertRaises(p009.EvidenceError):
            self.load()

    def test_unsupported_schema_version_fails_safely(self):
        self.rewrite_session(lambda session: session.update(schema_version=2))
        with self.assertRaisesRegex(p009.EvidenceError, "schema validation failed"):
            self.load()

    def test_malformed_json_returns_cli_error_without_traceback(self):
        path = fixture_tools.build_fixture(self.root / "corrupt", "corrupted_json")
        result = self.run_cli("validate", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("valid UTF-8 JSON", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_non_finite_json_numbers_are_rejected(self):
        self.rewrite_session(lambda session: next(item for item in session["observations"] if item["event_type"] == "LAN_OBSERVATION")["details"].update(latency_ms=float("inf")))
        result = self.run_cli("validate", self.package_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("non-standard numeric", result.stderr)

    def test_hashes_are_checked_before_session_interpretation(self):
        path = fixture_tools.build_fixture(self.root / "bad-hash", "invalid_hashes")
        result = self.run_cli("validate", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("SHA-256 or size mismatch", result.stderr)

    def test_path_traversal_is_rejected(self):
        path = fixture_tools.build_fixture(self.root / "traversal", "path_traversal")
        result = self.run_cli("validate", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("path traversal", result.stderr)

    def test_oversized_evidence_file_is_rejected(self):
        path = fixture_tools.build_fixture(self.root / "oversized", "oversized_evidence")
        result = self.run_cli("validate", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("size limit", result.stderr)

    def test_symlink_escape_is_rejected(self):
        outside = self.root / "outside.txt"
        outside.write_text("synthetic")
        link = self.package_path / "evidence/escape.txt"
        link.symlink_to(outside)
        result = self.run_cli("validate", self.package_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)

    def test_unexpected_additional_file_is_rejected(self):
        (self.package_path / "extra.txt").write_text("unexpected")
        result = self.run_cli("validate", self.package_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unexpected files", result.stderr)

    def test_duplicate_manifest_file_identifier_is_rejected(self):
        manifest_path = self.package_path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][1]["file_id"] = manifest["files"][0]["file_id"]
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        result = self.run_cli("validate", self.package_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate file identifier", result.stderr)

    def test_credential_like_fields_are_rejected(self):
        self.rewrite_session(lambda session: session["observations"][0]["details"].update(password="never-store-this"))
        result = self.run_cli("validate", self.package_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("credential-like field", result.stderr)

    def test_report_does_not_emit_arbitrary_observation_details(self):
        self.rewrite_session(lambda session: session["observations"][0]["details"].update(operator_note="private diagnostic text"))
        result = self.run_cli("report", self.package_path)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("private diagnostic text", result.stdout)

    def test_markdown_report_collapses_untrusted_metadata_newlines(self):
        self.rewrite_session(lambda session: session["build_run"].update(build_id="build-1\n## injected heading"))
        result = self.run_cli("report", self.package_path)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("\n## injected heading", result.stdout)

    def test_same_evidence_generates_identical_reports(self):
        first = self.run_cli("report", self.package_path, "--format", "json")
        second = self.run_cli("report", self.package_path, "--format", "json")
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)

    def test_manifest_builder_is_deterministic_and_keeps_validation_read_only(self):
        staged = self.root / "staged"
        shutil.copytree(self.package_path, staged)
        (staged / "manifest.json").unlink()
        session_path = staged / "session.json"
        session = json.loads(session_path.read_text())
        session["evidence_files"] = []
        session_path.write_text(json.dumps(session, indent=2, sort_keys=True) + "\n")
        first = self.run_cli("manifest", staged)
        self.assertEqual(first.returncode, 0, first.stderr)
        manifest_bytes = (staged / "manifest.json").read_bytes()
        session_bytes = session_path.read_bytes()
        second = self.run_cli("manifest", staged, "--replace")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual((staged / "manifest.json").read_bytes(), manifest_bytes)
        self.assertEqual(session_path.read_bytes(), session_bytes)
        self.assertEqual(self.run_cli("validate", staged).returncode, 0)

    def test_manifest_builder_requires_explicit_replace(self):
        result = self.run_cli("manifest", self.package_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("use --replace", result.stderr)

    def test_event_enumeration_order_does_not_change_results(self):
        original = self.report()
        path = fixture_tools.build_fixture(self.root / "reverse", "valid_simulated_bounded_trial")
        session_path = path / "session.json"
        session = json.loads(session_path.read_text())
        session["observations"].reverse()
        session_path.write_text(json.dumps(session, indent=2, sort_keys=True) + "\n")
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        raw = session_path.read_bytes()
        next(item for item in manifest["files"] if item["path"] == "session.json").update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        reversed_report = self.report(self.load(path))
        self.assertEqual(original["gates"], reversed_report["gates"])
        self.assertEqual(original["timeline"], reversed_report["timeline"])

    def test_report_status_is_not_inferred_from_build_hashes(self):
        report = self.report()
        self.assertTrue(report["identity"]["package_sha256"])
        self.assertEqual(report["decision"]["hardware_acceptance"], "PENDING")

    def test_assertion_evidence_does_not_prove_network_continuity(self):
        path = fixture_tools.build_fixture(self.root / "power-only", "valid_simulated_bounded_trial", origin="OPERATOR_RECORDED")
        package = self.load(path)
        package["session"]["observations"] = [event for event in package["session"]["observations"] if event["event_type"] not in {"LAN_OBSERVATION", "TAILSCALE_OBSERVATION"}]
        candidates = p009.gate_candidates(package["session"], p009.replay(package["session"]))
        self.assertEqual(candidates["iokit_acquire_verified"][0], "REVIEW_REQUIRED")
        self.assertEqual(candidates["screen_locked_lan_verified"][0], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(candidates["screen_locked_tailscale_verified"][0], "INSUFFICIENT_EVIDENCE")

    def test_offline_evaluator_does_not_open_network_sockets(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network use")):
            package = self.load()
            p009.replay(package["session"])
            self.report(package)

    def test_p008_readiness_contract_remains_pending_and_unattended_unauthorized(self):
        source = (ROOT / "scripts/generate_p008_attestation.py").read_text()
        self.assertIn('"hardware_validation_status": "PENDING"', source)
        self.assertIn('"release_authorization_status": "NOT_AUTHORIZED"', source)
        for job in ("linux-protocol", "ios-cross-build", "ios-artifact-inspection", "ios-rootful-package"):
            self.assertIn(f'"{job}"', source)
        self.assertIn("PENDING", (ROOT / "docs/P008-RELEASE-READINESS.md").read_text())


if __name__ == "__main__":
    unittest.main()
