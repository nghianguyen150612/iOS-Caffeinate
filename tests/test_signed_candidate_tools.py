from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_candidate_inventory as inventory  # noqa: E402
import finalize_signed_candidate as finalizer  # noqa: E402
import p020_signed_rc_manifest as rc_manifest  # noqa: E402
import signing_profile  # noqa: E402
import verify_signed_candidate_macos as macos_verify  # noqa: E402


def ar_member(name: str, data: bytes) -> bytes:
    header = (
        f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{0o100644:<8}{len(data):<10}`\n"
    ).encode("ascii")
    return header + data + (b"\n" if len(data) & 1 else b"")


def candidate_deb(path: Path, *, unsafe_path: bool = False) -> dict[str, bytes]:
    binaries = {
        "ios-caffeinate": b"signed-cli-macho",
        "ios-caffeinated": b"signed-daemon-macho",
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:xz") as archive:
        for name, content in binaries.items():
            member = tarfile.TarInfo(f"usr/local/bin/{name}")
            member.mode = 0o755
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        if unsafe_path:
            member = tarfile.TarInfo("../outside")
            member.mode = 0o644
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))
    path.write_bytes(b"!<arch>\n" + ar_member("debian-binary", b"2.0\n") + ar_member("data.tar.xz", stream.getvalue()))
    return binaries


class SignedCandidateToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ioscaf-r05-signed-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_rc_codesign_failure_fails_job_but_preserves_receipt(self) -> None:
        workflow = (ROOT / ".github/workflows/p020-signed-rc-candidate.yml").read_text()
        verifier = workflow.split(
            "      - name: Verify both signed executables with Apple codesign\n", 1
        )[1].split(
            "      - name: Upload actual Apple signature-integrity receipt, including failures\n", 1
        )[0]
        upload = workflow.split(
            "      - name: Upload actual Apple signature-integrity receipt, including failures\n", 1
        )[1].split("  finalize-candidate:\n", 1)[0]
        self.assertNotIn("continue-on-error: true", verifier)
        self.assertIn("if: always()", upload)
        self.assertIn("if: needs.macos-signature-integrity.result == 'success'", workflow)

    def test_pinned_h003_signer_identity_survives_missing_runtime_banner(self) -> None:
        signer = self.root / "ldid"
        signer.write_bytes(b"verified pinned signer")
        signer.chmod(0o755)
        digest = "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c"
        with patch.object(signing_profile, "sha256", return_value=digest), patch.object(
            signing_profile.subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)
        ):
            self.assertEqual(
                signing_profile.signer_identity(signer),
                ("2.1.5-procursus7", digest),
            )

    def test_unpinned_signer_without_runtime_banner_is_rejected(self) -> None:
        signer = self.root / "unknown-ldid"
        signer.write_bytes(b"unknown signer")
        signer.chmod(0o755)
        with patch.object(signing_profile.subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
            with self.assertRaisesRegex(signing_profile.SigningError, "version banner"):
                signing_profile.signer_identity(signer)

    def test_macos_verifier_records_both_binary_results_and_exact_package_hash(self) -> None:
        package = self.root / "candidate.deb"
        binaries = candidate_deb(package)
        output = self.root / "receipt.json"
        real_is_file = Path.is_file
        real_access = macos_verify.os.access

        def is_file(path: Path) -> bool:
            return True if path == Path("/usr/bin/codesign") else real_is_file(path)

        def access(path: str | Path, mode: int) -> bool:
            return True if Path(path) == Path("/usr/bin/codesign") else real_access(path, mode)

        with patch.object(Path, "is_file", is_file), patch.object(macos_verify.os, "access", access), \
             patch.object(macos_verify.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="verified\n", stderr="")) as run:
            receipt = macos_verify.verify_package(package, "a" * 40, output, platform_name="darwin")

        self.assertEqual(receipt["status"], "VERIFIED")
        self.assertEqual(receipt["package_sha256"], hashlib.sha256(package.read_bytes()).hexdigest())
        self.assertEqual({item["name"] for item in receipt["binary_results"]}, set(binaries))
        self.assertEqual(run.call_count, 2)
        self.assertEqual(json.loads(output.read_text()), receipt)

    def test_macos_verifier_preserves_failed_codesign_result(self) -> None:
        package = self.root / "candidate.deb"
        candidate_deb(package)
        output = self.root / "receipt.json"
        real_is_file = Path.is_file
        real_access = macos_verify.os.access

        def is_file(path: Path) -> bool:
            return True if path == Path("/usr/bin/codesign") else real_is_file(path)

        def access(path: str | Path, mode: int) -> bool:
            return True if Path(path) == Path("/usr/bin/codesign") else real_access(path, mode)

        with patch.object(Path, "is_file", is_file), patch.object(macos_verify.os, "access", access), \
             patch.object(macos_verify.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="invalid signature")):
            receipt = macos_verify.verify_package(package, "a" * 40, output, platform_name="darwin")
        self.assertEqual(receipt["status"], "FAILED")
        self.assertTrue(all(item["exit_code"] == 1 for item in receipt["binary_results"]))

    def test_macos_verifier_rejects_traversal_in_package_data(self) -> None:
        package = self.root / "unsafe.deb"
        candidate_deb(package, unsafe_path=True)
        with self.assertRaisesRegex(macos_verify.VerificationError, "unsafe path"):
            macos_verify.read_payload_binary(package, "usr/local/bin/ios-caffeinate")

    def test_finalizer_accepts_only_matching_package_and_receipt(self) -> None:
        package = self.root / "ioscaffeinate_0.2.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb"
        package.write_bytes(b"signed package")
        package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
        source_sha = "a" * 40
        binary_hashes = {name: hashlib.sha256(name.encode()).hexdigest() for name in finalizer.BINARIES}
        package_record = {
            "source_commit_sha": source_sha,
            "package_identifier": "com.ioscaffeinate.cli",
            "package_version": "0.2.0~rc1-1",
            "architecture": "iphoneos-arm",
            "source_tree_clean": True,
            "package": {"file": package.name, "sha256": package_sha},
            "signing": {
                "state": "SIGNATURE_PRESENT",
                "profile_id": finalizer.EXPECTED_PROFILE,
                "profile_sha256": finalizer.EXPECTED_PROFILE_SHA256,
                "signing_tool_version": "2.1.5-procursus7",
                "signing_tool_sha256": "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c",
                "embedded_entitlements": "EXACT_MATCH",
                "signature_verification": "PENDING",
                "final_binary_sha256": binary_hashes,
            },
        }
        results = [{
            "name": name,
            "package_path": relative,
            "binary_sha256": binary_hashes[name],
            "exit_code": 0,
            "command": ["/usr/bin/codesign", "--verify", "--strict", "--verbose=2", "/tmp/" + name],
        } for name, relative in finalizer.BINARIES.items()]
        receipt = {
            "schema_version": 1,
            "status": "VERIFIED",
            "source_commit_sha": source_sha,
            "package_file": package.name,
            "package_sha256": package_sha,
            "host": "macOS",
            "tool": "/usr/bin/codesign",
            "method": "codesign --verify --strict --verbose=2",
            "binary_results": results,
        }
        actual_sha, actual_binaries = finalizer.validate_receipt(package, package_record, receipt, source_sha)
        self.assertEqual(actual_sha, package_sha)
        self.assertEqual(actual_binaries, binary_hashes)
        receipt["package_sha256"] = "0" * 64
        with self.assertRaisesRegex(finalizer.FinalizationError, "receipt does not match"):
            finalizer.validate_receipt(package, package_record, receipt, source_sha)

    def test_finalizer_writes_validator_sidecars_before_final_validation(self) -> None:
        package_dir = self.root / "input"
        package_dir.mkdir()
        package = package_dir / "ioscaffeinate_0.2.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb"
        package.write_bytes(b"signed input package")
        source_sha = "a" * 40
        binary_bytes = {"ios-caffeinate": b"signed cli", "ios-caffeinated": b"signed daemon"}
        binary_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in binary_bytes.items()}
        package_build = {
            "source_commit_sha": source_sha,
            "signing": {
                "signature_verification": "PENDING",
                "profile_id": finalizer.EXPECTED_PROFILE,
                "profile_sha256": finalizer.EXPECTED_PROFILE_SHA256,
                "final_binary_sha256": binary_hashes,
            },
        }
        signing_state = "signature_verification=PENDING\n"
        payload_files = {
            "usr/local/bin/ios-caffeinate": binary_bytes["ios-caffeinate"],
            "usr/local/bin/ios-caffeinated": binary_bytes["ios-caffeinated"],
            "usr/share/ioscaffeinate/package-build.json": (json.dumps(package_build) + "\n").encode(),
            "usr/share/ioscaffeinate/SIGNING-STATE": signing_state.encode(),
        }
        embedded_sums = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {relative}\n"
            for relative, data in sorted(payload_files.items())
        )
        package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
        package_record = {
            "source_commit_sha": source_sha,
            "source_tree_clean": True,
            "package_identifier": "com.ioscaffeinate.cli",
            "package_version": "0.2.0~rc1-1",
            "architecture": "iphoneos-arm",
            "package": {"file": package.name, "sha256": package_sha},
            "signing": {
                "state": "SIGNATURE_PRESENT",
                "profile_id": finalizer.EXPECTED_PROFILE,
                "profile_sha256": finalizer.EXPECTED_PROFILE_SHA256,
                "signing_tool_version": "2.1.5-procursus7",
                "signing_tool_sha256": "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c",
                "embedded_entitlements": "EXACT_MATCH",
                "signature_verification": "PENDING",
                "final_binary_sha256": binary_hashes,
            },
        }
        (package_dir / f"{package.name}.manifest.json").write_text(json.dumps(package_record))
        (package_dir / f"{package.name}.manifest.txt").write_text(
            f"source_date_epoch: 1700000000\nartifact_sha256: {package_sha}\nsignature_verification: PENDING\n")
        (package_dir / f"{package.name}.files.sha256").write_text(embedded_sums)
        (package_dir / f"{package.name}.sha256").write_text(f"{package_sha}  {package.name}\n")
        receipt_path = self.root / "receipt.json"
        receipt = {
            "schema_version": 1, "status": "VERIFIED", "source_commit_sha": source_sha,
            "package_file": package.name, "package_sha256": package_sha, "host": "macOS",
            "tool": "/usr/bin/codesign", "method": "codesign --verify --strict --verbose=2",
            "binary_results": [{
                "name": name,
                "package_path": finalizer.BINARIES[name],
                "binary_sha256": binary_hashes[name],
                "exit_code": 0,
                "command": ["/usr/bin/codesign", "--verify", "--strict", "--verbose=2", "/tmp/" + name],
            } for name in finalizer.BINARIES],
        }
        receipt_path.write_text(json.dumps(receipt))
        signer = self.root / "ldid"
        signer.write_bytes(b"test signer")
        signer.chmod(0o755)
        output_dir = self.root / "final"
        args = SimpleNamespace(package=package, signature_receipt=receipt_path, source_sha=source_sha,
                               ldid=signer, output_dir=output_dir)

        def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
            if command[:2] == ["dpkg-deb", "--raw-extract"]:
                extracted = Path(command[-1])
                for relative, data in payload_files.items():
                    destination = extracted / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                sums_path = extracted / "usr/share/ioscaffeinate/SHA256SUMS"
                sums_path.write_text(embedded_sums)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if command[:2] == ["dpkg-deb", "--build"]:
                Path(command[-1]).write_bytes(b"final package bytes")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if "--report" in command:
                for suffix in (".files.sha256", ".sha256", ".manifest.txt", ".manifest.json"):
                    self.assertTrue(Path(str(output_dir / package.name) + suffix).is_file(), suffix)
                Path(command[-1]).write_text("signature_verification=SIGNATURE_VERIFIED\n")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(finalizer.subprocess, "run", side_effect=fake_run):
            result = finalizer.finalize(args)
        final_package = output_dir / package.name
        self.assertEqual(result["final_package_sha256"], hashlib.sha256(final_package.read_bytes()).hexdigest())
        self.assertEqual((output_dir / f"{package.name}.sha256").read_text(),
                         f"{result['final_package_sha256']}  {package.name}\n")
        self.assertIn("signature_verification: SIGNATURE_VERIFIED",
                      (output_dir / f"{package.name}.manifest.txt").read_text())

    def test_signed_rc_manifest_binds_files_and_keeps_physical_gates_pending(self) -> None:
        root = self.root / "build" / "p020"
        final = root / "signed-final"
        final.mkdir(parents=True)
        source_sha = "a" * 40
        tree_sha = "b" * 40
        package = final / "ioscaffeinate_0.2.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb"
        package.write_bytes(b"signed package bytes")
        package_sha = rc_manifest.sha256(package)
        package_record = {
            "source_commit_sha": source_sha,
            "source_tree_clean": True,
            "package_identifier": "com.ioscaffeinate.cli",
            "package_version": "0.2.0~rc1-1",
            "architecture": "iphoneos-arm",
            "package": {"file": package.name, "sha256": package_sha},
            "signing": {
                "state": "SIGNATURE_PRESENT",
                "profile_id": rc_manifest.EXPECTED_PROFILE,
                "profile_sha256": rc_manifest.EXPECTED_PROFILE_SHA256,
                "signing_tool_version": rc_manifest.EXPECTED_SIGNER_VERSION,
                "signing_tool_sha256": rc_manifest.EXPECTED_SIGNER_SHA256,
                "embedded_entitlements": "EXACT_MATCH",
                "signature_verification": "SIGNATURE_VERIFIED",
                "device_execution_verification": "NOT_VERIFIED",
                "device_package_acceptance": "NOT_ACCEPTED",
                "final_binary_sha256": {
                    "ios-caffeinate": "c" * 64,
                    "ios-caffeinated": "d" * 64,
                },
            },
        }
        (final / f"{package.name}.manifest.json").write_text(json.dumps(package_record))
        (final / f"{package.name}.sha256").write_text(f"{package_sha}  {package.name}\n")
        (final / f"{package.name}.files.sha256").write_text("e" * 64 + "  usr/share/ioscaffeinate/package-build.json\n")
        validation = final / "signed-validation.txt"
        validation.write_text("\n".join((
            "package=com.ioscaffeinate.cli", "version=0.2.0~rc1-1", "architecture=iphoneos-arm",
            "signing_state=SIGNATURE_PRESENT", "embedded_entitlements=EXACT_MATCH",
            "signature_verification=SIGNATURE_VERIFIED", "device_execution=NOT_VERIFIED",
            "device_package_acceptance=NOT_ACCEPTED", "result=PASS",
        )) + "\n")

        build = {
            "source": {"repository": rc_manifest.EXPECTED_SOURCE, "commit_sha": source_sha, "tree_sha": tree_sha, "worktree_clean": True},
            "build_configuration": {"target_triple": "arm64-apple-ios12.0", "deployment_target": "12.0"},
            "toolchain": {"sdk_name": "iPhoneOS", "sdk_version": "18.0", "xcode_version": "Xcode 16.0", "compiler_version": "Apple clang 16"},
            "artifacts": {},
            "reproducibility": {"status": "REPRODUCIBLE", "independent_builds": 2, "artifact_hashes_match": True},
            "ci": {"source_sha_verified": True, "run_id": "123", "run_url": "https://example.invalid/ci/123"},
            "candidate_state": "UNSIGNED_DEVELOPMENT",
        }
        release = {"release": {"version": "v0.2.0", "package_identifier": "com.ioscaffeinate.cli", "package_version": "0.2.0~rc1-1", "architecture": "iphoneos-arm"}, "source": {"commit_sha": source_sha}}
        assessment = {"decision": "RELEASE_BLOCKED", "publication_authorized": False, "hardware_gates": {"p012": {"status": "PENDING"}}}
        signer = {"result": "VERIFIED", "executable": {"version": rc_manifest.EXPECTED_SIGNER_VERSION, "sha256": rc_manifest.EXPECTED_SIGNER_SHA256}, "reproducibility": {"outcome": "EXACT_MATCH"}}
        receipt = {
            "status": "VERIFIED", "source_commit_sha": source_sha, "host": "macOS", "tool": "/usr/bin/codesign",
            "binary_results": [
                {"name": "ios-caffeinate", "binary_sha256": "c" * 64},
                {"name": "ios-caffeinated", "binary_sha256": "d" * 64},
            ],
        }
        receipt_path = root / "signature-integrity-verification.json"
        receipt_path.write_text(json.dumps(receipt))
        finalization = {
            "source_commit_sha": source_sha, "final_package_sha256": package_sha,
            "macos_receipt_sha256": rc_manifest.sha256(receipt_path),
            "repackaging": "SIGNING_METADATA_ONLY_BINARIES_UNCHANGED", "final_package_validation": "PASS",
            "binary_sha256": {"ios-caffeinate": "c" * 64, "ios-caffeinated": "d" * 64},
        }
        finalization_path = final / "finalization-provenance.json"
        finalization_path.write_text(json.dumps(finalization))
        signer_path = root / "signer-provenance.json"
        signer_path.write_text(json.dumps(signer))
        build_path = root / "P020-BUILD-PROVENANCE.json"
        build_path.write_text(json.dumps(build))
        release_path = root / "release-manifest.json"
        release_path.write_text(json.dumps(release))
        assessment_path = root / "release-assessment.json"
        assessment_path.write_text(json.dumps(assessment))

        with patch.object(rc_manifest, "validate_build_provenance"):
            manifest = rc_manifest.assemble_manifest(
                build_path=build_path,
                release_path=release_path,
                assessment_path=assessment_path,
                package=package,
                package_manifest_path=final / f"{package.name}.manifest.json",
                signer_path=signer_path,
                signature_receipt_path=receipt_path,
                finalization_path=finalization_path,
                validation_path=validation,
                source_sha=source_sha,
                workflow_run_id="456",
                workflow_run_url="https://example.invalid/run/456",
                workflow_branch="docs/h004-device-phase0-readiness",
            )
        self.assertEqual(manifest["candidate_state"], "SIGNED_RC_DEVICE_UNVERIFIED")
        self.assertEqual(manifest["package"]["sha256"], package_sha)
        self.assertEqual(manifest["validation"]["release_readiness"], "RELEASE_BLOCKED")
        self.assertFalse(manifest["validation"]["publication_authorized"])
        self.assertEqual(manifest["validation"]["package_validation_report"]["sha256"], rc_manifest.sha256(validation))

    def test_candidate_inventory_is_sorted_and_refuses_symlinks(self) -> None:
        root = self.root / "inventory"
        (root / "z").mkdir(parents=True)
        (root / "z" / "last.txt").write_text("last")
        (root / "first.txt").write_text("first")
        output = root / "SHA256SUMS"
        rows = inventory.create_inventory(root, output)
        self.assertEqual([row.split("  ", 1)[1] for row in rows], ["first.txt", "z/last.txt"])
        self.assertEqual(output.read_text(), "\n".join(rows) + "\n")
        (root / "unsafe").symlink_to(root / "first.txt")
        with self.assertRaisesRegex(inventory.InventoryError, "symlink"):
            inventory.create_inventory(root, root / "SECOND-SHA256SUMS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
