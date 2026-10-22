#!/usr/bin/env python3
"""Deterministic, unprivileged regression tests for rootful package tooling."""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from macho_ios import validate_ios12_arm64  # noqa: E402
from validate_rootful_package import (  # noqa: E402
    check_sha_manifest,
    check_script_safety,
    inspect_package,
    normalized_member_path,
    validate_archive_members,
)


def macho_fixture(
    *,
    cpu_type: int = 0x0100000C,
    subtype: int = 0,
    min_os: int = 12 << 16,
    signed: bool = False,
    dependencies: tuple[str, ...] = ("/usr/lib/libSystem.B.dylib",),
) -> bytes:
    commands = [
        struct.pack("<IIIIII", 0x32, 24, 2, min_os, 12 << 16, 0),
        struct.pack("<II16sQQQQiiII", 0x19, 72, b"__LINKEDIT", 0x100000, 0, 0, 0, 7, 1, 0, 0),
    ]
    for dependency in dependencies:
        encoded = dependency.encode("utf-8") + b"\x00"
        size = (24 + len(encoded) + 7) & ~7
        commands.append(struct.pack("<IIIIII", 0x0C, size, 24, 0, 0, 0) + encoded + b"\x00" * (size - 24 - len(encoded)))
    if signed:
        commands.append(struct.pack("<IIII", 0x1D, 16, 32 + sum(map(len, commands)) + 16, 16))
    header = struct.pack(
        "<IiiIIIII",
        0xFEEDFACF,
        cpu_type,
        subtype,
        2,
        len(commands),
        sum(len(command) for command in commands),
        0,
        0,
    )
    result = bytearray(header + b"".join(commands) + b"\x00" * 64 + (b"X" * 16 if signed else b""))
    segment_offset = 32 + 24
    struct.pack_into("<Q", result, segment_offset + 32, len(result))
    struct.pack_into("<Q", result, segment_offset + 48, len(result))
    return bytes(result)


