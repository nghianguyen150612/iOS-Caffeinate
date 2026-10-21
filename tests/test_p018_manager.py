from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGER_SOURCE = ROOT / "packaging/rootful/manager"


class P018ManagerReadinessTests(unittest.TestCase):
    """Exercise manager state gates with temporary paths and mocked system tools."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ioscaf-p018-manager-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.install = self.root / "installed"
        self.install.mkdir()
        self.socket = self.root / "run/ioscaffeinated.sock"
        self.socket.parent.mkdir()
        self.live_plist = self.root / "Library/LaunchDaemons/com.ioscaffeinate.daemon.plist"
        self.live_plist.parent.mkdir(parents=True)
        self.cli = self.fake_bin / "ios-caffeinate"
        self.preflight = self.root / "p018_package_preflight.py"
        self.python = self.fake_bin / "python3"
        self.preflight.write_text("# deterministic mocked package helper\n", encoding="utf-8")
        self.write_cli()
        self.write_tool(self.python, """#!/bin/sh
printf '%s\\n' 'package.decision=READY_FOR_OPERATOR_REVIEW' 'package.signer_provenance=VALID'
exit 0
""")

        manager = MANAGER_SOURCE.read_text(encoding="utf-8")
        replacements = {
            "CLI": self.cli,
            "MANIFEST": self.install / "SHA256SUMS",
            "SIGNING_STATE": self.install / "SIGNING-STATE",
            "P018_PREFLIGHT": self.preflight,
            "P009_EVIDENCE_TOOL": self.install / "p009_evidence.py",
            "P018_EVIDENCE_TOOL": self.install / "p018_evidence.py",
            "P018_EXPORT_VALIDATOR": self.install / "p018_validate_export.py",
            "PYTHON": self.python,
            "TEMPLATE": self.install / "launchd.plist",
            "LIVE_PLIST": self.live_plist,
            "SOCKET": self.socket,
        }
        for name, value in replacements.items():
            manager, count = re.subn(rf"^{name}='[^']*'$",
                                     f"{name}={shlex.quote(str(value))}", manager,
                                     count=1, flags=re.MULTILINE)
            self.assertEqual(count, 1, f"could not redirect manager {name} path")
        manager = manager.replace("/var/lib/ioscaffeinate/server-mode.json",
                                  str(self.root / "state/server-mode.json"))
        manager, count = re.subn(
            r"(?s)run_checks\(\) \{.*?\n\}\n\nfield_value\(\)",
            "run_checks() {\n    FAILURES=0\n    return 0\n}\n\nfield_value()",
            manager, count=1,
        )
        self.assertEqual(count, 1, "could not isolate package-integrity checks")
        self.manager = self.root / "manager"
        self.manager.write_text(manager, encoding="utf-8")
        self.manager.chmod(0o755)

        self.current_version = "0.1.0-2"
        self.write_tool(self.fake_bin / "dpkg-query", """#!/bin/sh
printf '%s\\n' '0.1.0-2'
""")
        self.write_tool(self.fake_bin / "dpkg-deb", """#!/bin/sh
case "${3:-}" in
  Package) printf '%s\\n' 'com.ioscaffeinate.cli' ;;
  Version) printf '%s\\n' '0.1.0-1' ;;
  Architecture) printf '%s\\n' 'iphoneos-arm' ;;
  *) exit 1 ;;
esac
""")
        self.write_tool(self.fake_bin / "dpkg", """#!/bin/sh
if [ "${1:-}" = '--compare-versions' ] && [ "${2:-}" = '0.1.0-1' ] &&
   [ "${3:-}" = 'lt' ] && [ "${4:-}" = '0.1.0-2' ]; then
  exit 0
fi
exit 1
""")
        self.candidate = self.root / "candidate.deb"
        self.candidate.write_bytes(b"synthetic package fixture; never installed\n")

    @staticmethod
    def write_tool(path: Path, body: str) -> None:
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def write_cli(self, *, registration: str = "NOT_REGISTERED",
                  runtime: str = "NOT_OBSERVED", ipc: str = "UNAVAILABLE",
                  assertion: str = "NONE", recovery: str = "HEALTHY") -> None:
        self.write_tool(self.cli, f"""#!/bin/sh
case "${{1:-}} ${{2:-}}" in
  'service status')
    printf '%s\\n' 'launchd.registration={registration}' 'runtime.process={runtime}' \\
      'ipc.availability={ipc}' 'assertion.state={assertion}' 'recovery.state={recovery}' ;;
  'schedule validate') printf '%s\\n' 'schedule.validation=PASS' ;;
  'server policy') printf '%s\\n' 'policy.config_valid=yes' ;;
  *) exit 2 ;;
