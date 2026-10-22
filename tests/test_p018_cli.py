from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "build/test/ios-caffeinate"


class P018CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not CLI.is_file():
            build = subprocess.run([str(ROOT / "scripts/build-linux-test.sh")],
                                   cwd=ROOT, capture_output=True, text=True, timeout=120)
            if build.returncode:
                raise AssertionError(build.stdout + build.stderr)

    def run_cli(self, *args: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(CLI), *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=timeout, check=False)

    def test_top_level_and_topic_help(self) -> None:
        for args in (("--help",), ("help",), ("help", "schedule"),
                     ("help", "service"), ("help", "server"),
                     ("help", "package"), ("help", "evidence")):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Read-only diagnostics", result.stdout) if len(args) == 1 else None
        self.assertIn("unauthorized", self.run_cli("help", "schedule").stdout.lower())
        self.assertIn("maximum 300 seconds", self.run_cli("help", "server").stdout)
        self.assertIn("maximum of 300 seconds", self.run_cli("help", "power").stdout)
        self.assertIn("24 hours", self.run_cli("help", "power").stdout)
        self.assertIn("unverified", self.run_cli("help", "service").stdout.lower())
        self.assertIn("not accepted", self.run_cli("help", "evidence").stdout)

    def test_version_reports_source_build_and_schema_metadata(self) -> None:
        result = self.run_cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        self.assertEqual(fields["package.identifier"], "com.ioscaffeinate.cli")
        self.assertEqual(fields["package.version"], "0.1.0-1")
        self.assertRegex(fields["source.commit"], r"^[0-9a-f]{40}$")
        self.assertIn(fields["release.channel"], {"DEVELOPMENT", "PRE_RELEASE", "STABLE"})
        self.assertEqual(fields["schema.p018"], "1")

    def test_existing_status_and_manual_hold_duration_syntax_remain(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ioscaf-p018-legacy-") as temporary:
            missing_socket = str(Path(temporary) / "daemon.sock")
            status = self.run_cli("--socket", missing_socket, "status")
            self.assertEqual(status.returncode, 1)
            self.assertIn("daemon", (status.stderr + status.stdout).lower())
            accepted_duration = self.run_cli("--socket", missing_socket, "start", "--for", "24h")
            self.assertEqual(accepted_duration.returncode, 1, accepted_duration.stderr)
            too_long = self.run_cli("--socket", missing_socket, "start", "--for", "24h1s")
            self.assertEqual(too_long.returncode, 2)
            self.assertIn("Invalid duration", too_long.stderr)

    def test_server_and_schedule_limits_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ioscaf-p018-limits-") as temporary:
            missing_socket = str(Path(temporary) / "daemon.sock")
            trial_300 = self.run_cli("--socket", missing_socket, "server", "trial", "start", "--for", "300s")
            self.assertEqual(trial_300.returncode, 1, trial_300.stderr)
            trial_301 = self.run_cli("--socket", missing_socket, "server", "trial", "start", "--for", "301s")
            self.assertEqual(trial_301.returncode, 2)
            schedule_301 = self.run_cli("--schedule-state", str(Path(temporary) / "schedules.json"),
                                        "schedule", "add", "--daily", "12:00", "--for", "301s")
            self.assertEqual(schedule_301.returncode, 2)
            self.assertIn("300 seconds", schedule_301.stderr)

    def test_read_only_doctor_json_is_structured_and_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ioscaf-p018-doctor-") as temporary:
            root = Path(temporary)
            schedule = root / "schedules.json"
            schedule.write_text('{"version":1,"next_id_counter":1,"schedules":[]}\n')
            schedule.chmod(0o600)
            before = sorted((path.relative_to(root).as_posix(), path.read_bytes())
                            for path in root.rglob("*") if path.is_file())
            result = self.run_cli("--socket", str(root / "missing.sock"),
                                  "--schedule-state", str(schedule),
                                  "--server-config", str(root / "missing-policy.json"),
                                  "--recovery-state", str(root / "missing-recovery.json"),
                                  "doctor", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["changed"], "no")
            self.assertIs(report["read_only"], True)
            checks = {check["component"]: check for check in report["checks"]}
            self.assertEqual(checks["p013_launchd"]["status"], "PENDING_VERIFICATION")
            self.assertEqual(checks["schedule_executor"]["status"], "UNSUPPORTED")
            self.assertEqual(checks["hardware_acceptance"]["status"], "PENDING_VERIFICATION")
            self.assertTrue(all("next_safe_step" in check for check in report["checks"]))
            after = sorted((path.relative_to(root).as_posix(), path.read_bytes())
                           for path in root.rglob("*") if path.is_file())
            self.assertEqual(after, before)
            self.assertFalse((root / "missing.sock").exists())

    def test_package_and_evidence_json_are_valid_and_versioned(self) -> None:
        package = self.run_cli("package", "status", "--json")
        self.assertEqual(package.returncode, json.loads(package.stdout)["manager_exit_code"])
        package_data = json.loads(package.stdout)
        self.assertEqual(package_data["schema_version"], 1)
        self.assertEqual(package_data["command"], "package.status")
        self.assertNotEqual(package_data["manager_exit_code"], 2)
        self.assertEqual(package_data["hardware_acceptance"], "NOT_ESTABLISHED")
        self.assertEqual(package_data["cleanup"], "not_applicable")
        if package_data["error_code"] is not None:
            self.assertTrue(package_data["error_reason"])
            self.assertTrue(package_data["next_safe_step"])
        verify = self.run_cli("package", "verify", "--json")
        verify_data = json.loads(verify.stdout)
        self.assertEqual(verify_data["command"], "package.verify")
        self.assertNotEqual(verify_data["manager_exit_code"], 2)
        inventory = self.run_cli("evidence", "inventory", "--json")
        self.assertIn(inventory.returncode, (0, 1))
        evidence_data = json.loads(inventory.stdout)
        self.assertEqual(evidence_data["schema_version"], 1)
        self.assertEqual(evidence_data["hardware_evidence_accepted"], "NOT_ESTABLISHED")

    def test_ipc_timeout_is_bounded_and_does_not_start_a_daemon(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ioscaf-p018-ipc-") as temporary:
            socket_path = str(Path(temporary) / "silent.sock")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(socket_path)
            listener.listen(1)
            finished = threading.Event()

            def silent_peer() -> None:
                try:
                    connection, _ = listener.accept()
                    with connection:
                        connection.recv(4096)
                        finished.wait(3)
                finally:
                    listener.close()

            thread = threading.Thread(target=silent_peer, daemon=True)
            thread.start()
            started = time.monotonic()
            result = self.run_cli("--socket", socket_path, "health", "status", timeout=8)
            elapsed = time.monotonic() - started
            finished.set()
            thread.join(timeout=1)
            self.assertLess(elapsed, 5.0)
            self.assertFalse(result.stderr and "timed out" in result.stderr.lower())
            self.assertTrue(Path(socket_path).exists())
            self.assertIn(result.returncode, (0, 1), result.stderr)

    def test_invalid_top_level_command_keeps_usage_exit_code(self) -> None:
        result = self.run_cli("unrecognized-command")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error.code=INVALID_ARGUMENT", result.stderr)
        self.assertIn("changed=no", result.stderr)
        self.assertIn("cleanup=not_applicable", result.stderr)


if __name__ == "__main__":
    unittest.main()
