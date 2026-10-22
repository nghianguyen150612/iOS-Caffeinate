"""End-to-end mocked diagnostics; the result is deliberately nonphysical."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "build/test/ios-caffeinate"
DAEMON = ROOT / "build/test/ios-caffeinated"

import sys
sys.path.insert(0, str(ROOT / "tests"))
from p020_fixtures import release_manifest  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
import p020_release_gate  # noqa: E402


class P020MockedEndToEndTests(unittest.TestCase):
    def test_package_recovery_policy_schedule_telemetry_evidence_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ioscaf-p020-e2e-") as temporary:
            root = Path(temporary)
            socket_path = root / "daemon.sock"
            schedule_path = root / "schedules.json"
            recovery_path = root / "recovery.json"
            server_config_path = root / "server-mode.json"
            evidence_path = root / "evidence"
            record = {
                "schema_version": 1, "policy_version": 1, "generation": 1,
                "process_state": "CLEAN", "cleanup_state": "CONFIRMED",
                "last_exit_class": "GRACEFUL_CONFIRMED", "last_exit_signal": 0,
                "attempts": [], "last_event_id": 0, "last_failure_event_id": 0,
                "last_failure_monotonic_ns": 0, "last_failure_wall_utc_seconds": 0,
                "last_failure_clock_id": "", "healthy_since_monotonic_ns": 0,
                "healthy_clock_id": "",
            }
            # Match the P014 journal's schema field order, as its native parser
            # intentionally rejects unknown or reordered persisted records.
            recovery_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            recovery_path.chmod(0o600)
            env = {**os.environ, "IOSCAFFEINATE_MOCK_NO_POWER_EFFECT": "1"}

            # 1. Package status: this Linux fixture is not an installed rootful package.
            package_result = subprocess.run([str(CLI), "package", "status", "--json"], capture_output=True, text=True, timeout=8)
            package = json.loads(package_result.stdout)
            self.assertIn(package["status"], {"UNAVAILABLE", "INCOMPLETE"})
            self.assertEqual(package["hardware_acceptance"], "NOT_ESTABLISHED")

            # Start only the compiled Linux mock daemon; it cannot acquire an iOS assertion.
            daemon = subprocess.Popen(
                [str(DAEMON), "--socket", str(socket_path), "--schedules", str(schedule_path),
                 "--recovery-state", str(recovery_path), "--foreground"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=env,
            )
            def stop_mock_daemon() -> None:
                if daemon.poll() is None:
                    daemon.terminate()
                    daemon.wait(timeout=4)
                if daemon.stderr is not None:
                    daemon.stderr.close()
            self.addCleanup(stop_mock_daemon)
            common = [str(CLI), "--socket", str(socket_path), "--schedule-state", str(schedule_path),
                      "--recovery-state", str(recovery_path), "--server-config", str(server_config_path)]
            deadline = time.monotonic() + 4
            status_result = None
            while time.monotonic() < deadline:
                if daemon.poll() is not None:
                    self.fail("mock daemon exited before status was available")
                status_result = subprocess.run(common + ["status"], capture_output=True, text=True, timeout=5)
                if status_result.returncode == 0:
                    break
                time.sleep(0.02)
            self.assertIsNotNone(status_result)
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            self.assertIn("recovery_state=HEALTHY", status_result.stdout)
            self.assertIn("recovery_cleanup=CONFIRMED", status_result.stdout)
            self.assertIn("recovery_restart_eligibility=BLOCKED_SUPERVISOR_UNVERIFIED", status_result.stdout)

            # 2. Recovery, 3. unattended policy, 4. schedule authorization.
            recovery = status_result.stdout
            self.assertNotIn("automatic_restart=yes", recovery)
            policy = subprocess.run(common + ["server", "doctor"], capture_output=True, text=True, timeout=5)
            self.assertEqual(policy.returncode, 0, policy.stderr)
            self.assertIn("unattended_authorized=no", policy.stdout)
            schedule = subprocess.run(common + ["schedule", "doctor"], capture_output=True, text=True, timeout=5)
            self.assertEqual(schedule.returncode, 0, schedule.stderr)
            self.assertIn("schedule.executor=NOT_AUTHORIZED", schedule.stdout)
            self.assertIn("schedule.policy_reason=SCHEDULE_EXECUTOR_NOT_AUTHORIZED", schedule.stdout)

            # 5. Telemetry is diagnostic and may be unavailable; it grants no authorization.
            telemetry = subprocess.run(common + ["health", "doctor"], capture_output=True, text=True, timeout=5)
            self.assertEqual(telemetry.returncode, 0, telemetry.stderr)
            self.assertIn("doctor.assertion_acquisition=no", telemetry.stdout)

            # 6. Evidence inventory is empty and remains explicitly non-accepted.
            evidence = subprocess.run(common + ["evidence", "inventory", "--json", "--root", str(evidence_path)],
                                      capture_output=True, text=True, timeout=8)
            self.assertIn(evidence.returncode, (0, 1), evidence.stderr)
            evidence_data = json.loads(evidence.stdout)
            self.assertEqual(evidence_data["hardware_evidence_accepted"], "NOT_ESTABLISHED")

            # 7. Feed only unsigned cloud fixture evidence to the offline gate.
            manifest_root = root / "release-evidence"
            head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
            base = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "origin/main"], check=True, capture_output=True, text=True).stdout.strip()
            manifest = release_manifest(manifest_root, source_sha=head, base_sha=base)
            manifest_path = manifest_root / "release-manifest.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            assessment = p020_release_gate.assess(manifest_path, head)
            self.assertEqual(assessment["decision"], "RELEASE_BLOCKED")
            self.assertFalse(assessment["publication_authorized"])
            self.assertTrue(all(item["status"] == "PENDING" for item in assessment["hardware_gates"].values()))

            chain_report = {
                "schema_version": 1,
                "evidence_class": "MOCK",
                "device_actions": "NOT_PERFORMED",
                "stages": {
                    "package_status": package["status"],
                    "recovery": "HEALTHY / cleanup CONFIRMED / automatic restart blocked without supervisor evidence",
                    "policy": "unattended_authorized=no",
                    "schedule": "NOT_AUTHORIZED by policy",
                    "telemetry": "DIAGNOSTIC_ONLY",
                    "evidence": evidence_data["hardware_evidence_accepted"],
                    "release_decision": assessment["decision"],
                },
                "publication_authorized": assessment["publication_authorized"],
            }
            output_dir = ROOT / "build/p020"
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "P020-E2E-MOCKED-INTEGRATION.json").write_text(
                json.dumps(chain_report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            if daemon.poll() is None:
                daemon.terminate()
                self.assertEqual(daemon.wait(timeout=4), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
