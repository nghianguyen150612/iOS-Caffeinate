from __future__ import annotations

import hashlib
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import p018_evidence as evidence  # noqa: E402
import p018_validate_export as validator  # noqa: E402


def write_bundle(root: Path, *, records_override=None, file_bytes=None) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(mode=0o700, parents=True)
    contents = file_bytes or {
        "snapshots/doctor.json": b'{"hardware_evidence_accepted":"NOT_ESTABLISHED","source_class":"UNKNOWN"}\n',
        "evidence/p009/notes.txt": b"operator review required\n",
        "evidence/p009/table.csv": b"name,value\nobservation,unknown\n",
    }
    for relative, content in contents.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o600)
    records = [
        {
            "path": relative,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content_type": {".json": "application/json", ".txt": "text/plain", ".csv": "text/csv", ".pem": "application/x-pem-file"}[Path(relative).suffix],
            "source_id": "fixture-" + Path(relative).stem,
            "provenance": "UNKNOWN",
            "review_state": "UNREVIEWED",
        }
        for relative, content in sorted(contents.items())
    ]
    manifest = {
        "schema_version": 1,
        "export_type": "ioscaffeinate-diagnostic-bundle",
        "exported_at_utc": "2026-10-21T12:00:00Z",
        "package_identifier": "com.ioscaffeinate.cli",
        "source_metadata": {
            "package_version": "0.1.0-1",
            "source_commit_sha": "a" * 40,
            "export_tool": "p018_evidence.py",
        },
        "files": records if records_override is None else records_override,
        "validation_report": {
            "status": "REQUIRES_STANDALONE_VALIDATOR",
            "validator": "p018_validate_export.py",
            "scope": "schema_paths_types_sizes_hashes_encoding_privacy",
        },
        "hardware_evidence_accepted": "NOT_ESTABLISHED",
        "privacy_notice": "Review every included source before sharing.",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    (root / "manifest.json").chmod(0o600)


class P018ExportValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ioscaf-p018-export-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "bundle"
        self.root.mkdir(mode=0o700)

    def test_valid_bundle_keeps_hardware_acceptance_unestablished(self) -> None:
        write_bundle(self.root)
        report = validator.validate_bundle(self.root)
        self.assertEqual(report["validation"], "VALID")
        self.assertEqual(report["hardware_evidence_accepted"], "NOT_ESTABLISHED")
        self.assertEqual(report["files_checked"], 3)

    def test_tampered_file_is_rejected(self) -> None:
        write_bundle(self.root)
        path = self.root / "evidence/p009/notes.txt"
        path.write_bytes(path.read_bytes().replace(b"required", b"rejected"))
        with self.assertRaisesRegex(validator.ExportValidationError, "checksum mismatch"):
            validator.validate_bundle(self.root)

    def test_duplicate_manifest_paths_are_rejected(self) -> None:
        write_bundle(self.root)
        manifest_path = self.root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"].append(dict(manifest["files"][0]))
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(validator.ExportValidationError, "duplicate file entries"):
            validator.validate_bundle(self.root)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        write_bundle(self.root)
        (self.root / "manifest.json").write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(validator.ExportValidationError, "duplicate object key"):
            validator.validate_bundle(self.root)

    def test_boolean_and_unknown_schema_versions_are_rejected(self) -> None:
        for version in (True, 999):
            with self.subTest(version=version):
                write_bundle(self.root)
                manifest_path = self.root / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["schema_version"] = version
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(validator.ExportValidationError, "schema version"):
                    validator.validate_bundle(self.root)

    def test_path_traversal_and_unsupported_provenance_are_rejected(self) -> None:
        write_bundle(self.root)
        manifest_path = self.root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["path"] = "evidence/../outside.txt"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(validator.ExportValidationError, "traversing"):
            validator.validate_bundle(self.root)
        write_bundle(self.root)
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["provenance"] = "PHYSICALLY_ACCEPTED"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(validator.ExportValidationError, "provenance"):
            validator.validate_bundle(self.root)

    def test_symlinks_and_hardlinks_are_rejected(self) -> None:
        write_bundle(self.root)
        target = self.root / "snapshots/doctor.json"
        target.unlink()
        target.symlink_to(self.root / "manifest.json")
        with self.assertRaisesRegex(validator.ExportValidationError, "opened safely"):
            validator.validate_bundle(self.root)
        write_bundle(self.root)
        target = self.root / "snapshots/doctor.json"
        other = Path(self.temp.name) / "outside-copy.json"
        os.link(target, other)
        with self.assertRaisesRegex(validator.ExportValidationError, "singly linked"):
            validator.validate_bundle(self.root)

    def test_unauthorized_type_invalid_encoding_and_secret_are_rejected(self) -> None:
        for contents, message in (
            ({"evidence/p009/private.pem": b"unused"}, "file type"),
            ({"evidence/p009/notes.txt": b"\xff"}, "UTF-8"),
            ({"evidence/p009/notes.txt": b"token=ghp_" + b"a" * 24}, "token material"),
            ({"evidence/p009/notes.txt": b"host 2001:db8::1"}, "IPv6 address"),
        ):
            with self.subTest(message=message):
                write_bundle(self.root, file_bytes=contents)
                with self.assertRaisesRegex(validator.ExportValidationError, message):
                    validator.validate_bundle(self.root)

    def test_exported_bundle_requires_a_real_normalized_directory(self) -> None:
        write_bundle(self.root)
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(validator.ExportValidationError, "real directory"):
            validator.validate_bundle(alias)

    def test_nested_json_and_oversized_directory_inventory_are_bounded(self) -> None:
        nested: object = "leaf"
        for _ in range(40):
            nested = [nested]
        raw = json.dumps(nested).encode()
        with self.assertRaisesRegex(validator.ExportValidationError, "nesting"):
            validator.scan_sensitive(json.loads(raw))
        write_bundle(self.root)
        for index in range(validator.MAX_DIRECTORY_ENTRIES + 1):
            (self.root / f"snapshots/extra-{index}.txt").write_text("x")
        with self.assertRaisesRegex(validator.ExportValidationError, "too many directory entries"):
            validator.validate_bundle(self.root)


class P018EvidenceInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ioscaf-p018-inventory-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "evidence"
        self.root.mkdir(mode=0o700)

    def test_unknown_provenance_and_review_claim_are_not_acceptance(self) -> None:
        path = self.root / "p012/trial-record.json"
        path.parent.mkdir(mode=0o700)
        path.write_text(json.dumps({"source_class": "FUTURE_SOURCE", "review_status": "REVIEWED"}))
        os.chmod(path, 0o600)
        report = evidence.inventory_report(self.root)
        item = next(row for row in report["items"] if row["source_id"] == "p012-trial-record")
        self.assertEqual(item["state"], "PRESENT")
        self.assertEqual(item["provenance"], "UNKNOWN")
        self.assertEqual(item["review_state"], "REVIEWED_CLAIMED")
        self.assertEqual(item["acceptance"], "NOT_INFERRED")
        self.assertEqual(report["hardware_evidence_accepted"], "NOT_ESTABLISHED")

    def test_excessively_nested_inventory_json_is_reported_invalid(self) -> None:
        path = self.root / "p011/package-acceptance.json"
        path.parent.mkdir(mode=0o700)
        path.write_bytes(b"[" * 1100 + b"0" + b"]" * 1100)
        os.chmod(path, 0o600)
        report = evidence.inventory_report(self.root)
        item = next(row for row in report["items"] if row["source_id"] == "p011-package-acceptance")
        self.assertEqual(item["state"], "INVALID")
        self.assertNotEqual(report["inventory_status"], "AVAILABLE")

    def test_malformed_symlink_and_hardlinked_records_are_invalid(self) -> None:
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text("{}")
        link = self.root / "p013/launchd-observation.json"
        link.parent.mkdir(mode=0o700)
        link.symlink_to(outside)
        hard = self.root / "p014/recovery-observation.json"
        hard.parent.mkdir(mode=0o700)
        hard.write_text("{}")
        os.chmod(hard, 0o600)
        os.link(hard, Path(self.temp.name) / "hardlink.json")
        malformed = self.root / "p015/policy-observation.json"
        malformed.parent.mkdir(mode=0o700)
        malformed.write_bytes(b"{invalid")
        os.chmod(malformed, 0o600)
        report = evidence.inventory_report(self.root)
        by_id = {row["source_id"]: row for row in report["items"]}
        for source_id in ("p013-launchd-observation", "p014-recovery-observation", "p015-policy-observation"):
            self.assertEqual(by_id[source_id]["state"], "INVALID")

    def test_historical_p010_report_is_inventoried_but_excluded_by_default(self) -> None:
        report = evidence.inventory_report(self.root)
        item = next(row for row in report["items"] if row["source_id"] == "p010-operator-reported")
        self.assertEqual(item["state"], "PRESENT")
        self.assertEqual(item["export_status"], "OPT_IN_REQUIRED")
        dry_run = subprocess.run(
            [sys.executable, str(ROOT / "scripts/p018_evidence.py"), "export", "--dry-run",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertNotIn("p010-operator-reported", json.loads(dry_run.stdout)["would_export"])

    @unittest.skipUnless(os.geteuid() == 0, "root ownership is required to exercise operator export inclusion")
    def test_opt_in_operator_files_are_untrusted_and_sensitive_ids_are_rejected(self) -> None:
        private_temp = tempfile.TemporaryDirectory(prefix="ioscaf-p018-root-export-",
                                                   dir=ROOT / "build")
        self.addCleanup(private_temp.cleanup)
        path = Path(private_temp.name) / "operator.json"
        path.write_text('{"source_class":"DEVICE_REPORTED","observation":"review required"}\n')
        os.chmod(path, 0o600)
        source = evidence.operator_file_source(path)
        self.assertEqual(source["record"]["provenance"], "UNKNOWN")
        self.assertEqual(source["record"]["review_state"], "UNREVIEWED")
        self.assertNotIn(path.name, source["export_path"])
        path.write_text('{"assertion_id":12345}\n')
        with self.assertRaisesRegex(evidence.EvidenceError, "identifier"):
            evidence.operator_file_source(path)

    @unittest.skipUnless(os.geteuid() == 0, "root ownership is required to exercise export cleanup")
    def test_interrupted_export_removes_partial_bundle(self) -> None:
        private_temp = tempfile.TemporaryDirectory(prefix="ioscaf-p018-interrupt-",
                                                   dir=ROOT / "build")
        self.addCleanup(private_temp.cleanup)
        base = Path(private_temp.name)
        data_root = base / "evidence"
        data_root.mkdir(mode=0o700)
        destination = base / "bundle"
        original = evidence.write_new_file
        calls = 0

        def interrupt_after_first_file(*args, **kwargs):
            nonlocal calls
            if calls == 0:
                calls += 1
                return original(*args, **kwargs)
            raise evidence.ExportInterrupted("fixture interruption")

        with mock.patch.object(evidence, "write_new_file", side_effect=interrupt_after_first_file):
            with self.assertRaises(evidence.ExportInterrupted):
                evidence.export_bundle(destination, data_root)
        self.assertFalse(destination.exists())
        self.assertFalse(destination.is_symlink())

    def test_dry_run_is_inert_and_export_refuses_non_root(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/p018_evidence.py"), "export", "--dry-run",
             "--root", str(self.root), "--json"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["export_created"], "no")
        self.assertFalse((self.root / "export").exists())
        if os.geteuid() != 0:
            destination = Path(self.temp.name) / "bundle"
            blocked = subprocess.run(
                [sys.executable, str(ROOT / "scripts/p018_evidence.py"), "export", "--output",
                 str(destination), "--root", str(self.root), "--json"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertNotEqual(blocked.returncode, 0)
            blocked_report = json.loads(blocked.stdout)
            self.assertEqual(blocked_report["error_code"], "PERMISSION_DENIED")
            self.assertFalse(destination.exists())

    def test_export_failure_reports_partial_change_and_cleanup_as_unknown(self) -> None:
        destination = Path(self.temp.name) / "interrupted-bundle"
        output = io.StringIO()
        with mock.patch.object(evidence, "export_bundle",
                               side_effect=evidence.ExportInterrupted("fixture interruption")):
            with contextlib.redirect_stdout(output):
                result = evidence.main(["export", "--output", str(destination),
                                        "--root", str(self.root), "--json"])
        self.assertEqual(result, 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report["operation"], "evidence_export")
        self.assertEqual(report["error_code"], "IO_ERROR")
        self.assertEqual(report["changed"], "unknown")
        self.assertEqual(report["cleanup"], "unknown")


if __name__ == "__main__":
    unittest.main()
