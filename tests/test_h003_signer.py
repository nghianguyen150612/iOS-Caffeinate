"""Offline negative-path tests for H003 signer provisioning and provenance."""

from __future__ import annotations

import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import h003_signer as signer  # noqa: E402


def elf64_pie_fixture() -> bytes:
    interpreter = b"/lib64/ld-linux-x86-64.so.2\x00"
    program_header_offset = 64
    interpreter_offset = program_header_offset + 56
    raw = bytearray(interpreter_offset + len(interpreter))
    raw[:16] = b"\x7fELF\x02\x01\x01" + b"\x00" * 9
    struct.pack_into(
        "<HHIQQQIHHHHHH",
        raw,
        16,
        3,
        62,
        1,
        0,
        program_header_offset,
        0,
        0,
        64,
        56,
        1,
        64,
        0,
        0,
    )
    struct.pack_into(
        "<IIQQQQQQ",
        raw,
        program_header_offset,
        3,
        4,
        interpreter_offset,
        0,
        0,
        len(interpreter),
        len(interpreter),
        1,
    )
    raw[interpreter_offset:] = interpreter
    return bytes(raw)


class H003SignerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = signer.load_lock()
        self.temporary = tempfile.TemporaryDirectory(prefix="ioscaffeinate-h003-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_executable(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.write_bytes(payload)
        path.chmod(0o700)
        return path

    def valid_build_fields(self) -> dict[str, str]:
        values = {
            "source_url": self.lock["H003_SOURCE_URL"],
            "source_commit_1": self.lock["H003_SOURCE_COMMIT"],
            "source_tree_1": self.lock["H003_SOURCE_TREE"],
            "source_commit_2": self.lock["H003_SOURCE_COMMIT"],
            "source_tree_2": self.lock["H003_SOURCE_TREE"],
            "container_image": self.lock["H003_CONTAINER_IMAGE"],
            "container_platform": self.lock["H003_PLATFORM"],
            "ubuntu_id": "ubuntu",
            "ubuntu_version": "24.04",
            "apt_snapshot": self.lock["H003_APT_SNAPSHOT"],
            "apt_signature_verification": "VERIFIED_BY_APT",
            "apt_source_origin": self.lock["H003_APT_SNAPSHOT"],
            "gcc_version": self.lock["H003_GCC_VERSION"],
            "gxx_version": self.lock["H003_GCC_VERSION"],
            "binutils_version": self.lock["H003_BINUTILS_VERSION"],
            "make_version": self.lock["H003_MAKE_VERSION"],
            "libplist_version": self.lock["H003_LIBPLIST_VERSION"],
            "openssl_version": self.lock["H003_OPENSSL_VERSION"],
            "build_1_sha256": self.lock["H003_SIGNER_SHA256"],
            "build_2_sha256": self.lock["H003_SIGNER_SHA256"],
            "executable_sha256": self.lock["H003_SIGNER_SHA256"],
            "version_banner": f"Link Identity Editor {self.lock['H003_SIGNER_VERSION']}",
            "binary_architecture": "x86_64",
            "binary_elf_class": "ELF64",
            "binary_type": "ELF64-PIE",
            "binary_interpreter": "/lib64/ld-linux-x86-64.so.2",
            "result": "VERIFIED",
        }
        values.update({f"package.{name}": self.lock[key] for name, key in signer.PACKAGE_LOCK_KEYS.items()})
        return values

    def test_exact_signer_hash_and_version_are_accepted(self) -> None:
        binary = self.write_executable("ldid", elf64_pie_fixture())
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        version_reader = Mock(return_value="Link Identity Editor 2.1.5-procursus7")
        result = signer.verify_binary_identity(binary, digest, "2.1.5-procursus7", version_reader)
        self.assertEqual(result["sha256"], digest)
        self.assertEqual(result["architecture"], "x86_64")
        version_reader.assert_called_once_with(binary)

    def test_host_artifact_verification_does_not_execute_dynamic_signer(self) -> None:
        binary = self.write_executable("ldid", elf64_pie_fixture())
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        with patch.object(signer.subprocess, "run", side_effect=AssertionError("must not execute on host")):
            result = signer.verify_binary_artifact(binary, digest)
        self.assertEqual(result["sha256"], digest)
        self.assertEqual(result["architecture"], "x86_64")

    def test_version_banner_is_found_after_usage_lines(self) -> None:
        binary = self.write_executable("ldid", elf64_pie_fixture())
        result = Mock(
            stdout="Usage: ldid [options] binary",
            stderr="\x1b[1mLink Identity Editor 2.1.5-procursus7\x1b[0m\n",
        )
        with patch.object(signer.subprocess, "run", return_value=result) as run:
            banner = signer.read_version_banner(binary)
        self.assertEqual(banner, "Link Identity Editor 2.1.5-procursus7")
        run.assert_called_once()

    def test_hash_mismatch_aborts_before_executing_signer(self) -> None:
        binary = self.write_executable("ldid", elf64_pie_fixture())
        version_reader = Mock(return_value="Link Identity Editor 2.1.5-procursus7")
        with self.assertRaisesRegex(signer.H003Error, "SIGNER_REPRODUCTION_MISMATCH"):
            signer.verify_binary_identity(binary, "0" * 64, "2.1.5-procursus7", version_reader)
        version_reader.assert_not_called()

    def test_wrong_signer_version_is_rejected_after_hash_match(self) -> None:
        binary = self.write_executable("ldid", elf64_pie_fixture())
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        with self.assertRaisesRegex(signer.H003Error, "wrong signer version"):
            signer.verify_binary_identity(binary, digest, "2.1.5-procursus7", lambda _: "Link Identity Editor 2.1.5")

    def test_wrong_source_commit_is_rejected(self) -> None:
        with self.assertRaisesRegex(signer.H003Error, "wrong source commit"):
            signer.validate_source_identity("0" * 40, self.lock["H003_SOURCE_TREE"], self.lock)

    def test_corrupt_source_tree_is_rejected(self) -> None:
        with self.assertRaisesRegex(signer.H003Error, "corrupt build input"):
            signer.validate_source_identity(self.lock["H003_SOURCE_COMMIT"], "0" * 40, self.lock)

    def test_unavailable_exact_source_fetch_is_rejected(self) -> None:
        with self.assertRaisesRegex(signer.H003Error, "SOURCE_ARCHIVE_UNAVAILABLE"):
            signer.require_source_fetch_success(128)

    def test_wrong_host_architecture_is_rejected(self) -> None:
        with self.assertRaisesRegex(signer.H003Error, "WRONG_HOST_ARCHITECTURE"):
            signer.require_host_architecture("aarch64")

    def test_missing_signer_executable_is_rejected(self) -> None:
        with self.assertRaisesRegex(signer.H003Error, "missing or unsafe"):
            signer.inspect_elf(self.root / "missing-ldid")

    def test_corrupt_binary_is_rejected_before_version_check(self) -> None:
        binary = self.write_executable("corrupt-ldid", b"not an ELF executable")
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        version_reader = Mock(return_value="Link Identity Editor 2.1.5-procursus7")
        with self.assertRaisesRegex(signer.H003Error, "not an ELF executable"):
            signer.verify_binary_identity(binary, digest, "2.1.5-procursus7", version_reader)
        version_reader.assert_not_called()

    def test_dependency_version_and_origin_mismatches_fail_closed(self) -> None:
        fields = self.valid_build_fields()
        fields["package.gcc-13"] = "13.2.0"
        with self.assertRaisesRegex(signer.H003Error, "dependency version mismatch"):
            signer.validate_build_fields(fields, self.lock)
        fields = self.valid_build_fields()
        fields["apt_source_origin"] = "https://archive.ubuntu.com/ubuntu"
        with self.assertRaisesRegex(signer.H003Error, "apt_source_origin"):
            signer.validate_build_fields(fields, self.lock)

    def test_independent_build_hash_mismatch_is_rejected(self) -> None:
        fields = self.valid_build_fields()
        fields["build_2_sha256"] = "0" * 64
        with self.assertRaisesRegex(signer.H003Error, "SIGNER_REPRODUCTION_MISMATCH"):
            signer.validate_build_fields(fields, self.lock)

    def test_build_receipt_records_exact_source_and_environment(self) -> None:
        fields = self.valid_build_fields()
        signer.validate_build_fields(fields, self.lock)
        report = signer.make_provenance(fields)
        self.assertEqual(report["result"], "VERIFIED")
        self.assertEqual(report["source"]["commit"], self.lock["H003_SOURCE_COMMIT"])
        self.assertEqual(report["reproducibility"]["outcome"], "EXACT_MATCH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
