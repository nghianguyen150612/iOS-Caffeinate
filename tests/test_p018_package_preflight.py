from __future__ import annotations

import hashlib
import contextlib
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import p018_package_preflight as preflight  # noqa: E402


def package_fixture(directory: Path, *, provenance: bool = True) -> tuple[Path, dict[str, bytes | None]]:
    directory.mkdir(parents=True, exist_ok=True)
    package = directory / "candidate.deb"
    package_raw = b"synthetic, never-installed, P018 package fixture\n"
    package.write_bytes(package_raw)
    digest = hashlib.sha256(package_raw).hexdigest()
    (directory / "candidate.deb.sha256").write_text(f"{digest}  candidate.deb\n")
    profile = plistlib.dumps({"com.apple.private.security.no-container": True}, fmt=plistlib.FMT_XML)
    profile_hash = hashlib.sha256(profile).hexdigest()
    commit = "b" * 40
    signing = {
        "state": "SIGNATURE_PRESENT",
        "profile_id": "amethyst-ios12-rootful",
        "profile_sha256": profile_hash,
        "signing_tool_version": "ldid-test-1",
        "signing_tool_sha256": "c" * 64,
        "embedded_entitlements": "EXACT_MATCH",
        "signature_verification": "SIGNATURE_VERIFIED",
        "signature_integrity": {"status": "VERIFIED", "tool": "fixture", "results": []},
    }
    base_record = {
        "schema_version": 1,
        "package_identifier": "com.ioscaffeinate.cli",
        "package_version": "0.1.0-2",
        "architecture": "iphoneos-arm",
        "source_commit_sha": commit,
        "source_tree_clean": True,
        "signing": signing,
    }
    embedded = json.dumps(base_record, sort_keys=True).encode() + b"\n"
    package_record = dict(base_record)
    package_record["package"] = {"file": package.name, "sha256": digest}
    (directory / "candidate.deb.manifest.json").write_text(json.dumps(package_record, sort_keys=True) + "\n")

    members: dict[str, bytes | None] = {
        "usr/share/ioscaffeinate/package-build.json": embedded,
        "usr/share/ioscaffeinate/SIGNING-STATE": (
            "signature_state=SIGNATURE_PRESENT\nprofile_id=amethyst-ios12-rootful\n"
            f"profile_sha256={profile_hash}\nembedded_entitlements=EXACT_MATCH\n"
        ).encode(),
        "usr/share/ioscaffeinate/signing/amethyst-ios12-rootful.plist": profile,
        "usr/local/bin/ic": None,
    }
    checksum_records = []
    for name, content in sorted(members.items()):
        if content is not None:
            checksum_records.append(f"{hashlib.sha256(content).hexdigest()}  {name}")
    members["usr/share/ioscaffeinate/SHA256SUMS"] = ("\n".join(checksum_records) + "\n").encode()

    if provenance:
        candidate = {
            "manifest_version": 1,
            "package_version": "0.1.0-2",
            "source": {"commit_sha": commit,
                       "workflow_url": "https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/123"},
            "signing": {
                "profile_id": signing["profile_id"],
                "profile_sha256": profile_hash,
                "signing_tool_version": signing["signing_tool_version"],
                "signing_tool_sha256": signing["signing_tool_sha256"],
                "signature_integrity": "SIGNATURE_VERIFIED",
            },
            "artifacts": {"signed_candidate_package": {"path": package.name, "sha256": digest}},
            "ci": {"source_sha_pinned": True, "jobs": {
                "linux-protocol": "success", "ios-cross-build": "success",
                "ios-artifact-inspection": "success", "ios-rootful-package": "success",
                "p009-evidence-validation": "success", "p010-signing-release-gate": "PASS",
                "p008-release-attestation": "SKIPPED_EXPECTED_BRANCH_GUARD",
            }},
            "device_execution": "NOT_VERIFIED",
            "device_package_acceptance": "NOT_ACCEPTED",
            "release_authorization_status": "BLOCKED",
        }
        (directory / "candidate.deb.P010-SIGNED-CANDIDATE-MANIFEST.json").write_text(
            json.dumps(candidate, sort_keys=True) + "\n"
        )
    return package, members


