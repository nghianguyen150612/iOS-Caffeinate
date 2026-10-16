#!/usr/bin/env python3
"""Linux mock integration test; it does not validate iOS sleep inhibition."""
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAEMON = ROOT / "build/test/ioscaffeinated"
CLI = ROOT / "build/test/ioscaffeinate"


def call(path, *args, good=True):
    result = subprocess.run([str(CLI), "--socket", path, *args],
                            capture_output=True, text=True, timeout=5)
    if good:
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    else:
        assert result.returncode != 0, (result.returncode, result.stdout)
    return result.stdout + result.stderr


def main():
    with tempfile.TemporaryDirectory(prefix="ioscaf-") as temp:
        path = os.path.join(temp, "test.sock")
        proc = subprocess.Popen([str(DAEMON), "--socket", path, "--foreground"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(100):
                if os.path.exists(path):
                    break
                time.sleep(.02)
            assert os.path.exists(path), "daemon did not create socket"
            assert "active=no" in call(path, "status")
            assert "MOCK_NO_POWER_EFFECT" in call(path, "probe")
            assert "duration_seconds=2" in call(path, "start", "--for", "2s")
            assert "active=yes" in call(path, "status")
            assert "already active" in call(path, "start", "--for", "3s", good=False)
            time.sleep(2.6)
            assert "active=no" in call(path, "status")
            assert "duration_seconds=60" in call(path, "start", "--for", "1m")
            assert "active=yes" in call(path, "status")
            assert "active=no" in call(path, "stop")
            assert "already_stopped" in call(path, "stop")
            for invalid in ("0s", "25h", "-1m", "1q", "999999999999999h", "1m2s"):
                call(path, "start", "--for", invalid, good=False)
            assert "active=no" in call(path, "status")
            proc.send_signal(signal.SIGTERM)
            assert proc.wait(timeout=4) == 0
            assert not os.path.exists(path), "socket not cleaned up"
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
            if proc.stderr:
                output = proc.stderr.read()
                if "MOCK_NO_POWER_EFFECT" not in output:
                    raise AssertionError(f"not a mock backend: {output}")
    print("PASS: daemon lifecycle, probe, timers, stop, validation, socket cleanup (mock only)")


if __name__ == "__main__":
    main()
