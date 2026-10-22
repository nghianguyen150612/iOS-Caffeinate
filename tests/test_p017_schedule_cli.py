import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "build/test/ios-caffeinate"


class P017ScheduleCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ioscaf-p017-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schedule_path = self.root / "schedules.json"
        self.socket_path = self.root / "missing.sock"
        self.recovery_path = self.root / "missing-recovery.json"
        target = 1792747800  # 2026-10-23T09:30:00Z, fixed fixture instant
        state = {
            "version": 1,
            "next_id_counter": 3,
            "schedules": [
                {
                    "id": "legacy-long",
                    "type": 2,
                    "target_time": 0,
                    "hour": 9,
                    "minute": 30,
                    "days_mask": 0,
                    "duration": 86400,
                    "tz": "Asia/Ho_Chi_Minh",
                    "enabled": True,
                    "last_fired_time": 0,
                },
                {
                    "id": "one-time",
                    "type": 1,
                    "target_time": target,
                    "hour": 0,
                    "minute": 0,
                    "days_mask": 0,
                    "duration": 300,
                    "tz": "",
                    "enabled": True,
                    "last_fired_time": 0,
                },
                {
                    "id": "overlap-time",
                    "type": 1,
                    "target_time": target + 120,
                    "hour": 0,
                    "minute": 0,
                    "days_mask": 0,
                    "duration": 300,
                    "tz": "",
                    "enabled": True,
                    "last_fired_time": 0,
                },
                {
                    "id": "isolated-time",
                    "type": 1,
                    "target_time": target + 86400,
                    "hour": 0,
                    "minute": 0,
                    "days_mask": 0,
                    "duration": 300,
                    "tz": "",
                    "enabled": True,
                    "last_fired_time": 0,
                },
            ],
        }
        self.schedule_path.write_text(json.dumps(state, indent=2) + "\n")
        os.chmod(self.schedule_path, 0o600)
        self.original = self.schedule_path.read_bytes()

    def call_cli(self, *args, code=0):
        result = subprocess.run(
            [str(CLI), "--socket", str(self.socket_path),
             "--schedule-state", str(self.schedule_path),
             "--recovery-state", str(self.recovery_path), "schedule", *args],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, code, (args, result.stdout, result.stderr))
        return result

    def test_read_only_preview_and_runtime_distinction_offline(self):
        at = "2026-10-21T12:00:00Z"
        result = self.call_cli("next", "--at", at)
        self.assertIn("schedule.definitions_source=STORAGE", result.stdout)
        self.assertIn("schedule.runtime_state=NOT_INFERRED_FROM_STORAGE", result.stdout)
        self.assertIn("schedule.next_utc=", result.stdout)
        self.assertIn("schedule.outcome=TIMEZONE_UNVERIFIED", result.stdout)
        self.assertIn("LEGACY_DURATION_EXCEEDS_POLICY", result.stdout)
        self.assertIn("execution=NOT_GUARANTEED", result.stdout)
        self.assertFalse(self.socket_path.exists(), "next does not start the daemon")
        self.assertEqual(self.schedule_path.read_bytes(), self.original)

        doctor = self.call_cli("doctor", "--at", at)
        self.assertIn("schedule.runtime=UNAVAILABLE", doctor.stdout)
        self.assertIn("schedule.recovery=UNKNOWN", doctor.stdout)
        self.assertIn("schedule.recovery_journal=MISSING", doctor.stdout)
        self.assertIn("schedule.policy_reason=SCHEDULE_EXECUTOR_NOT_AUTHORIZED", doctor.stdout)
        self.assertIn("schedule.telemetry=UNKNOWN_NOT_SAMPLED", doctor.stdout)
        self.assertIn("schedule.wake_capability=UNVERIFIED", doctor.stdout)
        self.assertFalse(self.socket_path.exists())

    def test_validate_and_explain_preserve_v1_data(self):
        validated = self.call_cli("validate")
        self.assertIn("schedule.validation=PASS", validated.stdout)
        self.assertIn("legacy_duration_exceeds_policy=1", validated.stdout)
        self.assertIn("timezone_resolution_unverified=1", validated.stdout)
        self.assertEqual(self.schedule_path.read_bytes(), self.original)

        explained = self.call_cli("explain", "legacy-long", "--at",
                                  "2026-10-21T12:00:00Z")
        self.assertIn("schedule.id=legacy-long", explained.stdout)
        self.assertIn("schedule.execution_reason=SCHEDULE_EXECUTOR_NOT_AUTHORIZED", explained.stdout)
        self.assertIn("schedule.horizon_days=370", explained.stdout)
        self.assertEqual(self.schedule_path.read_bytes(), self.original)

    def test_explain_limits_conflicts_to_the_requested_schedule(self):
        explained = self.call_cli("explain", "one-time", "--at", "2026-10-21T12:00:00Z")
        self.assertIn("schedule.conflicts_scope=one-time", explained.stdout)
        self.assertIn("conflict.first=one-time", explained.stdout)
        self.assertIn("conflict.second=overlap-time", explained.stdout)
        self.assertNotIn("isolated-time", explained.stdout)

    def test_conflicts_and_dry_run_are_read_only(self):
        conflict = self.call_cli("conflicts", "--at", "2026-10-21T12:00:00Z")
        self.assertIn("schedule.conflicts=INCOMPLETE", conflict.stdout)
        self.assertEqual(self.schedule_path.read_bytes(), self.original)

        listing = self.call_cli("list").stdout
        generation = next(line.split("=", 1)[1] for line in listing.splitlines()
                          if line.startswith("schedule.generation="))
        preview = subprocess.run(
            [str(CLI), "--socket", str(self.socket_path),
             "--schedule-state", str(self.schedule_path),
             "--recovery-state", str(self.recovery_path), "schedule", "disable",
             "legacy-long", "--if-generation", generation, "--dry-run"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("schedule.write_performed=no", preview.stdout)
        self.assertEqual(self.schedule_path.read_bytes(), self.original)

    def test_duplicate_json_keys_fail_validation(self):
        self.schedule_path.write_text(
            '{"version":1,"version":1,"next_id_counter":1,"schedules":[]}\n'
        )
        os.chmod(self.schedule_path, 0o600)
        result = self.call_cli("validate", code=1)
        self.assertIn("schedule.storage=INVALID", result.stderr)

    def test_at_requires_explicit_timezone(self):
        self.call_cli("next", "--at", "2026-10-21T12:00:00", code=2)


if __name__ == "__main__":
    unittest.main()