class P018PackagePreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ioscaf-p018-package-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package, self.members = package_fixture(self.root)

    def call_preflight(self, *, architecture: str = "iphoneos-arm", collisions=()):
        def field(_package, field, _pass_fds=()):
            return {"Package": "com.ioscaffeinate.cli", "Version": "0.1.0-2",
                    "Architecture": architecture}[field]
        with patch.object(preflight, "dpkg_field", side_effect=field), \
                patch.object(preflight, "stream_archive", return_value=self.members), \
                patch.object(preflight, "check_collisions", return_value=list(collisions)):
            return preflight.validate_artifact(self.package, None)

    def test_exact_artifact_and_p010_provenance_are_ready_for_operator_review(self) -> None:
        result = self.call_preflight()
        self.assertEqual(result["decision"], "READY_FOR_OPERATOR_REVIEW")
        self.assertEqual(result["signer_provenance"], "VALID")
        self.assertEqual(result["path_collisions"], "CLEAR")
        self.assertEqual(result["hardware_acceptance"], "NOT_ESTABLISHED")
        self.assertEqual(result["package_installed"], "no")

    def test_wrong_architecture_is_rejected(self) -> None:
        with patch.object(preflight, "dpkg_field", side_effect=lambda _p, key, _fds=():
                          {"Package": "com.ioscaffeinate.cli", "Version": "0.1.0-2",
                           "Architecture": "all"}[key]):
            with self.assertRaisesRegex(preflight.PreflightError, "architecture"):
                preflight.validate_artifact(self.package, None)

    def test_hash_mismatch_and_malformed_sidecar_are_rejected(self) -> None:
        (self.root / "candidate.deb.sha256").write_text("0" * 64 + "  candidate.deb\n")
        with self.assertRaisesRegex(preflight.PreflightError, "SHA-256 sidecar"):
            preflight.validate_artifact(self.package, None)
        (self.root / "candidate.deb.sha256").write_text("malformed\n")
        with self.assertRaisesRegex(preflight.PreflightError, "SHA-256 sidecar"):
            preflight.validate_artifact(self.package, None)

    def test_invalid_signed_package_metadata_is_rejected(self) -> None:
        self.members["usr/share/ioscaffeinate/SIGNING-STATE"] = (
            b"signature_state=UNSIGNED\nprofile_id=amethyst-ios12-rootful\n"
        )
        checksums = []
        for name, content in sorted(self.members.items()):
            if isinstance(content, bytes) and name != "usr/share/ioscaffeinate/SHA256SUMS":
                checksums.append(f"{hashlib.sha256(content).hexdigest()}  {name}")
        self.members["usr/share/ioscaffeinate/SHA256SUMS"] = ("\n".join(checksums) + "\n").encode()
        with self.assertRaisesRegex(preflight.PreflightError, "SIGNING-STATE does not match"):
            self.call_preflight()

    def test_missing_exact_signer_provenance_is_unverified(self) -> None:
        (self.root / "candidate.deb.P010-SIGNED-CANDIDATE-MANIFEST.json").unlink()
        result = self.call_preflight()
        self.assertEqual(result["decision"], "UNVERIFIED")
        self.assertEqual(result["signer_provenance"], "MISSING")
        self.assertIn("EXACT_P010_SIGNER_PROVENANCE_MISSING", result["blockers"])

    def test_not_ready_human_output_uses_shared_error_fields(self) -> None:
        output = io.StringIO()
        with patch.object(preflight, "validate_artifact",
                          side_effect=preflight.PreflightError("package SHA-256 mismatch")):
            with contextlib.redirect_stdout(output):
                result = preflight.main([str(self.package)])
        self.assertEqual(result, 1)
        fields = dict(line.split("=", 1) for line in output.getvalue().splitlines()
                      if "=" in line)
        self.assertEqual(fields["error.operation"], "package_upgrade_check")
        self.assertEqual(fields["error.code"], "INTEGRITY_FAILED")
        self.assertEqual(fields["changed"], "no")
        self.assertEqual(fields["cleanup"], "not_applicable")
        self.assertEqual(fields["next_safe_step"], "inspect_package_metadata_and_signer_provenance")

    def test_p010_ci_manifest_must_match_exact_job_contract_and_repo(self) -> None:
        manifest = self.root / "candidate.deb.P010-SIGNED-CANDIDATE-MANIFEST.json"
        candidate = json.loads(manifest.read_text())
        del candidate["ci"]["jobs"]["p009-evidence-validation"]
        manifest.write_text(json.dumps(candidate))
        result = self.call_preflight()
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertEqual(result["signer_provenance"], "INVALID")
        self.assertIn("P010_EXACT_SOURCE_CI_PROVENANCE_INVALID", result["blockers"])

    def test_unverified_host_signature_integrity_stays_unverified(self) -> None:
        manifest = self.root / "candidate.deb.P010-SIGNED-CANDIDATE-MANIFEST.json"
        candidate = json.loads(manifest.read_text())
        candidate["signing"]["signature_integrity"] = "PENDING"
        manifest.write_text(json.dumps(candidate))
        result = self.call_preflight()
        self.assertEqual(result["decision"], "UNVERIFIED")
        self.assertEqual(result["signer_provenance"], "UNVERIFIED")
        self.assertIn("HOST_SIGNATURE_INTEGRITY_NOT_VERIFIED", result["blockers"])

    def test_active_path_collision_blocks_review_readiness(self) -> None:
        result = self.call_preflight(collisions=("PACKAGE_PATH_COLLISION_UNOWNED",))
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertEqual(result["path_collisions"], "BLOCKED")

    def test_package_symlink_and_hardlink_inputs_are_rejected(self) -> None:
        alias = self.root / "alias.deb"
        alias.symlink_to(self.package)
        with self.assertRaises(OSError):
            preflight.read_regular(alias, 1024)
        hardlink = self.root / "other.deb"
        hardlink.hardlink_to(self.package)
        with self.assertRaisesRegex(preflight.PreflightError, "singly linked regular file"):
            preflight.read_regular(self.package, 1024)

    def test_untrusted_package_archive_traversal_and_links_are_rejected(self) -> None:
        class FakeProcess:
            def __init__(self, raw: bytes) -> None:
                self.stdout = io.BytesIO(raw)
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self) -> None:
                self.returncode = -15

            def wait(self, timeout=None):
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode

        def archive_bytes(entries) -> bytes:
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                for member in entries:
                    member.uid = member.gid = 0
                    archive.addfile(member, io.BytesIO(b"fixture") if member.isfile() else None)
            return stream.getvalue()

        traversing = tarfile.TarInfo("usr/share/doc/ioscaffeinate/../../etc/passwd")
        traversing.size = 7
        with patch.object(preflight.subprocess, "Popen",
                          side_effect=lambda *_args, **_kwargs: FakeProcess(archive_bytes([traversing]))):
            with self.assertRaisesRegex(preflight.PreflightError, "traversal"):
                preflight.stream_archive(self.package)

        hardlink = tarfile.TarInfo("usr/share/doc/ioscaffeinate/unexpected")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "usr/local/bin/ios-caffeinate"
        with patch.object(preflight.subprocess, "Popen",
                          side_effect=lambda *_args, **_kwargs: FakeProcess(archive_bytes([hardlink]))):
            with self.assertRaisesRegex(preflight.PreflightError, "hard link"):
                preflight.stream_archive(self.package)

        link = tarfile.TarInfo("usr/share/doc/ioscaffeinate/unexpected")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../etc/passwd"
        with patch.object(preflight.subprocess, "Popen",
                          side_effect=lambda *_args, **_kwargs: FakeProcess(archive_bytes([link]))):
            with self.assertRaisesRegex(preflight.PreflightError, "symbolic link"):
                preflight.stream_archive(self.package)

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is required for the archive snapshot test")
    def test_dpkg_deb_reads_only_the_private_file_descriptor_snapshot(self) -> None:
        package_tree = self.root / "real-package"
        control = package_tree / "DEBIAN"
        payload = package_tree / "usr/share/doc/ioscaffeinate"
        control.mkdir(parents=True)
        payload.mkdir(parents=True)
        control.chmod(0o755)
        payload.chmod(0o755)
        (control / "control").write_text(
            "Package: com.ioscaffeinate.cli\nVersion: 0.1.0-2\n"
            "Architecture: iphoneos-arm\nMaintainer: test fixture\nDescription: inert P018 fixture\n"
        )
        (payload / "fixture.txt").write_text("synthetic; never installed\n")
        deb = self.root / "fd-snapshot.deb"
        built = subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(package_tree), str(deb)],
                               capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(built.returncode, 0, built.stderr)
        raw = deb.read_bytes()
        with tempfile.TemporaryFile(prefix="ioscaf-p018-fd-test-") as snapshot:
            snapshot.write(raw)
            snapshot.flush()
            snapshot.seek(0)
            fd = snapshot.fileno()
            private_path = Path(f"/dev/fd/{fd}")
            self.assertEqual(preflight.dpkg_field(private_path, "Package", (fd,)),
                             "com.ioscaffeinate.cli")
            self.assertEqual(preflight.dpkg_field(private_path, "Architecture", (fd,)),
                             "iphoneos-arm")
            archive = preflight.stream_archive(private_path, (fd,))
            self.assertEqual(archive["usr/share/doc/ioscaffeinate/fixture.txt"],
                             b"synthetic; never installed\n")

    def test_portable_shell_manager_never_installs_or_mutates_launchd(self) -> None:
        manager = ROOT / "packaging/rootful/manager"
        syntax = subprocess.run(["sh", "-n", str(manager)], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        source = manager.read_text()
        for forbidden in (r"\bdpkg\s+-i\b", r"\bdpkg\s+--remove\b",
                          r"\blaunchctl\s+(?:load|bootstrap|enable|kickstart|start|restart)\b",
                          r"\bkill\s+-9\b", r"\brm\s+-rf\b"):
            self.assertNotRegex(source, forbidden)
        for invariant in ("NOT_REGISTERED", "UNKNOWN", "P014_RECOVERY_NOT_CONFIRMED_HEALTHY",
                          "operator_install_authorization=NOT_GRANTED", "persistent_data_preservation=REVIEW_REQUIRED"):
            self.assertIn(invariant, source)


if __name__ == "__main__":
    unittest.main()
