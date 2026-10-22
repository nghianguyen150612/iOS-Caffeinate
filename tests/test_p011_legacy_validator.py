"""Offline H002 regressions for the bounded v0.1.0 compatibility path."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
import struct
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import p011_legacy_package_validator as legacy  # noqa: E402
import p011_release_preflight as p011  # noqa: E402
import signing_profile as signing_profile_module  # noqa: E402
from validate_rootful_package import REQUIRED_HASHES, check_sha_manifest  # noqa: E402
from macho_ios import validate_ios12_arm64  # noqa: E402


def make_offline_layout_fixture() -> tuple[dict[str, object], list[tarfile.TarInfo], dict[str, bytes]]:
    """Build a structural fixture; it is never labeled as a published artifact."""
    inventory = copy.deepcopy(legacy.load_derived_inventory())
    inventory["inventory_kind"] = "SYNTHETIC_OFFLINE_TEST_FIXTURE"
    inventory["source"]["package_sha256"] = "0" * 64
    data: dict[str, bytes] = {}
    for item in inventory["members"]:
        if item["type"] == "regular" and item["path"] != legacy.EMBEDDED_CHECKSUM_PATH:
            data[item["path"]] = f"synthetic H002 fixture content: {item['path']}\n".encode()
    sums = "".join(
        f"{hashlib.sha256(data[path]).hexdigest()}  {path}\n"
        for path in legacy.HISTORICAL_CHECKSUM_PATHS
    ).encode()
    data[legacy.EMBEDDED_CHECKSUM_PATH] = sums
    for item in inventory["members"]:
        path = item["path"]
        kind = item["type"]
        if kind == "regular":
            contents = data[path]
            item["size"] = len(contents)
            item["derived_sha256"] = hashlib.sha256(contents).hexdigest()
    members = []
    for item in inventory["members"]:
        path = item["path"]
        kind = item["type"]
        name = "." if path == "." else "./" + path + ("/" if kind == "directory" else "")
        member = tarfile.TarInfo(name)
        member.uid = item["uid"]
        member.gid = item["gid"]
        member.mode = item["mode"]
        if kind == "directory":
            member.type = tarfile.DIRTYPE
        elif kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = item["link_target"]
        else:
            member.type = tarfile.REGTYPE
            member.size = len(data[path])
        members.append(member)
    return inventory, members, data


def read_fixture_member(member: tarfile.TarInfo, data: dict[str, bytes]) -> bytes:
    return data[legacy.normalized_member_path(member.name)]


def serialize_control(fields: dict[str, str]) -> bytes:
    lines = []
    for name, value in fields.items():
        parts = value.split("\n")
        lines.append(f"{name}: {parts[0]}")
        lines.extend(" " + part for part in parts[1:])
    return ("\n".join(lines) + "\n").encode()


def unsigned_ios12_macho(dependencies: tuple[str, ...]) -> bytes:
    commands = [
        struct.pack("<IIIIII", 0x32, 24, 2, 12 << 16, 12 << 16, 0),
        struct.pack("<II16sQQQQiiII", 0x19, 72, b"__LINKEDIT", 0x100000, 0, 0, 0, 7, 1, 0, 0),
    ]
    for dependency in dependencies:
        encoded = dependency.encode("utf-8") + b"\x00"
        size = (24 + len(encoded) + 7) & ~7
        commands.append(struct.pack("<IIIIII", 0x0C, size, 24, 0, 0, 0) + encoded + b"\x00" * (size - 24 - len(encoded)))
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, len(commands), sum(map(len, commands)), 0, 0)
    result = bytearray(header + b"".join(commands) + b"\x00" * 64)
    segment_offset = 32 + 24
    struct.pack_into("<Q", result, segment_offset + 32, len(result))
    struct.pack_into("<Q", result, segment_offset + 48, len(result))
    return bytes(result)


def package_build_fixture() -> dict[str, object]:
    return {
        "architecture": legacy.ARCHITECTURE,
        "package_identifier": legacy.PACKAGE_ID,
        "package_version": legacy.PACKAGE_VERSION,
        "schema_version": 1,
        "source_commit_sha": legacy.SOURCE_COMMIT,
        "source_tree_clean": True,
        "signing": copy.deepcopy(legacy.EXPECTED_SIGNING),
    }


class P011LegacyValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory, self.members, self.data = make_offline_layout_fixture()

    def validate_fixture_members(self, members: list[tarfile.TarInfo] | None = None, data: dict[str, bytes] | None = None):
        selected_members = self.members if members is None else members
        selected_data = self.data if data is None else data
        return legacy.validate_member_table(selected_members, self.inventory, lambda member: read_fixture_member(member, selected_data))

    def test_offline_historical_layout_fixture_passes_structural_contract(self) -> None:
        entries, data = self.validate_fixture_members()
        self.assertEqual(len(entries), 81)
        records, uncovered = legacy.validate_historical_checksum_records(
            data[legacy.EMBEDDED_CHECKSUM_PATH], data, self.inventory
        )
        self.assertEqual(len(records), 7)
        self.assertEqual(len(uncovered), 52)
        # The fixture exercises the compatibility rules only. It does not
        # produce an official-artifact identity or validation PASS.
        self.assertEqual(self.inventory["inventory_kind"], "SYNTHETIC_OFFLINE_TEST_FIXTURE")
        self.assertEqual(self.inventory["source"]["package_sha256"], "0" * 64)

    def test_altered_historical_archive_hash_is_rejected_before_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / legacy.PACKAGE_FILENAME
            path.write_bytes(b"changed" * (legacy.PACKAGE_SIZE // 7) + b"x")
            path.write_bytes(path.read_bytes()[:legacy.PACKAGE_SIZE].ljust(legacy.PACKAGE_SIZE, b"x"))
            with self.assertRaisesRegex(legacy.LegacyValidationError, "SHA-256 differs"):
                legacy.verify_official_archive_identity(path)

    def test_unrelated_010_package_never_uses_legacy_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ioscaffeinate_0.1.0-2_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb"
            path.write_bytes(b"x" * legacy.PACKAGE_SIZE)
            with self.assertRaisesRegex(legacy.LegacyValidationError, "exact published v0.1.0 filename"):
                legacy.verify_official_archive_identity(path)

    def test_wrong_debian_version_is_rejected(self) -> None:
        fields = dict(legacy.CONTROL_FIELDS)
        fields["Version"] = "0.1.0-2"
        with self.assertRaisesRegex(legacy.LegacyValidationError, "Version"):
            legacy.parse_debian_control(serialize_control(fields))

    def test_wrong_debian_architecture_is_rejected(self) -> None:
        fields = dict(legacy.CONTROL_FIELDS)
        fields["Architecture"] = "arm64"
        with self.assertRaisesRegex(legacy.LegacyValidationError, "Architecture"):
            legacy.parse_debian_control(serialize_control(fields))

    def test_unexpected_payload_member_is_rejected(self) -> None:
        extra = tarfile.TarInfo("./usr/share/ioscaffeinate/unexpected")
        extra.uid = extra.gid = 0
        extra.mode = 0o644
        extra.size = 0
        with self.assertRaisesRegex(legacy.LegacyValidationError, "unexpected package member"):
            self.validate_fixture_members([*self.members, extra])

    def test_missing_historical_required_file_is_rejected(self) -> None:
        members = [member for member in self.members if legacy.normalized_member_path(member.name) != legacy.CLI_PATH]
        with self.assertRaisesRegex(legacy.LegacyValidationError, "missing required member"):
            self.validate_fixture_members(members)

    def test_modified_covered_file_is_rejected(self) -> None:
        data = dict(self.data)
        data[legacy.CLI_PATH] += b"tampered"
        with self.assertRaisesRegex(legacy.LegacyValidationError, "checksum mismatch"):
            legacy.validate_historical_checksum_records(self.data[legacy.EMBEDDED_CHECKSUM_PATH], data, self.inventory)

    def test_duplicate_historical_checksum_record_is_rejected(self) -> None:
        lines = self.data[legacy.EMBEDDED_CHECKSUM_PATH].decode().splitlines()
        lines[-1] = lines[0]
        raw = ("\n".join(lines) + "\n").encode()
        with self.assertRaisesRegex(legacy.LegacyValidationError, "duplicate historical checksum"):
            legacy.validate_historical_checksum_records(raw, self.data, self.inventory)

    def test_invalid_historical_checksum_syntax_is_rejected(self) -> None:
        lines = self.data[legacy.EMBEDDED_CHECKSUM_PATH].decode().splitlines()
        lines[0] = lines[0].replace("  ", " ", 1)
        with self.assertRaisesRegex(legacy.LegacyValidationError, "invalid historical checksum"):
            legacy.validate_historical_checksum_records(("\n".join(lines) + "\n").encode(), self.data, self.inventory)

    def test_missing_external_sidecar_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(legacy.LegacyValidationError, "missing or unsafe"):
                legacy.verify_published_asset(Path(temporary), f"{legacy.PACKAGE_FILENAME}.sha256")

    def test_modified_signing_metadata_is_rejected(self) -> None:
        build = package_build_fixture()
        build["signing"]["embedded_entitlements"] = "NOT_CHECKED"
        with self.assertRaisesRegex(legacy.LegacyValidationError, "published P010 identity"):
            legacy.validate_package_build_metadata(build)

    def test_wrong_pinned_signer_sha_is_rejected(self) -> None:
        with self.assertRaisesRegex(legacy.LegacyValidationError, "SHA-256 mismatch"):
            legacy.validate_pinned_signer_identity(legacy.SIGNER_VERSION, "0" * 64)

    def test_wrong_pinned_signer_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(legacy.LegacyValidationError, "version mismatch"):
            legacy.validate_pinned_signer_identity("2.1.5", legacy.SIGNER_SHA256)

    def test_pinned_signer_version_banner_accepts_terminal_formatting_after_hash_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            signer = Path(temporary) / "ldid"
            signer.write_bytes(b"verified test fixture")
            signer.chmod(0o700)
            expected_digest = hashlib.sha256(signer.read_bytes()).hexdigest()
            output = Mock(stdout="Usage: ldid", stderr="\x1b[1mLink Identity Editor 2.1.5-procursus7\x1b[0m\n")
            with patch.object(signing_profile_module.subprocess, "run", return_value=output) as run:
                version, digest = legacy.signer_identity(signer, expected_sha256=expected_digest)
            self.assertEqual(version, "2.1.5-procursus7")
            self.assertEqual(digest, expected_digest)
            run.assert_called_once()

    def test_missing_cli_signature_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "ios-caffeinate"
            binary.write_bytes(unsigned_ios12_macho(("/usr/lib/libSystem.B.dylib",)))
            with self.assertRaisesRegex(ValueError, "code signature must be present"):
                validate_ios12_arm64(binary, allow_signature=True, expected_dependencies=legacy.HISTORICAL_DEPENDENCIES[legacy.CLI_PATH])

    def test_missing_daemon_signature_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "ios-caffeinated"
            binary.write_bytes(unsigned_ios12_macho((
                "/usr/lib/libSystem.B.dylib",
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
            )))
            with self.assertRaisesRegex(ValueError, "code signature must be present"):
                validate_ios12_arm64(binary, allow_signature=True, expected_dependencies=legacy.HISTORICAL_DEPENDENCIES[legacy.DAEMON_PATH])

    def test_exact_entitlement_profile_is_accepted(self) -> None:
        profile = (ROOT / "packaging/signing/profiles/amethyst-ios12-rootful.plist").read_bytes()
        self.assertEqual(legacy.validate_embedded_profile(profile), {"com.apple.private.security.no-container": True})

    def test_incorrect_or_unexpected_embedded_entitlement_is_rejected(self) -> None:
        import plistlib

        wrong = plistlib.dumps({
            "com.apple.private.security.no-container": True,
            "com.apple.private.security.cs.allow-jit": True,
        })
        with self.assertRaisesRegex(legacy.LegacyValidationError, "entitlement profile is unexpected"):
            legacy.validate_embedded_profile(wrong)

    def test_unsafe_symlink_is_rejected(self) -> None:
        members = copy.copy(self.members)
        link = next(member for member in members if legacy.normalized_member_path(member.name) == "usr/local/bin/ic")
        link.linkname = "../../etc/passwd"
        with self.assertRaisesRegex(legacy.LegacyValidationError, "unsafe or unexpected package symlink"):
            self.validate_fixture_members(members)

    def test_unexpected_hardlink_and_special_file_are_rejected(self) -> None:
        for tar_type, label in ((tarfile.LNKTYPE, "hardlink"), (tarfile.FIFOTYPE, "special")):
            with self.subTest(label=label):
                members = copy.copy(self.members)
                changed = next(member for member in members if legacy.normalized_member_path(member.name) == legacy.CLI_PATH)
                changed.type = tar_type
                with self.assertRaisesRegex(legacy.LegacyValidationError, "unsupported hardlink or special"):
                    self.validate_fixture_members(members)

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaisesRegex(legacy.LegacyValidationError, "path traversal"):
            legacy.normalized_member_path("./usr/share/../../etc/passwd")

    def test_malicious_maintainer_script_is_rejected_without_execution(self) -> None:
        with self.assertRaisesRegex(legacy.LegacyValidationError, "unsafe maintainer script command"):
            legacy.validate_script_text("preinst", b"#!/bin/sh\nrm -rf /\n")

    def test_duplicate_package_paths_are_rejected(self) -> None:
        with self.assertRaisesRegex(legacy.LegacyValidationError, "duplicate package member path"):
            self.validate_fixture_members([*self.members, self.members[1]])

    def test_missing_and_corrupt_package_build_metadata_are_rejected(self) -> None:
        with self.assertRaisesRegex(legacy.LegacyValidationError, "not valid UTF-8 JSON"):
            legacy.parse_json(b"{not json", "embedded package build metadata")
        build = package_build_fixture()
        build.pop("source_commit_sha")
        with self.assertRaisesRegex(legacy.LegacyValidationError, "missing or unexpected fields"):
            legacy.validate_package_build_metadata(build)

    def test_legacy_contract_never_claims_full_historical_coverage(self) -> None:
        inventory = legacy.load_derived_inventory()
        self.assertEqual(inventory["inventory_kind"], "DERIVED_AFTER_PUBLICATION")
        self.assertEqual(inventory["historical_checksum_manifest"]["full_payload_manifest"], "NOT_PRESENT_IN_HISTORICAL_RELEASE")
        self.assertEqual(len(legacy.HISTORICAL_CHECKSUM_PATHS), 7)
        self.assertEqual(inventory["counts"]["uncovered_regular_members_including_checksum_manifest"], 52)

    def test_current_full_regular_file_coverage_remains_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = []
            for path in sorted(REQUIRED_HASHES):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(("current strict candidate " + path).encode())
                records.append(f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {path}")
            extra = root / "usr/share/ioscaffeinate/another-payload"
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(b"extra payload")
            records.append(f"{hashlib.sha256(extra.read_bytes()).hexdigest()}  usr/share/ioscaffeinate/another-payload")
            manifest = root / "usr/share/ioscaffeinate/SHA256SUMS"
            manifest.write_text("\n".join(records) + "\n")
            self.assertEqual(check_sha_manifest(root), {line.split("  ", 1)[1] for line in records})
            manifest.write_text("\n".join(records[:-1]) + "\n")
            with self.assertRaisesRegex(ValueError, "cover the approved payload"):
                check_sha_manifest(root)

    def test_host_preflight_never_establishes_device_acceptance(self) -> None:
        hardware = p011.hardware_gate_report()
        self.assertEqual(hardware["device_acceptance"], "PENDING")
        self.assertEqual(hardware["release_authorization"], "BLOCKED")
        self.assertTrue(all(state == "PENDING" for state in hardware["gate_states"].values()))

    @unittest.skipUnless(
        os.environ.get("P011_OFFICIAL_ASSET_DIR") and os.environ.get("P011_VERIFIED_LDID"),
        "requires authentic v0.1.0 release assets and the verified H001 ldid executable",
    )
    def test_official_v010_package_passes_only_with_authentic_signer_input(self) -> None:
        asset_dir = Path(os.environ["P011_OFFICIAL_ASSET_DIR"])
        package = asset_dir / legacy.PACKAGE_FILENAME
        signer = Path(os.environ["P011_VERIFIED_LDID"])
        result = legacy.inspect_official_package(package, asset_dir, signer)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["artifact_scope"], "EXACT_PUBLISHED_V0_1_0")
        self.assertEqual(result["integrity_levels"]["embedded_entitlements"], "EXACT_MATCH")
        self.assertEqual(result["integrity_levels"]["device_package_acceptance"], "PENDING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
