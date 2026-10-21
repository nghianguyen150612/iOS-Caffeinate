"""Host-side checks for P013 CLI contracts and lifecycle safety boundaries."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "build/test/ios-caffeinate"


class P013ServiceCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = subprocess.run([str(ROOT / "scripts/build-linux-test.sh")], cwd=ROOT,
                                text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(f"Linux C11 build failed:\n{result.stdout}\n{result.stderr}")

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(CLI), *args], cwd=ROOT, text=True,
                              capture_output=True, timeout=5)

    def test_service_commands_are_in_help(self) -> None:
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for action in ("status", "doctor", "plan", "recovery", "reset", "enable", "disable", "start", "stop", "restart"):
            self.assertIn(action, result.stdout)

    def test_recovery_reset_requires_explicit_review_and_safe_state(self) -> None:
        usage = self.run_cli("service", "recovery", "reset")
        self.assertEqual(usage.returncode, 2)
        self.assertIn("--reviewed-cleanup", usage.stderr)
        self.assertIn("--reviewed-supervisor-state", usage.stderr)

        result = self.run_cli("service", "recovery", "reset", "--reviewed-cleanup",
                              "--reviewed-supervisor-state")
        self.assertIn(result.returncode, (3, 4, 6))
        self.assertIn("changed=no", result.stderr)

    def test_read_only_service_commands_report_no_changes(self) -> None:
        for action in ("status", "doctor", "plan"):
            with self.subTest(action=action):
                result = self.run_cli("service", action)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("changed=no", result.stdout)
                self.assertIn("launchd.mutating_compatibility=UNVERIFIED" if action != "plan"
                              else "launchctl_mutation=UNVERIFIED", result.stdout)
                self.assertIn("boot_persistence=UNVERIFIED", result.stdout)
                self.assertIn("daemon.state=UNKNOWN", result.stdout)
                self.assertIn("assertion.state=UNKNOWN", result.stdout)

    def test_mutating_operations_fail_closed_on_host(self) -> None:
        expected = 4 if os.geteuid() != 0 else None
        for action in ("enable", "disable", "start", "stop", "restart"):
            with self.subTest(action=action):
                result = self.run_cli("service", action)
                if expected is not None:
                    self.assertEqual(result.returncode, expected)
                else:
                    self.assertIn(result.returncode, (3, 5, 6))
                self.assertIn("changed=no", result.stderr)

    def test_package_removal_blocks_live_or_unknown_service_state(self) -> None:
        prerm = (ROOT / "packaging/rootful/DEBIAN/prerm").read_text()
        self.assertIn("/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist", prerm)
        self.assertIn("launchd.registration", prerm)
        self.assertIn("NOT_REGISTERED", prerm)
        self.assertIn("runtime.process", prerm)
        self.assertIn("ipc.availability", prerm)
        self.assertIn("refusing package removal", prerm)
        self.assertNotIn("launchctl load", prerm)
        subprocess.run(["sh", "-n", str(ROOT / "packaging/rootful/DEBIAN/prerm")], check=True)

    def test_package_removal_gate_with_injected_status_fixtures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ioscaf-p013-prerm-") as temporary:
            root = Path(temporary)
            socket = root / "run/daemon.sock"
            socket.parent.mkdir()
            live = root / "Library/LaunchDaemons/com.ioscaffeinate.daemon.plist"
            live.parent.mkdir(parents=True)
            cli = root / "ios-caffeinate"
            manager = root / "ioscaffeinate-manager"
            script = (ROOT / "packaging/rootful/DEBIAN/prerm").read_text()
            script = script.replace("/var/run/ioscaffeinated.sock", str(socket))
            script = script.replace("/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist", str(live))
            script = script.replace("/usr/local/bin/ios-caffeinate", str(cli))
            script = script.replace("/usr/local/libexec/ioscaffeinate-manager", str(manager))
            prerm = root / "prerm"
            prerm.write_text(script)
            script_path = str(prerm)
            manager.write_text("#!/bin/sh\n[ \"${1:-}\" = uninstall-check ]\n")
            manager.chmod(0o755)

            state_dir = root / "var/lib/ioscaffeinate"
            log_dir = root / "var/log/ioscaffeinate"
            state_dir.mkdir(parents=True)
            log_dir.mkdir(parents=True)
            schedule = state_dir / "schedules.json"
            log = log_dir / "daemon.log"
            schedule.write_text("preserve schedule\n")
            log.write_text("preserve log\n")

            def run_with_status(registration: str, runtime: str, ipc: str) -> subprocess.CompletedProcess[str]:
                cli.write_text(
                    "#!/bin/sh\n"
                    f"printf '%s\\n' 'launchd.registration={registration}' 'runtime.process={runtime}' 'ipc.availability={ipc}' 'assertion.state=NONE' 'recovery.state=HEALTHY'\n"
                )
                cli.chmod(0o755)
                return subprocess.run(["sh", script_path, "remove"], text=True,
                                      capture_output=True, timeout=3)

            clean = run_with_status("NOT_REGISTERED", "NOT_OBSERVED", "UNAVAILABLE")
            self.assertEqual(clean.returncode, 0, clean.stderr)
            active = run_with_status("REGISTERED", "UNVERIFIED", "UNAVAILABLE")
            self.assertEqual(active.returncode, 1)
            self.assertIn("active or uncertain", active.stderr)
            unknown = run_with_status("UNVERIFIED", "NOT_OBSERVED", "UNAVAILABLE")
            self.assertEqual(unknown.returncode, 1)

            cli.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'launchd.registration=NOT_REGISTERED' 'runtime.process=NOT_OBSERVED' 'ipc.availability=UNAVAILABLE' 'assertion.state=UNKNOWN' 'recovery.state=HEALTHY'\n"
            )
            cli.chmod(0o755)
            unresolved_assertion = subprocess.run(["sh", script_path, "remove"], text=True,
                                                  capture_output=True, timeout=3)
            self.assertEqual(unresolved_assertion.returncode, 1)
            self.assertIn("assertion=UNKNOWN", unresolved_assertion.stderr)
            cli.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'launchd.registration=NOT_REGISTERED' 'runtime.process=NOT_OBSERVED' 'ipc.availability=UNAVAILABLE' 'assertion.state=NONE' 'recovery.state=RECOVERY_UNVERIFIED'\n"
            )
            cli.chmod(0o755)
            unresolved_recovery = subprocess.run(["sh", script_path, "remove"], text=True,
                                                 capture_output=True, timeout=3)
            self.assertEqual(unresolved_recovery.returncode, 1)
            self.assertIn("recovery=RECOVERY_UNVERIFIED", unresolved_recovery.stderr)

            live.write_text("unrelated content\n")
            collision = run_with_status("NOT_REGISTERED", "NOT_OBSERVED", "UNAVAILABLE")
            self.assertEqual(collision.returncode, 1)
            self.assertIn("live LaunchDaemon plist", collision.stderr)
            live.unlink()
            socket.write_text("leave it\n")
            endpoint = run_with_status("NOT_REGISTERED", "NOT_OBSERVED", "UNAVAILABLE")
            self.assertEqual(endpoint.returncode, 1)
            self.assertIn("default daemon endpoint", endpoint.stderr)
            self.assertEqual(schedule.read_text(), "preserve schedule\n")
            self.assertEqual(log.read_text(), "preserve log\n")

            socket.unlink()
            (Path(str(socket) + ".lock")).write_text("stale lock\n")
            stale_lock = run_with_status("NOT_REGISTERED", "NOT_OBSERVED", "UNAVAILABLE")
            self.assertEqual(stale_lock.returncode, 1)
            self.assertIn("socket lock", stale_lock.stderr)

            Path(str(socket) + ".lock").unlink()
            manager.write_text("#!/bin/sh\nexit 1\n")
            manager.chmod(0o755)
            manager_incomplete = run_with_status("NOT_REGISTERED", "NOT_OBSERVED", "UNAVAILABLE")
            self.assertEqual(manager_incomplete.returncode, 1)
            self.assertIn("persistent-data review", manager_incomplete.stderr)

    def test_managed_configuration_disables_crash_relaunch(self) -> None:
        source = (ROOT / "src/service.c").read_text()
        self.assertIn('<key>KeepAlive</key><false/>', source)
        self.assertIn('<key>RunAtLoad</key><false/>', source)
        self.assertIn("iOS 12 launchctl semantics or a required verified operation adapter are UNVERIFIED", source)
        self.assertIn("service_install_managed_plist", source)

    def test_no_implicit_reboot_network_or_service_registration(self) -> None:
        source = (ROOT / "src/service.c").read_text()
        for forbidden in ("reboot(", "system(", "popen(", "launchctl bootstrap", "launchctl load"):
            self.assertNotIn(forbidden, source)
        self.assertIn("/bin/launchctl", source)
        self.assertIn("posix_spawn", source)
        self.assertIn("service_child_environment", source)
        self.assertNotIn("extern char **environ", source)
        self.assertNotIn("system(", (ROOT / "packaging/rootful/DEBIAN/prerm").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
