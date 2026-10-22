import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "build" / "test" / "ios-caffeinate"


class P015PolicyCliTests(unittest.TestCase):
    def setUp(self):
        if not BINARY.is_file():
            self.skipTest("build the C11 CLI with scripts/build-linux-test.sh first")
        self.tmp = tempfile.TemporaryDirectory(prefix="ioscaffeinate-p015-cli-")
        self.root = Path(self.tmp.name)
        self.v1 = self.root / "v1.json"
        self.v2 = self.root / "v2.json"
        self.socket = self.root / "missing.sock"
        self.v1_data = b'{"version":1,"policy":"observe_only"}'
        self.v2_data = (
            b'{"version":2,"policy":"bounded_session","session":{'
            b'"max_duration_seconds":300,"require_operator_confirmation":true,'
            b'"allow_automatic_start":false,"allow_restart_resume":false}}'
        )
        self.write_private(self.v1, self.v1_data)
        self.write_private(self.v2, self.v2_data)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def write_private(path, data):
        path.write_bytes(data)
        path.chmod(0o600)

    def run_cli(self, config, *args):
        return subprocess.run(
            [str(BINARY), "--socket", str(self.socket), "--server-config", str(config),
             "server", "policy", *args],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def test_show_validate_and_v1_migration_are_read_only(self):
        before = (self.v1.stat().st_ino, self.v1.stat().st_mtime_ns, self.v1.read_bytes())
        show = self.run_cli(self.v1, "show")
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn("policy.schema_version=1", show.stdout)
        self.assertIn("policy.mode=OBSERVE_ONLY", show.stdout)
        self.assertIn("policy.apply_supported=no", show.stdout)

        valid = self.run_cli(self.v1, "validate")
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertIn("policy.config_valid=yes", valid.stdout)

        preview = self.run_cli(self.v1, "migrate", "--dry-run")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn('"version":2,"policy":"observe_only"', preview.stdout)
        self.assertIn("migration.write_performed=no", preview.stdout)
        self.assertIn("migration.session_activation=no", preview.stdout)
        self.assertEqual((self.v1.stat().st_ino, self.v1.stat().st_mtime_ns,
                          self.v1.read_bytes()), before)
        self.assertFalse((self.root / "server-mode.json").exists())

    def test_v2_explain_fails_closed_without_hardware_and_recovery(self):
        before = self.v2.read_bytes()
        result = self.run_cli(self.v2, "explain")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("policy.requested=yes", result.stdout)
        self.assertIn("policy.config_stored=yes", result.stdout)
        self.assertIn("decision=BLOCK_RECOVERY", result.stdout)
        self.assertIn("eligible=no", result.stdout)
        self.assertIn("execution_authorized=no", result.stdout)
        self.assertIn("operator_authorization=NOT_GRANTED", result.stdout)
        self.assertIn("runtime_action_performed=no", result.stdout)
        self.assertIn("recovery.supervisor=UNVERIFIED", result.stdout)
        self.assertIn("evidence.battery_safety.state=PENDING", result.stdout)
        self.assertIn("evidence.battery_safety.confidence=UNKNOWN", result.stdout)
        self.assertIn("evidence.thermal_safety.state=PENDING", result.stdout)
        self.assertIn("evidence.p013_lifecycle_compatibility.state=PENDING", result.stdout)
        self.assertNotIn("RUNNING", result.stdout)
        self.assertNotIn("PRIVATE_KEY", result.stdout)
        self.assertEqual(self.v2.read_bytes(), before)

    def test_future_schema_is_rejected_and_apply_is_not_a_command(self):
        future = self.root / "future.json"
        self.write_private(future, b'{"version":9,"policy":"bounded_session"}')
        invalid = self.run_cli(future, "validate")
        self.assertEqual(invalid.returncode, 1)
        self.assertIn("policy.config_status=UNSUPPORTED", invalid.stdout)

        before = self.v2.read_bytes()
        apply = self.run_cli(self.v2, "apply", "--file", str(self.v2), "--confirm")
        self.assertEqual(apply.returncode, 2)
        self.assertEqual(self.v2.read_bytes(), before)
        self.assertFalse((self.root / "server-mode.json").exists())


if __name__ == "__main__":
    unittest.main()