def write_source_inputs(
    path: Path,
    *,
    cpu_type: int = 0x0100000C,
    subtype: int = 0,
    min_os: int = 12 << 16,
    signed: bool = False,
    extra_dependencies: tuple[str, ...] = (),
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    records = []
    for name in ("ios-caffeinate", "ios-caffeinated"):
        dependencies = (
            "/usr/lib/libSystem.B.dylib",
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
        )
        dependencies += extra_dependencies
        executable = path / name
        executable.write_bytes(macho_fixture(cpu_type=cpu_type, subtype=subtype, min_os=min_os, signed=signed, dependencies=dependencies))
        executable.chmod(0o755)
        records.append(f"{hashlib.sha256(executable.read_bytes()).hexdigest()}  {name}")
    (path / "SHA256SUMS").write_text("\n".join(records) + "\n")


class RootfulPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("dpkg-deb"):
            raise unittest.SkipTest("dpkg-deb is required for package integration tests")
        cls.temp = tempfile.TemporaryDirectory(prefix="ioscaffeinate-package-tests-")
        cls.work = Path(cls.temp.name)
        cls.inputs = cls.work / "input"
        cls.output = cls.work / "output"
        write_source_inputs(cls.inputs)
        result = subprocess.run(
            [
                str(ROOT / "scripts/package-rootful.sh"),
                "--input-dir", str(cls.inputs),
                "--output-dir", str(cls.output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise AssertionError(f"fixture package build failed:\n{result.stdout}\n{result.stderr}")
        cls.deb = next(cls.output.glob("*.deb"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_builder(
        self,
        input_dir: Path,
        output_dir: Path | None = None,
        package_version: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            str(ROOT / "scripts/package-rootful.sh"),
            "--input-dir", str(input_dir),
            "--output-dir", str(output_dir or self.work / "reject-output"),
        ]
        if package_version is not None:
            command.extend(("--package-version", package_version))
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_package_name_version_architecture_and_hash(self) -> None:
        output = inspect_package(self.deb)
        self.assertIn("package=com.ioscaffeinate.cli", output)
        self.assertIn("version=0.1.0-1", output)
        self.assertIn("architecture=iphoneos-arm", output)
        self.assertIn("result=PASS", output)

    def test_package_build_is_reproducible(self) -> None:
        second_output = self.work / "second-output"
        result = self.run_builder(self.inputs, second_output)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        second_deb = next(second_output.glob("*.deb"))
        self.assertEqual(hashlib.sha256(self.deb.read_bytes()).digest(), hashlib.sha256(second_deb.read_bytes()).digest())

    def test_prerelease_version_override_is_validated_and_preserved(self) -> None:
        candidate_output = self.work / "candidate-output"
        result = self.run_builder(self.inputs, candidate_output, "0.2.0~rc1-1")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        candidate = next(candidate_output.glob("*.deb"))
        self.assertEqual(candidate.name, "ioscaffeinate_0.2.0~rc1-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb")
        report = inspect_package(candidate, expected_version="0.2.0~rc1-1")
        self.assertIn("version=0.2.0~rc1-1", report)

        # A complete current candidate passes. Dropping even one regular-file
        # record still fails the strict validator for a v0.2 candidate.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["dpkg-deb", "--extract", str(candidate), str(root)], check=True)
            sums_path = root / "usr/share/ioscaffeinate/SHA256SUMS"
            records = sums_path.read_text().splitlines()
            self.assertGreater(len(records), 1)
            sums_path.write_text("\n".join(records[:-1]) + "\n")
            with self.assertRaisesRegex(ValueError, "cover the approved payload"):
                check_sha_manifest(root)

    def test_canonical_cli_daemon_and_real_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["dpkg-deb", "--extract", str(self.deb), str(root)], check=True)
            self.assertTrue((root / "usr/local/bin/ios-caffeinate").is_file())
            self.assertTrue((root / "usr/local/bin/ios-caffeinated").is_file())
            alias = root / "usr/local/bin/ic"
            self.assertTrue(alias.is_symlink())
            self.assertEqual(os.readlink(alias), "ios-caffeinate")
            self.assertEqual((root / "usr/local/bin/ios-caffeinate").stat().st_mode & 0o777, 0o755)
            self.assertEqual((root / "usr/local/bin/ios-caffeinated").stat().st_mode & 0o777, 0o755)

    def test_macho_architecture_and_minimum_target(self) -> None:
        info = validate_ios12_arm64(
            self.inputs / "ios-caffeinate",
            allow_signature=False,
            expected_dependencies={
                "/usr/lib/libSystem.B.dylib",
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
            },
        )
        self.assertEqual(info.architecture, "arm64")
        self.assertEqual(info.platform, "iOS")
        self.assertEqual(info.minimum_os, (12, 0, 0))

    def test_missing_input_artifacts_fail_closed(self) -> None:
        empty = self.work / "empty"
        empty.mkdir()
        result = self.run_builder(empty)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA256SUMS", result.stderr)

    def test_output_directory_symlink_is_rejected(self) -> None:
        target = self.work / "output-target"
        target.mkdir()
        output_link = self.work / "output-link"
        output_link.symlink_to(target, target_is_directory=True)
        result = self.run_builder(self.inputs, output_link)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(target.iterdir()), [])

    def test_existing_package_artifact_is_not_overwritten(self) -> None:
        output = self.work / "preexisting-output"
        output.mkdir()
        name = "ioscaffeinate_0.1.0-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb"
        artifact = output / name
        artifact.write_bytes(b"keep existing file")
        result = self.run_builder(self.inputs, output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertEqual(artifact.read_bytes(), b"keep existing file")

    def test_mismatched_input_checksum_is_rejected(self) -> None:
        bad = self.work / "bad-hash"
        shutil.copytree(self.inputs, bad)
        (bad / "SHA256SUMS").write_text("0" * 64 + "  ios-caffeinate\n" + (bad / "SHA256SUMS").read_text().splitlines()[1] + "\n")
        result = self.run_builder(bad)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)

    def test_wrong_cpu_architecture_is_rejected(self) -> None:
        wrong = self.work / "wrong-arch"
        write_source_inputs(wrong, cpu_type=0x01000007)
        result = self.run_builder(wrong)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wrong Mach-O CPU type", result.stderr)

    def test_unexpected_dynamic_dependency_is_rejected(self) -> None:
        unexpected = self.work / "unexpected-dependency"
        write_source_inputs(unexpected, extra_dependencies=("/usr/lib/libunexpected.dylib",))
        result = self.run_builder(unexpected)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected dynamic dependencies", result.stderr)

    def test_arm64e_only_input_is_rejected(self) -> None:
        arm64e = self.work / "arm64e"
        write_source_inputs(arm64e, subtype=2)
        result = self.run_builder(arm64e)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("arm64e-only", result.stderr)

    def test_target_above_ios_12_is_rejected(self) -> None:
        newer = self.work / "ios13"
        write_source_inputs(newer, min_os=13 << 16)
        result = self.run_builder(newer)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("above 12.0", result.stderr)

    def test_signature_without_signing_evidence_is_rejected(self) -> None:
        signed = self.work / "signed-input"
        write_source_inputs(signed, signed=True)
        result = self.run_builder(signed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("code signature must be absent", result.stderr)

    def test_duplicate_installed_paths_are_rejected(self) -> None:
        one = tarfile.TarInfo("./usr/local/bin/ios-caffeinate")
        one.type = tarfile.REGTYPE
        two = tarfile.TarInfo("usr/local/bin/ios-caffeinate")
        two.type = tarfile.REGTYPE
        with self.assertRaisesRegex(ValueError, "duplicate installed path"):
            validate_archive_members([one, two])

    def test_absolute_and_traversal_paths_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute archive path"):
            normalized_member_path("/usr/bin/evil")
        with self.assertRaisesRegex(ValueError, "traversal archive path"):
            normalized_member_path("usr/share/../../etc/evil")

    def test_only_the_cli_alias_symlink_is_allowed(self) -> None:
        link = tarfile.TarInfo("usr/local/bin/other")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../etc/launchd.conf"
        with self.assertRaisesRegex(ValueError, "unexpected package symlink"):
            validate_archive_members([link])

    def test_launchd_is_staged_disabled_and_no_state_is_seeded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["dpkg-deb", "--extract", str(self.deb), str(root)], check=True)
            plist = (root / "usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist").read_text()
            self.assertIn("<key>Disabled</key><true/>", plist)
            self.assertIn("<key>RunAtLoad</key><false/>", plist)
            self.assertFalse((root / "Library/LaunchDaemons/com.ioscaffeinate.daemon.plist").exists())
            state_dir = root / "var/lib/ioscaffeinate"
            self.assertTrue(state_dir.is_dir())
            self.assertEqual(list(state_dir.iterdir()), [])
            self.assertFalse((state_dir / "schedules.json").exists())
            self.assertFalse((state_dir / "server-mode.json").exists())

    def test_data_and_logs_survive_simulated_ordinary_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["dpkg-deb", "--extract", str(self.deb), str(root)], check=True)
            schedules = root / "var/lib/ioscaffeinate/schedules.json"
            server_mode = root / "var/lib/ioscaffeinate/server-mode.json"
            evidence = root / "var/lib/ioscaffeinate/evidence.txt"
            log = root / "var/log/ioscaffeinate/operator.log"
            for path in (schedules, server_mode, evidence, log):
                path.write_text("operator state\n")

            raw = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(self.deb)], check=True, capture_output=True).stdout
            with tarfile.open(fileobj=__import__("io").BytesIO(raw), mode="r:*") as archive:
                for member in archive.getmembers():
                    relative = normalized_member_path(member.name)
                    if relative == ".":
                        continue
                    target = root / relative
                    if member.isfile() or member.issym():
                        if target.is_symlink() or target.is_file():
                            target.unlink()
                    elif member.isdir() and target.is_dir() and not target.is_symlink():
                        try:
                            target.rmdir()
                        except OSError:
                            pass
            for path in (schedules, server_mode, evidence, log):
                self.assertEqual(path.read_text(), "operator state\n")

    def test_maintainer_scripts_are_syntax_checked_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            control = Path(temporary)
            subprocess.run(["dpkg-deb", "--control", str(self.deb), str(control)], check=True)
            self.assertEqual({p.name for p in control.iterdir() if p.name in ("preinst", "prerm")}, {"preinst", "prerm"})
            for name in ("preinst", "prerm"):
                check_script_safety(control / name)
                script = (control / name).read_text()
                self.assertNotIn("dpkg -i", script)
                self.assertNotIn("launchctl ", script)
                self.assertNotRegex(script, r"(?m)^\s*rm(?:\s|$)")

            # Repeated preinst calls fail at the same architecture gate under
            # a controlled fake dpkg. The removal guard performs read-only
            # endpoint/service observations and blocks unknown state. Neither
            # script writes to the host filesystem.
            fake_bin = Path(temporary) / "fake-bin"
            fake_bin.mkdir()
            fake_dpkg = fake_bin / "dpkg"
            fake_dpkg.write_text("#!/bin/sh\nprintf '%s\\n' arm64\n")
            fake_dpkg.chmod(0o755)
            preinst = control / "preinst"
            fake_path = f"{fake_bin}:/bin:/usr/bin"
            runs = [
                subprocess.run(["sh", str(preinst), "install"], env={**os.environ, "PATH": fake_path}, text=True, capture_output=True)
                for _ in range(2)
            ]
            self.assertEqual((runs[0].returncode, runs[0].stdout, runs[0].stderr), (runs[1].returncode, runs[1].stdout, runs[1].stderr))
            prerm_runs = [
                subprocess.run(["sh", str(control / "prerm"), "remove"], text=True, capture_output=True)
                for _ in range(2)
            ]
            self.assertEqual(
                (prerm_runs[0].returncode, prerm_runs[0].stdout, prerm_runs[0].stderr),
                (prerm_runs[1].returncode, prerm_runs[1].stdout, prerm_runs[1].stderr),
            )

    def test_manager_defaults_are_read_only_and_rollback_check_requires_artifact(self) -> None:
        manager = ROOT / "packaging/rootful/manager"
        subprocess.run(["sh", "-n", str(manager)], check=True)
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(["sh", str(manager), "rollback-check"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("matching .sha256 sidecar", result.stderr)
        text = manager.read_text()
        self.assertNotIn("dpkg -i", text)
        self.assertNotIn("launchctl load", text)

    def test_package_has_no_automatic_install_or_service_activation(self) -> None:
        output = inspect_package(self.deb)
        self.assertIn("package_installation=NOT-PERFORMED", output)
        self.assertIn("device_validation=UNVERIFIED", output)
        self.assertNotIn("/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist", output)
        builder = (ROOT / "scripts/package_rootful.py").read_text()
        self.assertNotIn('["dpkg", "-i"', builder)
        self.assertNotIn("launchctl load", builder)


if __name__ == "__main__":
    unittest.main(verbosity=2)
