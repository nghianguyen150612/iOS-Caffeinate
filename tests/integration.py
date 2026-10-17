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
        self.call("start", "--until", "2026-10-18T12:00:00", code=2)

        res = self.call("start", "--until", future_iso_ok)
        self.assertIn("active=yes", res.stdout)
        self.call("stop")

        self.call("schedule", "add", "--weekly", "invalidday", "--at", "10:00", "--for", "5m", code=2)
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
