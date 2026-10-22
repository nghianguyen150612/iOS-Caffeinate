from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import p020_release_gate as gate  # noqa: E402
from p020_fixtures import release_manifest, write_json  # noqa: E402


class P020ReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ioscaf-p020-gate-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        self.base_sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "origin/main"], check=True, capture_output=True, text=True).stdout.strip()
        self.manifest = release_manifest(self.root, source_sha=self.source_sha, base_sha=self.base_sha)
        self.manifest_path = self.root / "release-manifest.json"
        self.write_manifest()

    def write_manifest(self) -> None:
        self.manifest_path.write_text(json.dumps(self.manifest, sort_keys=True, indent=2) + "\n")

    def test_current_missing_hardware_evidence_blocks_release(self) -> None:
        result = gate.assess(self.manifest_path, self.source_sha)
        self.assertEqual(result["decision"], "RELEASE_BLOCKED")
        self.assertTrue(all(item["status"] == "PASS" for item in result["cloud_gates"].values()))
        self.assertTrue(all(item["status"] == "PENDING" for item in result["hardware_gates"].values()))
        self.assertIn("SIGNER_PROVENANCE_BLOCKED", result["hardware_gates"]["p010_signer_provenance"]["reason"])
        self.assertFalse(result["publication_authorized"])

    def test_user_supplied_hardware_pass_boolean_is_rejected_by_schema(self) -> None:
        self.manifest["hardware_gates"]["p012_physical_trials"]["status"] = "PASS"
        self.write_manifest()
        with self.assertRaisesRegex(gate.GateError, "schema validation failed"):
            gate.assess(self.manifest_path, self.source_sha)

    def test_simulated_p019_result_cannot_satisfy_physical_gate(self) -> None:
        payload = {
            "artifact_type": "P019_ACCEPTANCE_RESULT",
            "status": "ACCEPTED_FOR_TESTED_SCOPE",
            "hardware_acceptance": "ACCEPTED_FOR_TESTED_SCOPE",
            "evidence_class": "SIMULATED",
            "metrics": {"planned_trials": 24, "valid_trials": 24, "invalid_trials": 0,
                        "incomplete_trials": 0, "interrupted_trials": 0,
                        "successful_bounded_holds": 12, "confirmed_releases": 12,
                        "release_failures": 0, "unexpected_daemon_exits": 0, "unexpected_restarts": 0},
            "p009_review": {"status": "PASS"}, "p018_export_review": {"status": "PASS"},
        }
        digest = write_json(self.root / "simulated-p019.json", payload)
        review = {
            "schema_version": 1, "reviewer_id": "independent.reviewer",
            "reviewed_at_utc": "2026-10-22T12:00:00Z", "review_scope": "Synthetic negative-path fixture only.",
            "conclusion": "ACCEPTED", "independent": True, "evidence_sha256": [digest], "findings": [],
        }
        review_digest = write_json(self.root / "review.json", review)
        signature_digest = write_json(self.root / "review.json.sig", {"fixture": "unsigned synthetic placeholder"})
        self.manifest["hardware_gates"]["p019_supervised_cycles"]["evidence"] = [{
            "artifact_type": "P019_ACCEPTANCE_RESULT",
            "file": {"path": "simulated-p019.json", "sha256": digest, "evidence_class": "SIMULATED"},
            "review_receipt": {"path": "review.json", "sha256": review_digest,
                               "signature": {"path": "review.json.sig", "sha256": signature_digest},
                               "signer_fingerprint": "A" * 40},
        }]
        self.write_manifest()
        result = gate.assess(self.manifest_path, self.source_sha)
        self.assertEqual(result["decision"], "RELEASE_BLOCKED")
        self.assertEqual(result["hardware_gates"]["p019_supervised_cycles"]["status"], "BLOCKED")
        self.assertIn("SIMULATED", result["hardware_gates"]["p019_supervised_cycles"]["reason"])

    def test_untrusted_review_receipt_cannot_pass_hardware_gate(self) -> None:
        evidence = {"artifact_type": "P011_DEVICE_ACCEPTANCE", "status": "ACCEPTED", "evidence_class": "DEVICE_REPORTED"}
        evidence_digest = write_json(self.root / "device.json", evidence)
        receipt = {
            "schema_version": 1, "reviewer_id": "independent.reviewer",
            "reviewed_at_utc": "2026-10-22T12:00:00Z", "review_scope": "P011 device acceptance evidence review.",
            "conclusion": "ACCEPTED", "independent": True, "evidence_sha256": [evidence_digest], "findings": [],
        }
        receipt_digest = write_json(self.root / "device-review.json", receipt)
        signature_digest = write_json(self.root / "device-review.json.sig", {"fixture": "not a cryptographic signature"})
        self.manifest["hardware_gates"]["p011_stable_package_acceptance"]["evidence"] = [{
            "artifact_type": "P011_DEVICE_ACCEPTANCE",
            "file": {"path": "device.json", "sha256": evidence_digest, "evidence_class": "DEVICE_REPORTED"},
            "review_receipt": {
                "path": "device-review.json", "sha256": receipt_digest,
                "signature": {"path": "device-review.json.sig", "sha256": signature_digest},
                "signer_fingerprint": "A" * 40,
            },
        }]
        self.write_manifest()
        result = gate.assess(self.manifest_path, self.source_sha)
        self.assertEqual(result["decision"], "RELEASE_BLOCKED")
        self.assertEqual(result["hardware_gates"]["p011_stable_package_acceptance"]["status"], "UNVERIFIED")
        self.assertIn("trusted reviewer keyring", result["hardware_gates"]["p011_stable_package_acceptance"]["reason"])

    def test_cloud_pass_without_matching_exact_source_attestation_fails(self) -> None:
        self.manifest["cloud_gates"]["ios_cross_build"]["evidence"] = []
        self.write_manifest()
        result = gate.assess(self.manifest_path, self.source_sha)
        self.assertEqual(result["cloud_gates"]["ios_cross_build"]["status"], "FAILED")
        self.assertEqual(result["decision"], "RELEASE_BLOCKED")

    def test_chain_head_and_exact_head_ci_are_checked(self) -> None:
        self.manifest["source"]["milestone_chain"][7]["head_sha"] = "a" * 40
        self.manifest["source"]["milestone_chain"][8]["exact_head_ci"] = "PENDING"
        self.write_manifest()
        result = gate.assess(self.manifest_path, self.source_sha)
        self.assertEqual(result["decision"], "RELEASE_BLOCKED")
        self.assertEqual(len(result["chain_issues"]), 2)

    def test_assess_and_report_are_offline_read_only_commands(self) -> None:
        before = self.manifest_path.read_bytes()
        assessed = subprocess.run([
            sys.executable, str(ROOT / "scripts/p020_release_gate.py"), "assess",
            "--manifest", str(self.manifest_path), "--expected-source-sha", self.source_sha,
        ], capture_output=True, text=True)
        self.assertEqual(assessed.returncode, 0, msg=assessed.stderr)
        self.assertEqual(json.loads(assessed.stdout)["decision"], "RELEASE_BLOCKED")
        report = subprocess.run([
            sys.executable, str(ROOT / "scripts/p020_release_gate.py"), "report",
            "--manifest", str(self.manifest_path), "--expected-source-sha", self.source_sha,
        ], capture_output=True, text=True)
        self.assertEqual(report.returncode, 0, msg=report.stderr)
        self.assertIn("SIGNER_PROVENANCE_BLOCKED", report.stdout)
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_hardware_gate_file_hash_mismatch_fails_closed(self) -> None:
        file_record = {"path": "ci-attestation.json", "sha256": "0" * 64, "evidence_class": "DEVICE_REPORTED"}
        self.manifest["hardware_gates"]["p011_stable_package_acceptance"]["evidence"] = [{
            "artifact_type": "P011_DEVICE_ACCEPTANCE", "file": file_record, "review_receipt": None,
        }]
        self.write_manifest()
        result = gate.assess(self.manifest_path, self.source_sha)
        self.assertEqual(result["hardware_gates"]["p011_stable_package_acceptance"]["status"], "FAILED")
        self.assertEqual(result["decision"], "RELEASE_BLOCKED")

    def test_evidence_store_enforces_aggregate_and_file_count_limits(self) -> None:
        (self.root / "one.bin").write_bytes(b"123456")
        (self.root / "two.bin").write_bytes(b"abcdef")
        store = gate.EvidenceStore(self.root, max_files=1, max_total_bytes=10)
        self.assertEqual(store.read("one.bin"), b"123456")
        with self.assertRaisesRegex(gate.GateError, "distinct files"):
            store.read("two.bin")
        store = gate.EvidenceStore(self.root, max_files=2, max_total_bytes=10)
        store.read("one.bin")
        with self.assertRaisesRegex(gate.GateError, "aggregate limit"):
            store.read("two.bin")

    def test_evidence_store_rejects_symlinks(self) -> None:
        (self.root / "target.bin").write_bytes(b"safe")
        (self.root / "link.bin").symlink_to("target.bin")
        with self.assertRaisesRegex(gate.GateError, "cannot safely open"):
            gate.EvidenceStore(self.root).read("link.bin")

    def test_candidate_package_and_binary_hashes_are_cross_bound(self) -> None:
        signer = {
            "package_sha256": "a" * 64,
            "final_binary_sha256": {"cli": "b" * 64, "daemon": "c" * 64},
            "source_binary_sha256": {"cli": "d" * 64, "daemon": "e" * 64},
        }
        identity = {
            "source_commit_sha": self.source_sha, "package_identifier": "com.ioscaffeinate.cli",
            "package_version": "0.2.0~rc1-1", "package_sha256": "a" * 64,
            "profile_id": "amethyst-ios12-rootful", "profile_sha256": gate.EXPECTED_PROFILE_SHA256,
            "ldid_version": gate.EXPECTED_SIGNER_VERSION, "ldid_sha256": gate.EXPECTED_SIGNER_SHA256,
            "build_id": "candidate-1", "rollback_artifact_sha256": "f" * 64,
            "cli_binary_sha256": "b" * 64, "daemon_binary_sha256": "c" * 64,
            "source_cli_binary_sha256": "d" * 64, "source_daemon_binary_sha256": "e" * 64,
        }
        candidate = dict(identity)
        session = {"candidate": candidate}
        payloads = {
            "p010_signer_provenance": {"P010_SIGNER_PROVENANCE": signer},
            "installed_candidate_identity": {"V02_CANDIDATE_IDENTITY": identity},
            "p019_supervised_cycles": {"P019_SESSION": session},
        }
        self.assertEqual(gate._candidate_evidence_issues(payloads), [])
        session["candidate"]["daemon_binary_sha256"] = "0" * 64
        self.assertTrue(any("P019 session CLI/daemon hashes" in item for item in gate._candidate_evidence_issues(payloads)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
