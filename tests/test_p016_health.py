import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "build" / "test" / "ios-caffeinate"
sys.path.insert(0, str(ROOT / "scripts"))
import p009_evidence


class P016HealthCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([str(ROOT / "scripts" / "build-linux-test.sh")], cwd=ROOT, check=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ioscaffeinate-p016-health-")
        self.root = Path(self.tmp.name)
        self.socket = self.root / "missing.sock"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [str(BINARY), "--socket", str(self.socket), *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_p009_adapter(self, kind, fields, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "p016_p009_adapter.py"), kind,
             "--event-id", "P016-battery-01", "--sequence", "8", *args],
            cwd=ROOT,
            input=fields,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_sources_identify_mock_without_claiming_device_support(self):
        result = self.run_cli("health", "sources")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("platform=MOCK_NO_SENSOR_DATA", result.stdout)
        self.assertIn("battery.status=UNAVAILABLE", result.stdout)
        self.assertIn("thermal.status=UNAVAILABLE", result.stdout)
        self.assertIn("physical_device_observation=no", result.stdout)
        self.assertNotIn("device_reported=yes", result.stdout)

    def test_status_is_consolidated_and_read_only_when_daemon_is_absent(self):
        result = self.run_cli("health", "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in (
            "health.schema_version=1",
            "battery.percentage=UNAVAILABLE",
            "battery.charging=UNKNOWN",
            "thermal.state=UNKNOWN",
            "thermal.temperature_celsius=UNAVAILABLE",
            "device.uptime_seconds=UNAVAILABLE",
            "daemon.status=UNAVAILABLE",
            "daemon.read_only_query=yes",
            "health.polling=ON_DEMAND",
            "health.record_persisted=no",
            "health.hardware_acceptance=NOT_ESTABLISHED",
        ):
            self.assertIn(expected, result.stdout)

    def test_sensor_commands_report_unavailable_with_distinct_exit_status(self):
        battery = self.run_cli("health", "battery")
        thermal = self.run_cli("health", "thermal")
        self.assertEqual(battery.returncode, 3)
        self.assertEqual(thermal.returncode, 3)
        self.assertIn("battery.percentage=UNAVAILABLE", battery.stdout)
        self.assertIn("thermal.state=UNKNOWN", thermal.stdout)
        self.assertNotIn("thermal.state=NOMINAL", thermal.stdout)

    def test_doctor_and_bad_arguments(self):
        doctor = self.run_cli("health", "doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        for expected in (
            "doctor.read_only=yes",
            "doctor.background_polling=no",
            "doctor.launchd_activation=no",
            "doctor.assertion_acquisition=no",
            "doctor.unattended_server_mode=no",
            "doctor.battery_reason=no supported read-only value is available",
            "doctor.thermal_reason=no supported read-only value is available",
        ):
            self.assertIn(expected, doctor.stdout)
        invalid = self.run_cli("health", "start")
        self.assertEqual(invalid.returncode, 2)

    def test_p012_association_is_explicit_and_read_only(self):
        associated = self.run_cli(
            "health", "status", "--trial-id", "trial-01", "--condition-id", "A",
            "--outside-quiet-interval",
        )
        self.assertEqual(associated.returncode, 0, associated.stderr)
        self.assertIn("trial.association=EXPLICIT", associated.stdout)
        self.assertIn("trial.trial_id=trial-01", associated.stdout)
        self.assertIn("trial.condition_id=A", associated.stdout)
        self.assertIn("trial.sampling_window=OPERATOR_ASSERTED_OUTSIDE_QUIET_INTERVAL", associated.stdout)
        self.assertIn("trial.record_written=no", associated.stdout)
        self.assertIn("trial.independent_host_observation=UNAVAILABLE", associated.stdout)
        self.assertIn("battery.percentage_observation.observed_at_utc=", associated.stdout)

        missing_guard = self.run_cli("health", "status", "--trial-id", "trial-01",
                                     "--condition-id", "A")
        self.assertEqual(missing_guard.returncode, 2)
        invalid_id = self.run_cli("health", "status", "--trial-id", "bad id",
                                  "--condition-id", "A", "--outside-quiet-interval")
        self.assertEqual(invalid_id.returncode, 2)

    def test_strict_p009_adapter_preserves_observation_provenance(self):
        fields = "\n".join((
            "battery.percentage=0",
            "battery.charging=FULL",
            "battery.percentage_observation.status=AVAILABLE",
            "battery.percentage_observation.source=UIDevice.batteryLevel",
            "battery.percentage_observation.source_class=DEVICE_REPORTED",
            "battery.percentage_observation.source_detected=yes",
            "battery.percentage_observation.measurement_acquired=yes",
            "battery.percentage_observation.value_valid=yes",
            "battery.percentage_observation.observed_at_utc=1792541000",
            "battery.percentage_observation.freshness=CURRENT",
            "battery.percentage_observation.age_seconds=1",
            "battery.percentage_observation.clock_uncertainty_ms=1000",
            "battery.percentage_observation.timebase_id=mach-continuous:1792540000",
            "battery.percentage_observation.confidence=MEDIUM",
            "battery.percentage_observation.physical_source_verified=no",
            "battery.percentage_observation.safety_interpretation_reviewed=no",
            "battery.percentage_observation.p009_evidence_accepted=no",
        )) + "\n"
        result = self.run_p009_adapter(
            "battery", fields, "--trial-id", "trial-01", "--condition-id", "A",
            "--outside-quiet-interval",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        event = json.loads(result.stdout)
        self.assertEqual(event["event_type"], "BATTERY_OBSERVATION")
        self.assertEqual(event["source"], "DEVICE_REPORTED")
        self.assertEqual(event["timebase_id"], "mach-continuous:1792540000")
        self.assertEqual(event["details"]["percentage"], 0)
        self.assertEqual(event["details"]["charging"], "FULL")
        self.assertFalse(event["details"]["physical_source_verified"])
        self.assertFalse(event["details"]["p009_evidence_accepted"])
        self.assertEqual(event["details"]["trial_id"], "trial-01")
        self.assertEqual(event["details"]["sampling_window"],
                         "OPERATOR_ASSERTED_OUTSIDE_QUIET_INTERVAL")
        schemas = p009_evidence._schema_documents()
        device_schema = schemas["https://ios-caffeinate.invalid/schemas/device-acceptance-v1.schema.json"]
        errors = p009_evidence._schema_errors(
            event, {"$ref": "#/$defs/observation"}, device_schema, schemas,
        )
        self.assertEqual(errors, [])

        stale = fields.replace("freshness=CURRENT", "freshness=STALE")
        rejected = self.run_p009_adapter("battery", stale)
        self.assertEqual(rejected.returncode, 3)
        self.assertEqual(rejected.stdout, "")
        missing_timebase = fields.replace("mach-continuous:1792540000", "UNKNOWN")
        rejected = self.run_p009_adapter("battery", missing_timebase)
        self.assertEqual(rejected.returncode, 3)
        self.assertEqual(rejected.stdout, "")

    def test_p009_adapter_emits_no_event_for_currently_unavailable_sources(self):
        for kind in ("battery", "thermal"):
            observation = self.run_cli("health", kind)
            self.assertEqual(observation.returncode, 3)
            converted = self.run_p009_adapter(kind, observation.stdout)
            self.assertEqual(converted.returncode, 3)
            self.assertEqual(converted.stdout, "")

    def test_policy_adapter_keeps_p015_and_p014_gates_closed(self):
        config = self.root / "server-mode.json"
        config.write_text(
            '{"version":2,"policy":"bounded_session","session":{'
            '"max_duration_seconds":300,"require_operator_confirmation":true,'
            '"allow_automatic_start":false,"allow_restart_resume":false}}',
            encoding="utf-8",
        )
        config.chmod(0o600)
        before = (config.stat().st_ino, config.stat().st_mtime_ns, config.read_bytes())
        result = self.run_cli("--server-config", str(config), "server", "policy", "explain")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("decision=BLOCK_RECOVERY", result.stdout)
        self.assertIn("execution_authorized=no", result.stdout)
        self.assertIn("evidence.battery_safety.state=PENDING", result.stdout)
        self.assertIn("evidence.thermal_safety.state=PENDING", result.stdout)
        self.assertIn("telemetry.battery.source_class=MOCK", result.stdout)
        self.assertIn("telemetry.battery.source_detected=no", result.stdout)
        self.assertIn("telemetry.battery.measurement_acquired=no", result.stdout)
        self.assertIn("telemetry.battery.current=no", result.stdout)
        self.assertIn("telemetry.thermal.valid=no", result.stdout)
        self.assertIn("telemetry.thermal.p009_accepted=no", result.stdout)
        self.assertIn("recovery.restart_eligibility=no", result.stdout)
        self.assertEqual((config.stat().st_ino, config.stat().st_mtime_ns, config.read_bytes()), before)

    def test_health_output_contains_no_credentials(self):
        for command in (("health", "sources"), ("health", "status"),
                        ("health", "doctor"), ("health", "battery"),
                        ("health", "thermal")):
            result = self.run_cli(*command)
            self.assertIn(result.returncode, (0, 3), result.stderr)
            self.assertNotRegex(
                result.stdout,
                re.compile(r"(?i)(private[_-]?key|ssh[_-]?key|tailscale[_-]?token|password|secret)"),
            )

    def test_health_modules_have_no_service_or_network_side_effect_interface(self):
        module_sources = (
            ROOT / "src" / "health.c",
            ROOT / "src" / "health_ios.c",
            ROOT / "src" / "health_policy.c",
        )
        forbidden = (
            "launchctl", "system(", "fork(", "execv(", "posix_spawn(", "socket(",
            "AF_INET", "IOPMAssertion", "IOPowerSources", "IORegistryEntry",
            "timer_create(", "dispatch_source", "nanosleep(", "sleep(",
            "open(", "unlink(", "rename(", "https://", "http://",
        )
        for path in module_sources:
            source = path.read_text(encoding="utf-8")
            found = [token for token in forbidden if token in source]
            self.assertEqual(found, [], f"{path.name} contains {found}")
        cli_source = (ROOT / "src" / "cli.c").read_text(encoding="utf-8")
        health_start = cli_source.index("static int health_refresh_observation")
        health_end = cli_source.index("static int load_server_config", health_start)
        health_cli = cli_source[health_start:health_end]
        forbidden_cli = ("AF_INET", "getaddrinfo(", "execv(", "system(", "launchctl",
                         "IOPMAssertion", "IOPowerSources", "timer_create(", "sleep(")
        found = [token for token in forbidden_cli if token in health_cli]
        self.assertEqual(found, [], f"health CLI contains {found}")


if __name__ == "__main__":
    unittest.main()