esac
""")

    def run_manager(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PATH": f"{self.fake_bin}:{os.environ.get('PATH', '')}"}
        return subprocess.run(["sh", str(self.manager), *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=10,
                              check=False, env=env)

    def test_upgrade_is_blocked_by_active_or_unknown_service_state(self) -> None:
        self.write_cli(registration="UNKNOWN", runtime="OBSERVED", ipc="RESPONSIVE",
                       assertion="OWNED", recovery="CLEANUP_UNVERIFIED")
        result = self.run_manager("upgrade-check", str(self.candidate),
                                  "--rollback-artifact", str(self.root / "missing-old.deb"))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("LAUNCHD_REGISTRATION_NOT_CONFIRMED_ABSENT", result.stdout)
        self.assertIn("DAEMON_RUNTIME_NOT_CONFIRMED_STOPPED", result.stdout)
        self.assertIn("DAEMON_IPC_NOT_CONFIRMED_UNAVAILABLE", result.stdout)
        self.assertIn("ASSERTION_OWNERSHIP_NOT_CONFIRMED_CLEAR", result.stdout)
        self.assertIn("P014_RECOVERY_NOT_CONFIRMED_HEALTHY", result.stdout)
        self.assertIn("readiness=BLOCKED", result.stdout)
        self.assertTrue(self.candidate.exists())

    def test_stale_socket_lock_blocks_upgrade_and_is_preserved(self) -> None:
        lock = Path(str(self.socket) + ".lock")
        lock.write_text("stale fixture lock\n", encoding="utf-8")
        result = self.run_manager("upgrade-check", str(self.candidate))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("SOCKET_LOCK_STATE_UNVERIFIED", result.stdout)
        self.assertTrue(lock.is_file())
        self.assertEqual(lock.read_text(encoding="utf-8"), "stale fixture lock\n")

    def test_stale_default_socket_blocks_upgrade_and_is_preserved(self) -> None:
        self.socket.write_text("stale endpoint fixture\n", encoding="utf-8")
        result = self.run_manager("upgrade-check", str(self.candidate))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("DEFAULT_SOCKET_PRESENT_OR_UNSAFE", result.stdout)
        self.assertEqual(self.socket.read_text(encoding="utf-8"), "stale endpoint fixture\n")

    def test_live_plist_blocks_upgrade_and_is_preserved(self) -> None:
        self.live_plist.write_text("operator fixture\n", encoding="utf-8")
        result = self.run_manager("upgrade-check", str(self.candidate))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("LIVE_LAUNCHD_PLIST_REQUIRES_REVIEW", result.stdout)
        self.assertEqual(self.live_plist.read_text(encoding="utf-8"), "operator fixture\n")

    def test_missing_rollback_artifact_and_persistent_data_review_block_upgrade(self) -> None:
        result = self.run_manager("upgrade-check", str(self.candidate))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("ROLLBACK_ARTIFACT_NOT_SUPPLIED", result.stdout)
        self.assertIn("PERSISTENT_DATA_PRESERVATION_REQUIRES_OPERATOR_REVIEW", result.stdout)
        self.assertIn("persistent_data_preservation=REVIEW_REQUIRED", result.stdout)
        self.assertIn("operator_install_authorization=NOT_GRANTED", result.stdout)

    def test_missing_rollback_file_is_not_verified(self) -> None:
        result = self.run_manager("rollback-check", str(self.root / "absent.deb"))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("package or matching .sha256 sidecar is missing", result.stdout)
        self.assertNotIn("rollback.readiness=READY_FOR_OPERATOR_REVIEW", result.stdout)

    def test_malformed_rollback_sidecar_is_not_verified(self) -> None:
        artifact = self.root / "previous.deb"
        artifact.write_bytes(b"synthetic previous artifact; never installed\n")
        Path(str(artifact) + ".sha256").write_text("malformed sidecar\n", encoding="utf-8")
        result = self.run_manager("rollback-check", str(artifact))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("SHA-256 mismatch or no hash tool", result.stdout)

    def test_uninstall_does_not_convert_unknown_launchd_to_not_registered(self) -> None:
        self.write_cli(registration="UNVERIFIED")
        result = self.run_manager("uninstall-check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("launchd registration is UNVERIFIED", result.stdout)
        self.assertIn("uninstall_action=NOT_PERFORMED", result.stdout)


if __name__ == "__main__":
    unittest.main()
