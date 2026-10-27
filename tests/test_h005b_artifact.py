from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from scripts import h005b_artifact as artifact


def good_audit() -> dict[str, object]:
    return {
        "independent_code_directory_verified": True,
        "entitlements_exact_match": True,
        "adhoc_flag_present": True,
        "signature_kind": "ADHOC",
        "requirements": {"count": 0, "types": []},
    }


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


class H005BArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="h005b-artifact-test-")
        self.root = Path(self.temp.name)
        self.source_sha = "a" * 40
        self.source_tree = "b" * 40

    def tearDown(self) -> None:
        self.temp.cleanup()

    def provenance(self) -> dict[str, object]:
        return {
            "result": "VERIFIED",
            "source": {
                "commit": artifact.SIGNER_SOURCE,
                "tree": artifact.SIGNER_TREE,
                "independent_build_commit": artifact.SIGNER_SOURCE,
                "independent_build_tree": artifact.SIGNER_TREE,
            },
            "executable": {
                "sha256": artifact.SIGNER_SHA256,
                "version": artifact.SIGNER_VERSION,
            },
            "build_environment": {"container_image": "ubuntu@sha256:" + "d" * 64},
            "dependencies": {"gcc-13": "13.3.0"},
            "toolchain": {"gcc": "13.3.0"},
            "reproducibility": {
                "outcome": "EXACT_MATCH",
                "build_1_sha256": artifact.SIGNER_SHA256,
                "build_2_sha256": artifact.SIGNER_SHA256,
            },
        }

    def abi_report(self) -> Path:
        path = self.root / artifact.ABI_REPORT_NAME
        path.write_text(
            "\n".join((
                "H005_MACHO_ABI_INSPECTION_PASS",
                "iphoneos_sdk=12.4",
                "xcode=Xcode 16.4;Build version 16F6",
                "clang=Apple clang version 17.0.0",
                "target=arm64-apple-ios12.0",
                "platform_load_command=IOS",
                "minimum_os=12.0",
                "linked_frameworks=IOKit,CoreFoundation",
                "IOPMCopyAssertionsByProcess=runtime_dlsym_only",
                "IOPMCopyAssertionsStatus=runtime_dlsym_only",
                "assertion_mutation_imports=NONE",
                "execution_timeout_seconds=15",
                "runtime_behavior=UNVERIFIED_ON_IOS_12.5.7",
                "device_transfer=NOT_PERFORMED",
                "",
            )),
            encoding="utf-8",
        )
        return path

    def prepared_candidate(self) -> tuple[Path, Path]:
        candidate_dir = self.root / "pre-apple"
        candidate_dir.mkdir()
        binary = candidate_dir / artifact.INSPECTOR_NAME
        binary.write_bytes(b"signed-mock-inspector")
        abi = self.abi_report()
        provenance_path = self.root / "H003-SIGNER-PROVENANCE.json"
        write_json(provenance_path, self.provenance())
        signing = {
            "schema": "ioscaffeinate.h005b.signing-report.v1",
            "status": "SIGNED_PENDING_APPLE_VERIFICATION",
            "source": {
                "commit_sha": self.source_sha,
                "tree_sha": self.source_tree,
                "unsigned_binary_sha256": "c" * 64,
            },
            "signed_binary": {
                "file": artifact.INSPECTOR_NAME,
                "sha256": artifact.sha256_file(binary),
            },
            "signing": {
                "version": artifact.SIGNER_VERSION,
                "sha256": artifact.SIGNER_SHA256,
                "profile_id": artifact.PROFILE_ID,
                "profile_sha256": artifact.PROFILE_SHA256,
                "entitlements": artifact.EXPECTED_ENTITLEMENTS,
                "requirements_profile": artifact.ADHOC_REQUIREMENTS_PROFILE,
                "requirements_sha256": artifact.ADHOC_REQUIREMENTS_PROFILE_SHA256,
                "signer_provenance_sha256": artifact.sha256_file(provenance_path),
            },
        }
        write_json(candidate_dir / artifact.SIGNING_REPORT_NAME, signing)
        (candidate_dir / artifact.ABI_REPORT_NAME).write_bytes(abi.read_bytes())
        (candidate_dir / "H003-SIGNER-PROVENANCE.json").write_bytes(provenance_path.read_bytes())
        (candidate_dir / "source-commit.txt").write_text(self.source_sha + "\n", encoding="ascii")
        (candidate_dir / "source-tree.txt").write_text(self.source_tree + "\n", encoding="ascii")
        return candidate_dir, provenance_path

    def test_abi_report_rejects_wrong_platform_or_missing_toolchain(self) -> None:
        path = self.abi_report()
        self.assertEqual(artifact.parse_abi_report(path)["target"], "arm64-apple-ios12.0")
        path.write_text(path.read_text().replace("platform_load_command=IOS", "platform_load_command=IOS_SIMULATOR"))
        with self.assertRaisesRegex(artifact.ArtifactError, "required ARM64 iOS 12"):
            artifact.parse_abi_report(path)

    def test_signer_provenance_rejects_unpinned_or_nonreproducible_signer(self) -> None:
        path = self.root / "provenance.json"
        write_json(path, self.provenance())
        artifact.validate_signer_provenance(path)
        bad = self.provenance()
        bad["executable"] = {"sha256": "0" * 64, "version": artifact.SIGNER_VERSION}
        write_json(path, bad)
        with self.assertRaisesRegex(artifact.ArtifactError, "exact pinned reproducible"):
            artifact.validate_signer_provenance(path)

    def test_independent_signature_audit_rejects_default_requirements(self) -> None:
        audit = good_audit()
        audit["requirements"] = {"count": 1, "types": [3]}
        with self.assertRaisesRegex(artifact.ArtifactError, "signature, entitlement, or requirement"):
            artifact.validate_signature_audit(audit)

    def test_apple_verification_binds_exact_binary_hash_and_source(self) -> None:
        candidate_dir, _ = self.prepared_candidate()
        codesign = self.root / "codesign"
        codesign.write_text("mock", encoding="utf-8")
        codesign.chmod(0o700)
        output = self.root / "final"
        completed = SimpleNamespace(returncode=0, stdout="valid on disk\n", stderr="")
        with patch.object(artifact.sys, "platform", "darwin"), \
             patch.object(artifact, "CODESIGN_PATH", codesign), \
             patch.object(artifact.subprocess, "run", return_value=completed) as run, \
             patch.object(artifact, "audit_code_signature", return_value=good_audit()):
            manifest = artifact.verify_candidate(
                candidate_dir=candidate_dir, source_sha=self.source_sha,
                source_tree=self.source_tree, output_dir=output,
            )
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][1:4], ["--verify", "--strict", "--verbose=4"])
        self.assertEqual(manifest["source"]["commit_sha"], self.source_sha)
        self.assertEqual(manifest["artifact_sha256"], artifact.sha256_file(output / artifact.INSPECTOR_NAME))
        self.assertEqual(manifest["scope"]["device_execution"], "NOT_PERFORMED")
        self.assertTrue((output / artifact.MANIFEST_NAME).is_file())
        self.assertTrue((output / "SHA256SUMS").is_file())

    def test_tampered_candidate_fails_before_apple_verification(self) -> None:
        candidate_dir, _ = self.prepared_candidate()
        binary = candidate_dir / artifact.INSPECTOR_NAME
        binary.write_bytes(b"tampered")
        with patch.object(artifact.sys, "platform", "darwin"), \
             patch.object(artifact.subprocess, "run") as run:
            with self.assertRaisesRegex(artifact.ArtifactError, "hash or source identity"):
                artifact.verify_candidate(
                    candidate_dir=candidate_dir, source_sha=self.source_sha,
                    source_tree=self.source_tree, output_dir=self.root / "final",
                )
        run.assert_not_called()

    def test_failed_apple_strict_check_does_not_emit_final_manifest(self) -> None:
        candidate_dir, _ = self.prepared_candidate()
        codesign = self.root / "codesign"
        codesign.write_text("mock", encoding="utf-8")
        codesign.chmod(0o700)
        output = self.root / "failed-final"
        completed = SimpleNamespace(returncode=3, stdout="", stderr="strict verification failed")
        with patch.object(artifact.sys, "platform", "darwin"), \
             patch.object(artifact, "CODESIGN_PATH", codesign), \
             patch.object(artifact.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(artifact.ArtifactError, "Apple strict codesign verification failed"):
                artifact.verify_candidate(
                    candidate_dir=candidate_dir, source_sha=self.source_sha,
                    source_tree=self.source_tree, output_dir=output,
                )
        self.assertFalse((output / artifact.MANIFEST_NAME).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
