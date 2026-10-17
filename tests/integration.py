#!/usr/bin/env python3
"""Unprivileged Linux mock tests. No iOS power or network effects are tested."""
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAEMON = ROOT / "build/test/ios-caffeinated"
CLI = ROOT / "build/test/ios-caffeinate"


class Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ioscaf-")
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "test.sock")
        self.sched_path = str(Path(self.temp.name) / "schedules.json")
        self.server_config_path = str(Path(self.temp.name) / "server-mode.json")
        self.processes = []
        self.addCleanup(self.shutdown)

    def shutdown(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=4)
            proc.stderr.close()

    def launch(self, **env):
        proc = subprocess.Popen([str(DAEMON), "--socket", self.path, "--schedules", self.sched_path, "--foreground"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                text=True, env={**os.environ, **env})
        self.processes.append(proc)
        return proc

    def start(self, **env):
        proc = self.launch(**env)
        until = time.monotonic() + 3
        while time.monotonic() < until:
            self.assertIsNone(proc.poll(), "daemon exited before readiness")
            if os.path.exists(self.path):
                result = self.call("status", code=None)
                if result.returncode == 0:
                    return proc
            time.sleep(.02)
        self.fail("daemon did not become ready")

    def call(self, *args, code=0, exe=CLI):
        result = subprocess.run([str(exe), "--socket", self.path, *args],
                                capture_output=True, text=True, timeout=6)
        if code is not None:
            self.assertEqual(result.returncode, code, (args, result.stdout, result.stderr))
        return result

    def server_call(self, *args, code=0):
        return self.call("--server-config", self.server_config_path,
                         "--schedule-state", self.sched_path, "server", *args, code=code)

    def write_server_config(self, text, path=None, mode=0o600):
        target = Path(path or self.server_config_path)
        target.write_text(text)
        os.chmod(target, mode)
        return target

    def raw(self, data):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3)
            client.connect(self.path)
            client.sendall(data)
            client.shutdown(socket.SHUT_WR)
            result = b""
            while b"\n" not in result:
                try:
                    part = client.recv(2048)
                except ConnectionResetError:
                    break
                if not part:
                    break
                result += part
            return result.decode()

    def test_integrated_p001_p007_cli_contract_smoke(self):
        self.start()
        alias = CLI.parent / "ic"

        self.assertIn("Usage:", self.call("help", exe=alias).stdout)
        self.assertIn("probe=acquire_release", self.call("probe", exe=alias).stdout)
        self.assertIn("active=no", self.call("status", exe=alias).stdout)

        self.call("start", "--for", "1m", exe=alias)
        self.assertIn("active=yes", self.call("status", exe=alias).stdout)
        until = (datetime.now(timezone.utc) + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        self.call("stop", exe=alias)
        self.call("start", "--until", until, exe=alias)
        self.assertIn("active=yes", self.call("status", exe=alias).stdout)
        self.call("stop", exe=alias)

        added = self.call("schedule", "add", "--daily", "22:00", "--for", "30m", exe=alias)
        schedule_id = added.stdout.split("id=", 1)[1].strip()
        self.assertIn("type=daily", self.call("schedule", "list", exe=alias).stdout)
        self.call("schedule", "remove", schedule_id, exe=alias)

        wake = self.call("wake", "status", exe=alias)
        self.assertIn("scheduled_wake=unverified", wake.stdout)
        self.assertIn("wake_guarantee=no", wake.stdout)

        server_options = ["--server-config", self.server_config_path,
                          "--schedule-state", self.sched_path, "server"]
        server_status = self.call(*server_options, "status", exe=alias)
        server_doctor = self.call(*server_options, "doctor", exe=alias)
        server_plan = self.call(*server_options, "plan", exe=alias)
        self.assertIn("configured_policy=DISABLED", server_status.stdout)
        self.assertIn("readiness=BLOCKED", server_doctor.stdout)
        self.assertIn("unattended_authorized=no", server_plan.stdout)
        self.call(*server_options, "trial", "start", "--for", "1s", exe=alias)
        self.call(*server_options, "trial", "stop", exe=alias)
        self.assertIn("active=no", self.call("status", exe=alias).stdout)

    def test_canonical_names_and_alias(self):
        self.start()
        self.assertTrue(DAEMON.is_file())
        self.assertEqual(os.readlink(CLI.parent / "ic"), "ios-caffeinate")
        local_cli = Path(self.temp.name) / "ios-caffeinate"
        shutil.copy2(CLI, local_cli)
        alias = local_cli.with_name("ic")
        alias.symlink_to("ios-caffeinate")
        self.assertTrue(alias.is_symlink())
        self.assertIn("ios-caffeinate", self.call("--help", exe=alias).stdout)
        self.assertIn("MOCK_NO_POWER_EFFECT", self.call("probe", exe=alias).stdout)
        self.assertIn("active=no", self.call("status", exe=alias).stdout)
        self.call("start", "--for", "5m", exe=alias)
        self.call("stop", exe=alias)

    def test_wake_status_is_read_only_and_unverified(self):
        state = ("{\n"
                 "  \"version\": 1,\n"
                 "  \"next_id_counter\": 2,\n"
                 "  \"schedules\": [\n"
                 "    {\"id\": \"future\", \"type\": 1, \"target_time\": 4102444800, "
                 "\"hour\": 0, \"minute\": 0, \"days_mask\": 0, \"duration\": 60, "
                 "\"tz\": \"UTC\", \"enabled\": true, \"last_fired_time\": 0}\n"
                 "  ]\n"
                 "}\n")
        Path(self.sched_path).write_text(state)
        os.chmod(self.sched_path, 0o600)

        # The report is local: it succeeds before a daemon or socket exists.
        report = self.call("wake", "status")
        self.assertFalse(os.path.exists(self.path))
        fields = dict(line.split("=", 1) for line in report.stdout.splitlines())
        self.assertEqual(list(fields), [
            "platform", "backend", "platform_identity", "timed_awake",
            "timed_awake_backend", "scheduled_awake", "scheduled_awake_backend",
            "scheduled_wake", "scheduled_wake_validated", "hardware_validation",
            "runtime_wake_probe", "read_only_evidence", "wake_guarantee", "limitations",
        ])
        self.assertEqual(fields["platform"], "linux")
        self.assertEqual(fields["backend"], "MOCK_NO_POWER_EFFECT")
        self.assertEqual(fields["platform_identity"], "compile_time_target")
        self.assertEqual(fields["timed_awake"], "implemented")
        self.assertEqual(fields["timed_awake_backend"], "unverified")
        self.assertEqual(fields["scheduled_awake"], "implemented")
        self.assertEqual(fields["scheduled_awake_backend"], "unverified")
        self.assertEqual(fields["scheduled_wake"], "unverified")
        self.assertEqual(fields["scheduled_wake_validated"], "no")
        self.assertEqual(fields["hardware_validation"], "pending")
        self.assertEqual(fields["runtime_wake_probe"], "unavailable")
        self.assertEqual(fields["read_only_evidence"], "none")
        self.assertEqual(fields["wake_guarantee"], "no")
        self.assertIn("assertion_is_not_wake_alarm", fields["limitations"])
        self.assertEqual(Path(self.sched_path).read_text(), state)

        # Querying with a live, idle daemon still causes no assertion and does
        # not rewrite its persisted P004 schedule state.
        self.start(IOSCAFFEINATE_MOCK_FAIL_ACQUIRE="1")
        self.assertIn("active=no", self.call("status").stdout)
        self.call("wake", "status")
        self.assertIn("active=no", self.call("status").stdout)
        self.assertEqual(Path(self.sched_path).read_text(), state)

    def test_wake_status_argument_errors(self):
        self.call("wake", code=2)
        self.call("wake", "set", "2026-10-18T12:00:00Z", code=2)
        self.call("wake", "status", "extra", code=2)

    def test_server_diagnostics_are_read_only_and_default_disabled(self):
        self.start(IOSCAFFEINATE_MOCK_FAIL_ACQUIRE="1")
        future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        self.call("schedule", "add", "--at", future_iso, "--for", "1m")
        schedule_before = Path(self.sched_path).read_bytes()

        status = self.server_call("status")
        self.assertIn("configured_policy=DISABLED", status.stdout)
        self.assertIn("server_mode_enabled=no", status.stdout)
        self.assertIn("daemon_availability=AVAILABLE", status.stdout)
        self.assertIn("daemon_protocol_compatibility=COMPATIBLE", status.stdout)
        self.assertIn("assertion_ownership=NONE", status.stdout)
        self.assertIn("backend_verification=UNVERIFIED", status.stdout)
        self.assertIn("build_capability=MOCK_ONLY", status.stdout)
        self.assertIn("scheduled_wake_support=UNVERIFIED", status.stdout)
        self.assertIn("os_power_state=UNVERIFIED", status.stdout)
        self.assertIn("prior_process_cleanup=UNVERIFIED", status.stdout)
        self.assertIn("unattended_mode_authorized=no", status.stdout)
        self.assertIn("daemon_recent_errors=0", status.stdout)
        self.assertIn("health.last_assertion_acquisition=UNAVAILABLE", status.stdout)
        self.assertIn("health.battery_level=UNAVAILABLE", status.stdout)
        self.assertIn("battery_level=UNAVAILABLE", status.stdout)
        self.assertIn("health.thermal_state=UNAVAILABLE", status.stdout)
        self.assertIn("thermal_state=UNAVAILABLE", status.stdout)
        self.assertIn("health.lan_connectivity=UNAVAILABLE", status.stdout)
        self.assertIn("lan_reachability=UNAVAILABLE", status.stdout)
        self.assertIn("health.tailscale_connectivity=UNAVAILABLE", status.stdout)
        self.assertIn("tailscale_reachability=UNAVAILABLE", status.stdout)
        self.assertIn("active=no", self.call("status").stdout)

        doctor = self.server_call("doctor")
        self.assertIn("check.cli_daemon_protocol=COMPATIBLE", doctor.stdout)
        self.assertIn("check.daemon_state=IDLE", doctor.stdout)
        self.assertIn("check.automatic_startup=UNKNOWN", doctor.stdout)
        self.assertIn("check.launchd_template=DISABLED", doctor.stdout)
        self.assertIn("check.battery_telemetry=UNAVAILABLE", doctor.stdout)
        self.assertIn("check.thermal_telemetry=UNAVAILABLE", doctor.stdout)
        self.assertIn("readiness=BLOCKED", doctor.stdout)

        plan = self.server_call("plan")
        self.assertIn("unattended_authorized=no", plan.stdout)
        self.assertIn("automatic_apply=no", plan.stdout)
        self.assertEqual(sum(line.startswith("gate.") for line in plan.stdout.splitlines()), 10)
        self.assertIn("gate.screen_locked_lan_verified=PENDING", plan.stdout)
        self.assertIn("gate.screen_locked_tailscale_verified=PENDING", plan.stdout)
        self.assertEqual(Path(self.sched_path).read_bytes(), schedule_before)
        self.assertFalse(Path(self.server_config_path).exists())

    def test_server_daemon_unavailable_is_not_backend_failure(self):
        status = self.server_call("status")
        self.assertIn("daemon_availability=UNAVAILABLE", status.stdout)
        self.assertIn("daemon_protocol_compatibility=UNAVAILABLE", status.stdout)
        self.assertIn("assertion_ownership=UNKNOWN", status.stdout)
        self.assertIn("backend_identity=MOCK_NO_POWER_EFFECT", status.stdout)
        self.assertIn("backend_verification=UNVERIFIED", status.stdout)
        doctor = self.server_call("doctor")
        self.assertIn("check.daemon_availability=UNAVAILABLE", doctor.stdout)

    def test_server_diagnostics_distinguish_old_daemon_protocol(self):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(self.path)
        os.chmod(self.path, 0o600)
        listener.listen(1)

        def old_protocol_server():
            client, _ = listener.accept()
            with client:
                client.recv(128)
                client.sendall(b"ERR unknown command\n")
            listener.close()

        thread = threading.Thread(target=old_protocol_server)
        thread.start()
        status = self.server_call("status")
        thread.join(timeout=2)
        self.assertIn("daemon_availability=AVAILABLE", status.stdout)
        self.assertIn("daemon_protocol_compatibility=INCOMPATIBLE", status.stdout)
        self.assertIn("assertion_ownership=UNKNOWN", status.stdout)

    def test_server_configuration_schema_fails_closed(self):
        valid = self.write_server_config('{"version":1,"policy":"observe_only"}\n')
        status = self.server_call("status")
        self.assertIn("configured_policy=OBSERVE_ONLY", status.stdout)
        self.assertIn("server_mode_enabled=yes", status.stdout)
        self.assertIn("configuration_status=VALID", status.stdout)
        self.assertIn("unattended_mode_authorized=no", status.stdout)

        valid.write_text('{"version":1,"policy":"observe_only","enabled":true}\n')
        os.chmod(valid, 0o600)
        invalid = self.server_call("status")
        self.assertIn("configured_policy=DISABLED", invalid.stdout)
        self.assertIn("server_mode_enabled=no", invalid.stdout)
        self.assertIn("operating_state=BLOCKED", invalid.stdout)
        self.assertIn("configuration_status=INVALID", invalid.stdout)

        self.write_server_config('{"version":1,"policy":"disabled",}\n')
        trailing_comma = self.server_call("status")
        self.assertIn("configuration_status=INVALID", trailing_comma.stdout)

    def test_server_configuration_rejects_symlinks_and_unsafe_modes(self):
        config = self.write_server_config('{"version":1,"policy":"observe_only"}\n')
        os.chmod(config, 0o644)
        unsafe_mode = self.server_call("status")
        self.assertIn("configuration_status=UNSAFE", unsafe_mode.stdout)
        self.assertIn("server_mode_enabled=no", unsafe_mode.stdout)

        os.chmod(config, 0o600)
        linked_config = Path(self.temp.name) / "config-link.json"
        linked_config.symlink_to(config)
        symlink = self.call("--server-config", str(linked_config), "--schedule-state", self.sched_path,
                            "server", "status")
        self.assertIn("configuration_status=UNSAFE", symlink.stdout)
        self.assertIn("server_mode_enabled=no", symlink.stdout)

        linked_parent = Path(self.temp.name) / "linked-parent"
        linked_parent.symlink_to(self.temp.name)
        parent_config = linked_parent / "parent-config.json"
        parent_symlink = self.call("--server-config", str(parent_config), "--schedule-state", self.sched_path,
                                   "server", "status")
        self.assertIn("configuration_status=UNSAFE", parent_symlink.stdout)

        hardlink = Path(self.temp.name) / "hardlink.json"
        os.link(config, hardlink)
        hardlink_report = self.call("--server-config", str(hardlink), "--schedule-state", self.sched_path,
                                    "server", "status")
        self.assertIn("configuration_status=UNSAFE", hardlink_report.stdout)

    def test_bounded_server_trial_stop_timeout_and_single_owner(self):
        self.start()
        self.server_call("trial", "start", "--for", "301s", code=2)
        started = self.server_call("trial", "start", "--for", "5m")
        self.assertIn("trial=active", started.stdout)
        status = self.server_call("status")
        self.assertIn("assertion_ownership=OWNED", status.stdout)
        self.assertIn("assertion_lifecycle=ACTIVE", status.stdout)
        self.assertIn("trial=yes", status.stdout)
        self.assertIn("trial_state=ACTIVE", status.stdout)
        self.call("start", "--for", "1s", code=1)

        stopped = self.server_call("trial", "stop")
        self.assertIn("trial=stopped", stopped.stdout)
        status = self.server_call("status")
        self.assertIn("assertion_ownership=NONE", status.stdout)
        self.assertIn("trial=no", status.stdout)
        self.assertIn("trial_state=STOPPED", status.stdout)
        self.assertIn("trial_stop_seen=yes", status.stdout)
        self.server_call("trial", "stop")
        self.assertIn("assertion_ownership=NONE", self.server_call("status").stdout)

        self.server_call("trial", "start", "--for", "1s")
        until = time.monotonic() + 4
        while time.monotonic() < until:
            expired = self.server_call("status")
            if ("assertion_ownership=NONE" in expired.stdout and "trial=no" in expired.stdout and
                    "trial_state=EXPIRED" in expired.stdout):
                break
            time.sleep(0.05)
        else:
            self.fail("bounded server trial did not expire")

    def test_server_trial_backend_error_is_visible(self):
        self.start(IOSCAFFEINATE_MOCK_FAIL_ACQUIRE="1")
        failed = self.server_call("trial", "start", "--for", "5s", code=1)
        self.assertIn("create_rc=0xe00002c7", failed.stderr)
        status = self.server_call("status")
        self.assertIn("assertion_ownership=NONE", status.stdout)
        self.assertIn("daemon_recent_errors=1", status.stdout)

    def test_mock_invalid_state_transition_blocks_new_assertions(self):
        self.start()
        self.assertIn("fault_injected=yes", self.raw(b"TEST INVALID STATE\n"))
        status = self.server_call("status")
        self.assertIn("assertion_ownership=NONE", status.stdout)
        self.assertIn("assertion_lifecycle=BLOCKED", status.stdout)
        self.assertIn("state_invariant=ERROR", status.stdout)
        self.assertIn("daemon_recent_errors=1", status.stdout)
        self.server_call("trial", "start", "--for", "1s", code=1)

    def test_server_trial_release_failure_remains_unresolved_and_bounded(self):
        self.start(IOSCAFFEINATE_MOCK_FAIL_RELEASE="1")
        self.server_call("trial", "start", "--for", "30s")
        failed_stop = self.server_call("trial", "stop", code=1)
        self.assertIn("release_rc=0xe00002bc", failed_stop.stderr)
        status = self.server_call("status")
        self.assertIn("assertion_ownership=OWNED", status.stdout)
        self.assertIn("assertion_lifecycle=RELEASE_FAILED", status.stdout)
        self.assertIn("trial_state=RELEASE_FAILED", status.stdout)
        self.assertIn("release_pending=yes", status.stdout)
        self.assertIn("last_release_error=mock_release_rc_0xe00002bc", status.stdout)

        until = time.monotonic() + 4
        while time.monotonic() < until:
            status = self.server_call("status")
            if "release_attempts=3" in status.stdout:
                break
            time.sleep(0.1)
        else:
            self.fail("release retry budget was not exhausted")
        time.sleep(1.1)
        still_failed = self.server_call("status")
        self.assertIn("assertion_ownership=OWNED", still_failed.stdout)
        self.assertIn("release_attempts=3", still_failed.stdout)

    def test_server_trial_sigterm_cleanup(self):
        self.write_server_config('{"version":1,"policy":"observe_only"}\n')
        proc = self.start()
        self.server_call("trial", "start", "--for", "30s")
        proc.terminate()
        self.assertEqual(proc.wait(timeout=4), 0)
        self.assertIn("Released assertion", proc.stderr.read())

    def test_server_restart_does_not_resume_trial(self):
        self.write_server_config('{"version":1,"policy":"observe_only"}\n')
        proc = self.start()
        self.server_call("trial", "start", "--for", "30s")
        proc.kill()
        self.assertEqual(proc.wait(timeout=4), -signal.SIGKILL)

        restarted = self.start()
        self.assertIsNotNone(restarted)
        status = self.server_call("status")
        self.assertIn("configured_policy=OBSERVE_ONLY", status.stdout)
        self.assertIn("assertion_ownership=NONE", status.stdout)
        self.assertIn("assertion_lifecycle=IDLE", status.stdout)
        self.assertIn("trial_state=INACTIVE", status.stdout)
        self.assertIn("unattended_mode_authorized=no", status.stdout)

    def test_connectivity_evidence_schema_keeps_lan_and_tailscale_independent(self):
        schema_path = ROOT / "docs/schemas/connectivity-evidence-v1.schema.json"
        schema = json.loads(schema_path.read_text())
        self.assertEqual(schema["required"], ["version", "lan", "tailscale"])
        definitions = schema["$defs"]
        lan_fields = definitions["lan"]["properties"]
        tailscale_fields = definitions["tailscale"]["properties"]
        self.assertIn("local_address", lan_fields)
        self.assertIn("tcp_22_reachable", lan_fields)
        self.assertNotIn("peer_connected", lan_fields)
        self.assertIn("tailnet_address", tailscale_fields)
        self.assertIn("peer_connected", tailscale_fields)
        self.assertIn("path", tailscale_fields)
        self.assertNotIn("tcp_22_reachable", tailscale_fields)
        plist = (ROOT / "packaging/com.ioscaffeinate.daemon.plist").read_text()
        self.assertIn("<key>Disabled</key><true/>", plist)
        self.assertIn("<key>RunAtLoad</key><false/>", plist)

    def test_duration_validation_and_exit_codes(self):
        self.start()
        for value in ("", "0", "0s", "0h", "86401", "1441m", "25h", "-1m", "+1s",
                      "1q", "1m2s", "1.5h", " 1s", "1s ", "999999999999999999999999h",
                      "18446744073709551615h", "18446744073709551616"):
            with self.subTest(value=value):
                self.call("start", "--for", value, code=2)
        for args in ((), ("nope",), ("start",), ("help", "extra"), ("status", "extra")):
            self.call(*args, code=2)
        for value, seconds in (("1", 1), ("2s", 2), ("1m", 60), ("24h", 86400), ("1440m", 86400)):
            self.assertIn(f"duration_seconds={seconds}", self.call("start", "--for", value).stdout)
            self.call("stop")

    def test_until_and_schedule_validation(self):
        self.start()
        now_utc = datetime.now(timezone.utc)
        past_iso = (now_utc - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        future_iso_25h = (now_utc + timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        future_iso_ok = (now_utc + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

        self.call("start", "--until", past_iso, code=2)
        self.call("start", "--until", future_iso_25h, code=2)
        self.call("start", "--until", "not-a-date", code=2)
        self.call("start", "--until", "2026-13-01T12:00:00Z", code=2)
        self.call("start", "--until", "2026-02-31T12:00:00Z", code=2)
        self.call("start", "--until", "2025-02-29T12:00:00Z", code=2)
        self.call("start", "--until", "2026-01-01T12:00:60Z", code=2)
        self.call("start", "--until", "2026-10-18T12:00:00", code=2)

        res = self.call("start", "--until", future_iso_ok)
        self.assertIn("active=yes", res.stdout)
        self.call("stop")

        self.call("schedule", "add", "--weekly", "invalidday", "--at", "10:00", "--for", "5m", code=2)
        self.call("schedule", "add", "--at", "2026-02-31T12:00:00Z", "--for", "5m", code=2)
        self.call("schedule", "add", "--daily", "25:00", "--for", "5m", code=2)
        self.call("schedule", "add", "--daily", "10:60", "--for", "5m", code=2)
        self.call("schedule", "add", "--daily", "10:00", code=2)

    def test_schedule_crud_and_persistence(self):
        self.start()

        res1 = self.call("schedule", "add", "--daily", "22:00", "--for", "1h", "--tz", "Asia/Ho_Chi_Minh")
        self.assertIn("schedule_added=yes", res1.stdout)
        sched1_id = res1.stdout.split("id=")[1].strip()

        res2 = self.call("schedule", "add", "--weekly", "mon,wed,fri", "--at", "20:30", "--for", "30m", "--tz", "Asia/Ho_Chi_Minh")
        self.assertIn("schedule_added=yes", res2.stdout)

        future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        res3 = self.call("schedule", "add", "--at", future_iso, "--for", "15m")
        self.assertIn("schedule_added=yes", res3.stdout)

        list_res = self.call("schedule", "list")
        self.assertIn("schedules=3", list_res.stdout)
        self.assertIn(sched1_id, list_res.stdout)
        self.assertIn("type=daily", list_res.stdout)
        self.assertIn("type=weekly", list_res.stdout)
        self.assertIn("type=onetime", list_res.stdout)

        self.assertTrue(os.path.exists(self.sched_path))
        with open(self.sched_path, "r") as f:
            data = json.load(f)
            self.assertEqual(data["version"], 1)
            self.assertEqual(len(data["schedules"]), 3)

        rem_res = self.call("schedule", "remove", sched1_id)
        self.assertIn("schedule_removed=yes", rem_res.stdout)

        self.call("schedule", "remove", "non-existent-id", code=1)

        list_res2 = self.call("schedule", "list")
        self.assertIn("schedules=2", list_res2.stdout)

    def test_schedule_rejects_unsafe_timezone_before_writing_json(self):
        self.start()
        result = self.call("schedule", "add", "--daily", "22:00", "--for", "30m",
                           "--tz", 'UTC"invalid', code=1)
        self.assertIn("invalid or unsafe values", result.stderr)
        self.assertFalse(Path(self.sched_path).exists())

    def test_corrupt_or_replaced_schedule_state_fails_closed(self):
        valid = json.dumps({
            "version": 1,
            "next_id_counter": 2,
            "schedules": [{
                "id": "sched-preserve",
                "type": 2,
                "target_time": 0,
                "hour": 22,
                "minute": 0,
                "days_mask": 0,
                "duration": 1800,
                "tz": "UTC",
                "enabled": True,
                "last_fired_time": 0,
            }],
        })
        overflow_data = json.loads(valid)
        overflow_data["schedules"][0].update({
            "type": 1,
            "target_time": 9223372036854775807,
            "hour": 0,
            "minute": 0,
            "days_mask": 0,
        })
        malformed = '{"version":1,"next_id_counter":2}'
        incomplete_record = '{"version":1,"next_id_counter":2,"schedules":[{"id":"sched-x"}]}'
        for contents in (malformed, incomplete_record, json.dumps(overflow_data)):
            with self.subTest(contents=contents):
                Path(self.sched_path).write_text(contents)
                os.chmod(self.sched_path, 0o600)
                proc = self.launch()
                self.assertEqual(proc.wait(timeout=3), 1)
                self.assertIn("Failed to load schedules", proc.stderr.read())
                self.assertEqual(Path(self.sched_path).read_text(), contents)

        target = Path(self.temp.name) / "schedule-target.json"
        target.write_text(valid)
        os.chmod(target, 0o600)
        Path(self.sched_path).unlink()
        Path(self.sched_path).symlink_to(target)
        proc = self.launch()
        self.assertEqual(proc.wait(timeout=3), 1)
        self.assertTrue(Path(self.sched_path).is_symlink())
        self.assertEqual(target.read_text(), valid)
        Path(self.sched_path).unlink()

        target.write_text(valid)
        os.chmod(target, 0o600)
        os.link(target, self.sched_path)
        proc = self.launch()
        self.assertEqual(proc.wait(timeout=3), 1)
        self.assertEqual(Path(self.sched_path).read_text(), valid)
        self.assertEqual(os.stat(target).st_nlink, 2)

        linked_parent = Path(self.temp.name) / "linked-parent"
        linked_parent.symlink_to(self.temp.name)
        linked_state_path = linked_parent / "linked-schedules.json"
        proc = subprocess.run(
            [str(DAEMON), "--socket", str(Path(self.temp.name) / "linked.sock"),
             "--schedules", str(linked_state_path)],
            capture_output=True, text=True, timeout=3,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Failed to load schedules", proc.stderr)

    def test_schedule_write_failure_blocks_assertion_and_is_visible(self):
        now_wall = int(time.time())
        start_dt = datetime.fromtimestamp(now_wall - 300, timezone.utc)
        sched_data = {
            "version": 1,
            "next_id_counter": 2,
            "schedules": [{
                "id": "sched-write-failure",
                "type": 2,
                "target_time": 0,
                "hour": start_dt.hour,
                "minute": start_dt.minute,
                "days_mask": 0,
                "duration": 1800,
                "tz": "UTC",
                "enabled": True,
                "last_fired_time": 0,
            }],
        }
        Path(self.sched_path).write_text(json.dumps(sched_data))
        os.chmod(self.sched_path, 0o600)

        proc = self.start(IOSCAFFEINATE_MOCK_FAIL_SCHEDULE_SAVE="1")
        status = self.call("status").stdout
        self.assertIn("active=no", status)
        self.assertIn("state=IDLE", status)
        self.call("stop")
        self.assertEqual(json.loads(Path(self.sched_path).read_text())["schedules"][0]["last_fired_time"], 0)
        proc.terminate()
        self.assertEqual(proc.wait(timeout=3), 0)

        self.start(IOSCAFFEINATE_MOCK_FAIL_SCHEDULE_SAVE="1")
        self.assertIn("active=no", self.call("status").stdout)

    def test_schedule_state_path_must_be_absolute_and_bounded(self):
        for path in ("", "relative/schedules.json", "/" + "x" * 300):
            with self.subTest(path=path[:24]):
                result = subprocess.run(
                    [str(DAEMON), "--socket", str(Path(self.temp.name) / "invalid.sock"),
                     "--schedules", path],
                    capture_output=True, text=True, timeout=3,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("Schedule state path", result.stderr)

    def test_stop_within_active_schedule_window(self):
        now_dt = datetime.now(timezone.utc)
        now_wall = int(time.time())
        start_wall = now_wall - 300
        start_dt = datetime.fromtimestamp(start_wall, timezone.utc)

        sched_data = {
            "version": 1,
            "next_id_counter": 2,
            "schedules": [
                {
                    "id": "sched-stop-test",
                    "type": 2, # DAILY
                    "target_time": 0,
                    "hour": start_dt.hour,
                    "minute": start_dt.minute,
                    "days_mask": 0,
                    "duration": 1800, # 30 min
                    "tz": "UTC",
                    "enabled": True,
                    "last_fired_time": 0
                }
            ]
        }
        with open(self.sched_path, "w") as f:
            json.dump(sched_data, f)
        os.chmod(self.sched_path, 0o600)

        proc = self.start()
        status = self.call("status").stdout
        self.assertIn("active=yes", status)

        # Explicit STOP
        self.call("stop")
        status_after_stop = self.call("status").stdout
        self.assertIn("active=no", status_after_stop)

        # Wait brief moment and check daemon hasn't re-triggered same window
        time.sleep(0.1)
        status_recheck = self.call("status").stdout
        self.assertIn("active=no", status_recheck)

    def test_daemon_restart_recovery(self):
        now_wall = int(time.time())
        start_wall = now_wall - 300
        start_dt = datetime.fromtimestamp(start_wall, timezone.utc)

        sched_data = {
            "version": 1,
            "next_id_counter": 2,
            "schedules": [
                {
                    "id": "sched-test-rec",
                    "type": 2, # DAILY
                    "target_time": 0,
                    "hour": start_dt.hour,
                    "minute": start_dt.minute,
                    "days_mask": 0,
                    "duration": 1800, # 30 min
                    "tz": "UTC",
                    "enabled": True,
                    "last_fired_time": 0
                }
            ]
        }
        with open(self.sched_path, "w") as f:
            json.dump(sched_data, f)
        os.chmod(self.sched_path, 0o600)

        proc = self.start()
        status = self.call("status").stdout
        self.assertIn("active=yes", status)

        self.call("stop")

    def test_large_schedule_list_fragmented(self):
        self.start()
        for i in range(30):
            self.call("schedule", "add", "--daily", "12:00", "--for", "5m")

        list_res = self.call("schedule", "list")
        self.assertIn("schedules=30", list_res.stdout)

    def test_probe_and_hold_lifecycle(self):
        self.start()
        probe = self.call("probe").stdout
        for detail in ("probe=acquire_release", "assertion_id=", "release_rc=0x00000000",
                       "type=PreventUserIdleSystemSleep", "backend=MOCK_NO_POWER_EFFECT"):
            self.assertIn(detail, probe)
        self.call("start", "--for", "5m")
        status = self.call("status").stdout
        self.assertIn("active=yes", status)
        self.assertIn("state=ACTIVE", status)
        self.assertRegex(status, r"remaining_seconds=(299|300)\b")
        self.call("start", "--for", "2s", code=1)
        self.call("probe", code=1)
        self.assertIn("release_rc=0x00000000", self.call("stop").stdout)
        self.assertIn("already_stopped=yes", self.call("stop").stdout)

    def test_expiry_with_idle_client(self):
        proc = self.start()
        self.call("start", "--for", "1s")
        with socket.socket(socket.AF_UNIX) as idle:
            idle.connect(self.path)
            time.sleep(1.4)
            self.assertIn("active=no", self.call("status").stdout)
        proc.terminate()
        self.assertEqual(proc.wait(timeout=3), 0)
        self.assertIn("Released assertion", proc.stderr.read())

    def test_fragmented_request(self):
        self.start()
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3)
            client.connect(self.path)
            for part in (b"STA", b"RT ", b"2", b"\n"):
                client.sendall(part)
                time.sleep(.03)
            self.assertIn(b"OK active=yes", client.recv(2048))
        self.call("stop")

    def test_malformed_frames(self):
        self.start()
        for data in (b"NOPE\n", b"\n", b"STATUS", b"STATUS\x00junk\n", b"STATUS\r\n",
                     b"STATUS\nSTOP\n", b"x" * 512, b"START -1\n", b"START 0\n",
                     b"START 86401\n", b"START 18446744073709551616\n", b"START 1x\n",
                     b"START  1\n", b"START 1 \n"):
            with self.subTest(data=data):
                self.assertTrue(self.raw(data).startswith("ERR "))
        self.assertIn("active=no", self.call("status").stdout)

    def test_disconnect_does_not_kill_daemon(self):
        self.start()
        for data in (b"", b"STA", b"STATUS\n", b"START 1\n"):
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(self.path)
                if data:
                    client.sendall(data)
            time.sleep(.05)
        self.call("status")
        time.sleep(1.2)
        self.assertIn("active=no", self.call("status").stdout)

    def test_signal_cleanup(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            proc = self.start()
            self.call("start", "--for", "5m")
            with socket.socket(socket.AF_UNIX) as idle:
                idle.connect(self.path)
                time.sleep(.05)
                proc.send_signal(sig)
                self.assertEqual(proc.wait(timeout=2), 0)
            self.assertFalse(os.path.exists(self.path))
            self.assertIn("Released assertion", proc.stderr.read())
            self.call("status", code=1)

    def test_socket_permissions_and_single_instance(self):
        self.start()
        before = os.stat(self.path)
        self.assertEqual(stat.S_IMODE(before.st_mode), 0o600)
        self.assertEqual(before.st_uid, os.geteuid())
        contender = self.launch()
        self.assertEqual(contender.wait(timeout=3), 1)
        self.assertEqual(os.stat(self.path).st_ino, before.st_ino)
        self.call("status")

    def test_simultaneous_startup(self):
        for _ in range(4):
            first, second = self.launch(), self.launch()
            until = time.monotonic() + 3
            while first.poll() is None and second.poll() is None and time.monotonic() < until:
                time.sleep(.02)
            self.assertEqual(sum(p.poll() is None for p in (first, second)), 1)
            loser = first if first.poll() is not None else second
            winner = second if loser is first else first
            self.assertEqual(loser.returncode, 1)
            self.call("status")
            winner.terminate()
            self.assertEqual(winner.wait(timeout=3), 0)

    def test_stale_socket_and_crash_recovery(self):
        with socket.socket(socket.AF_UNIX) as stale:
            stale.bind(self.path)
        proc = self.start()
        proc.kill()
        proc.wait(timeout=3)
        self.assertTrue(os.path.exists(self.path))
        replacement = self.start()
        replacement.terminate()
        self.assertEqual(replacement.wait(timeout=3), 0)
        self.assertFalse(os.path.exists(self.path))

    def test_refuse_regular_file_and_symlink(self):
        target = Path(self.temp.name) / "keep"
        target.write_text("preserve me")
        for symlink in (False, True):
            path = Path(self.path)
            if symlink:
                path.symlink_to(target)
            else:
                path.write_text("preserve me")
            proc = self.launch()
            self.assertEqual(proc.wait(timeout=3), 1)
            self.assertTrue(path.exists())
            self.assertEqual(target.read_text(), "preserve me")
            path.unlink()

    def test_missing_daemon_and_bad_paths(self):
        self.call("status", code=1)
        for path in ("relative.sock", "/" + "x" * 200):
            cli = subprocess.run([str(CLI), "--socket", path, "status"], capture_output=True, timeout=3)
            self.assertEqual(cli.returncode, 2)
            result = subprocess.run([str(DAEMON), "--socket", path], capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 2)

    def test_acquire_failure(self):
        self.start(IOSCAFFEINATE_MOCK_FAIL_ACQUIRE="1")
        self.assertIn("create_rc=0xe00002c7", self.call("probe", code=1).stderr)
        self.call("start", "--for", "1s", code=1)
        self.assertIn("active=no", self.call("status").stdout)
        self.assertIn("state=IDLE", self.call("status").stdout)

    def test_release_failure_is_not_success(self):
        for probe in (False, True):
            proc = self.start(IOSCAFFEINATE_MOCK_FAIL_RELEASE="1")
            if probe:
                self.assertIn("release_rc=0xe00002bc", self.call("probe", code=1).stderr)
            else:
                self.call("start", "--for", "1s")
            self.assertIn("release_rc=0xe00002bc", self.call("stop", code=1).stderr)
            status = self.call("status").stdout
            self.assertIn("active=yes", status)
            self.assertIn("state=RELEASE_FAILED", status)
            self.assertIn("release_pending=yes", status)
            self.assertRegex(status, r"assertion_id=[1-9][0-9]*")
            self.call("start", "--for", "1s", code=1)
            time.sleep(1.2)
            self.assertIn("release_pending=yes", self.call("status").stdout)
            proc.terminate()
            self.assertEqual(proc.wait(timeout=3), 1)
            self.assertIn("UNRESOLVED assertion release", proc.stderr.read())
            self.assertFalse(os.path.exists(self.path))

    def test_existing_live_socket_is_preserved(self):
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(self.path)
            server.listen(1)
            before = os.stat(self.path)
            proc = self.launch()
            self.assertEqual(proc.wait(timeout=3), 1)
            self.assertEqual(os.stat(self.path).st_ino, before.st_ino)

    def test_unsafe_lock_is_preserved(self):
        target = Path(self.temp.name) / "keep"
        target.write_text("preserve me")
        lock = Path(self.path + ".lock")
        lock.symlink_to(target)
        proc = self.launch()
        self.assertEqual(proc.wait(timeout=3), 1)
        self.assertTrue(lock.is_symlink())
        self.assertEqual(target.read_text(), "preserve me")

    def test_cleanup_preserves_replacement_socket(self):
        proc = self.start()
        os.unlink(self.path)
        with socket.socket(socket.AF_UNIX) as replacement:
            replacement.bind(self.path)
            before = os.stat(self.path)
            proc.terminate()
            self.assertEqual(proc.wait(timeout=3), 0)
            self.assertEqual(os.stat(self.path).st_ino, before.st_ino)

    def test_cli_reply_timeout(self):
        done = threading.Event()
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(self.path)
            server.listen(1)
            def serve():
                with server.accept()[0] as peer:
                    peer.recv(128)
                    peer.sendall(b"OK incomplete")
                    done.wait(timeout=5)
            worker = threading.Thread(target=serve)
            worker.start()
            started = time.monotonic()
            try:
                self.call("status", code=1)
                self.assertLess(time.monotonic() - started, 5)
            finally:
                done.set()
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())

    def test_cli_fragmented_and_incomplete_replies(self):
        for parts, code in (((b"OK act", b"ive=no\n"), 0), ((b"OK partial",), 1),
                            ((b"OK bad\x00\n",), 1), ((b"OK one\nERR two\n",), 1)):
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(self.path)
                server.listen(1)
                def serve():
                    with server.accept()[0] as peer:
                        peer.recv(128)
                        for part in parts:
                            try:
                                peer.sendall(part)
                            except OSError:
                                break
                            time.sleep(.02)
                worker = threading.Thread(target=serve)
                worker.start()
                try:
                    self.call("status", code=code)
                finally:
                    worker.join(timeout=3)
                    self.assertFalse(worker.is_alive())
            os.unlink(self.path)

    def test_peer_authentication_and_rejection(self):
        self.start()
        res = self.call("status")
        self.assertEqual(res.returncode, 0)
        self.assertIn("OK active=no", res.stdout)
        raw_resp = self.raw(b"STATUS\n")
        self.assertTrue(raw_resp.startswith("OK "))

        proc = subprocess.run([str(DAEMON), "--socket", "/var/run/ioscaffeinated.sock"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Default socket requires root", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
