"""Offline P011 release-preflight and read-only device-harness regressions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import plistlib
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import p011_release_preflight as p011  # noqa: E402
from signing_profile import SigningError, load_approved_profile  # noqa: E402
from validate_rootful_package import expected_package_paths, validate_archive_members, validate_package_path_set  # noqa: E402


def release_api_fixture() -> dict[str, object]:
    assets = []
    for name in p011.EXPECTED_ASSETS:
        assets.append({
            "name": name,
            "size": p011.EXPECTED_PACKAGE_SIZE if name == p011.PACKAGE_FILENAME else 100,
            "state": "uploaded",
            "browser_download_url": f"https://github.com/{p011.REPOSITORY}/releases/download/{p011.TAG}/{name}",
        })
    return {
        "tag_name": p011.TAG,
        "html_url": p011.RELEASE_URL,
        "name": "iOS-Caffeinate v0.1.0",
        "draft": False,
        "prerelease": False,
        "assets": assets,
    }


class P011ReleasePreflightTests(unittest.TestCase):
    def test_stable_release_identity_and_asset_set(self) -> None:
        assets = p011.validate_release_identity(release_api_fixture())
        self.assertEqual(set(assets), set(p011.EXPECTED_ASSETS))
        self.assertEqual(p011.TAG, "v0.1.0")
        self.assertEqual(p011.REPOSITORY, "nghianguyen150612/iOS-Caffeinate")
        self.assertEqual(p011.RELEASE_URL, "https://github.com/nghianguyen150612/iOS-Caffeinate/releases/tag/v0.1.0")

    def test_expected_published_package_sha256_is_pinned(self) -> None:
        self.assertEqual(
            p011.EXPECTED_PACKAGE_SHA256,
            "439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c",
        )

    def test_wrong_tag_or_draft_release_is_rejected(self) -> None:
        wrong_tag = release_api_fixture()
        wrong_tag["tag_name"] = "v0.1.0-rc1"
        with self.assertRaisesRegex(p011.PreflightError, "tag"):
            p011.validate_release_identity(wrong_tag)
        draft = release_api_fixture()
        draft["draft"] = True
        with self.assertRaisesRegex(p011.PreflightError, "stable release"):
            p011.validate_release_identity(draft)

    def test_missing_or_extra_release_asset_is_rejected(self) -> None:
        response = release_api_fixture()
        response["assets"] = response["assets"][:-1]
        with self.assertRaisesRegex(p011.PreflightError, "asset names"):
            p011.validate_release_identity(response)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with self.assertRaisesRegex(p011.PreflightError, "duplicate"):
            p011.parse_json(b'{"tag_name":"v0.1.0","tag_name":"v0.2.0"}', "fixture")

    def test_download_redirect_or_url_to_unapproved_host_is_rejected(self) -> None:
        with self.assertRaisesRegex(p011.PreflightError, "unapproved"):
            p011._check_url("https://attacker.example/package.deb", p011.ALLOWED_DOWNLOAD_HOSTS)

    def test_download_destination_symlink_is_rejected_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            link = root / "release-assets"
            link.symlink_to(target, target_is_directory=True)
            with patch.object(p011, "fetch_release_metadata") as fetch:
                with self.assertRaisesRegex(p011.PreflightError, "must not be a symlink"):
                    p011.download_release_assets(link)
                fetch.assert_not_called()

    def test_wrong_debian_architecture_is_rejected(self) -> None:
        fields = {"Package": p011.DEBIAN_PACKAGE, "Version": p011.PACKAGE_VERSION, "Architecture": "arm64"}
        with self.assertRaisesRegex(p011.PreflightError, "architecture"):
            p011.validate_debian_identity(fields)

    def test_unexpected_debian_version_is_rejected(self) -> None:
        fields = {"Package": p011.DEBIAN_PACKAGE, "Version": "0.2.0-1", "Architecture": p011.DEBIAN_ARCHITECTURE}
        with self.assertRaisesRegex(p011.PreflightError, "version"):
            p011.validate_debian_identity(fields)

    def test_wrong_package_identifier_is_rejected(self) -> None:
        fields = {"Package": "com.example.other", "Version": p011.PACKAGE_VERSION, "Architecture": p011.DEBIAN_ARCHITECTURE}
        with self.assertRaisesRegex(p011.PreflightError, "identifier"):
            p011.validate_debian_identity(fields)

    def test_unsigned_package_manifest_is_rejected(self) -> None:
        manifest = {
            "schema_version": 1,
            "package_identifier": p011.DEBIAN_PACKAGE,
            "package_version": p011.PACKAGE_VERSION,
            "architecture": p011.DEBIAN_ARCHITECTURE,
            "source_commit_sha": p011.SOURCE_COMMIT,
            "source_tree_clean": True,
            "package": {"file": p011.PACKAGE_FILENAME, "sha256": p011.EXPECTED_PACKAGE_SHA256},
            "signing": {"state": "UNSIGNED"},
        }
        with self.assertRaisesRegex(p011.PreflightError, "unsigned"):
            p011.validate_package_build_manifest(manifest, p011.EXPECTED_PACKAGE_SHA256)

    def test_invalid_signing_profile_identity_is_rejected(self) -> None:
        signing = {
            "profile_id": "generic-ios-rootful",
            "profile_path": p011.PROFILE_RELATIVE_PATH.as_posix(),
            "profile_sha256": p011.EXPECTED_PROFILE_SHA256,
            "signing_tool_version": p011.EXPECTED_SIGNER_VERSION,
            "signing_tool_sha256": p011.EXPECTED_SIGNER_SHA256,
            "embedded_entitlements": "EXACT_MATCH",
        }
        with self.assertRaisesRegex(p011.PreflightError, "approved Amethyst"):
            p011.validate_profile_identity(signing, require_embedded=True)

    def test_invalid_profile_bytes_are_rejected_by_p010_profile_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "amethyst-ios12-rootful.plist"
            profile.write_bytes(plistlib.dumps({
                "com.apple.private.security.no-container": True,
                "com.apple.private.security.cs.allow-jit": True,
            }))
            with self.assertRaises(SigningError):
                load_approved_profile(profile)

    def test_tampered_package_checksum_sidecar_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset_dir = Path(temporary)
            sidecar = asset_dir / f"{p011.PACKAGE_FILENAME}.sha256"
            sidecar.write_text("0" * 64 + "  " + p011.PACKAGE_FILENAME + "\n")
            with self.assertRaisesRegex(p011.PreflightError, "sidecar"):
                p011.validate_package_checksum_sidecar(asset_dir, p011.EXPECTED_PACKAGE_SHA256)

    def test_tampered_package_manifest_relationship_is_rejected(self) -> None:
        manifest = {
            "schema_version": 1,
            "package_identifier": p011.DEBIAN_PACKAGE,
            "package_version": "0.1.1-1",
            "architecture": p011.DEBIAN_ARCHITECTURE,
            "source_commit_sha": p011.SOURCE_COMMIT,
            "source_tree_clean": True,
            "package": {"file": p011.PACKAGE_FILENAME, "sha256": p011.EXPECTED_PACKAGE_SHA256},
            "signing": {},
        }
        with self.assertRaisesRegex(p011.PreflightError, "version"):
            p011.validate_package_build_manifest(manifest, p011.EXPECTED_PACKAGE_SHA256)

    def test_tampered_manifest_package_hash_is_rejected(self) -> None:
        manifest = {
            "schema_version": 1,
            "package_identifier": p011.DEBIAN_PACKAGE,
            "package_version": p011.PACKAGE_VERSION,
            "architecture": p011.DEBIAN_ARCHITECTURE,
            "source_commit_sha": p011.SOURCE_COMMIT,
            "source_tree_clean": True,
            "package": {"file": p011.PACKAGE_FILENAME, "sha256": "0" * 64},
            "signing": {},
        }
        with self.assertRaisesRegex(p011.PreflightError, "SHA-256 mismatch"):
            p011.validate_package_build_manifest(manifest, p011.EXPECTED_PACKAGE_SHA256)

    def test_signed_candidate_manifest_cannot_overstate_hardware_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset_dir = Path(temporary)
            (asset_dir / "P010-RELEASE-MANIFEST.json").write_text('{"manifest_version":1}')
            (asset_dir / "P010-SIGNED-CANDIDATE-MANIFEST.json").write_text('{"manifest_version":1}')
            with self.assertRaises(p011.PreflightError):
                p011.validate_release_manifests(asset_dir, p011.EXPECTED_PACKAGE_SHA256, {})

    def test_wrong_alias_target_is_rejected_by_existing_p010_archive_validator(self) -> None:
        member = tarfile.TarInfo("usr/local/bin/ic")
        member.type = tarfile.SYMTYPE
        member.linkname = "ios-caffeinate-copy"
        with self.assertRaisesRegex(ValueError, "unexpected package symlink"):
            validate_archive_members([member])

    def test_p010_expected_package_layout_has_canonical_executable_names(self) -> None:
        paths = expected_package_paths()
        self.assertIn("usr/local/bin/ios-caffeinate", paths)
        self.assertIn("usr/local/bin/ios-caffeinated", paths)
        self.assertIn("usr/local/bin/ic", paths)
        self.assertIn("usr/local/libexec/ioscaffeinate-manager", paths)
        self.assertNotIn("usr/local/bin/ios-caffeinate-copy", paths)

    def test_wrong_executable_path_is_rejected_by_existing_p010_path_validator(self) -> None:
        expected = expected_package_paths()
        actual = set(expected)
        actual.remove("usr/local/bin/ios-caffeinated")
        actual.add("usr/local/bin/ios-caffeinated-copy")
        with self.assertRaisesRegex(ValueError, "approved payload layout"):
            validate_package_path_set(actual, expected)

    def test_clean_published_package_docs_use_its_source_commit(self) -> None:
        paths = expected_package_paths(p011.SOURCE_COMMIT, True)
        self.assertIn("usr/share/doc/ioscaffeinate/docs/P010-DEVICE-ACCEPTANCE.md", paths)
        self.assertNotIn("usr/share/doc/ioscaffeinate/docs/v0.2/ROADMAP.md", paths)

    def test_dirty_package_docs_follow_the_current_build_tree(self) -> None:
        paths = expected_package_paths(p011.SOURCE_COMMIT, False)
        self.assertIn("usr/share/doc/ioscaffeinate/docs/v0.2/ROADMAP.md", paths)

    def test_missing_dpkg_deb_dependency_fails_closed(self) -> None:
        with patch.object(p011.shutil, "which", return_value=None):
            with self.assertRaisesRegex(p011.PreflightError, "dpkg-deb is required"):
                p011.debian_fields(Path("untrusted.deb"))

    def test_missing_hardware_evidence_remains_pending(self) -> None:
        hardware = p011.hardware_gate_report()
        self.assertTrue(hardware["gate_states"])
        self.assertEqual(set(hardware["gate_states"].values()), {"PENDING"})
        self.assertEqual(hardware["device_acceptance"], "PENDING")

    def test_pending_hardware_gates_block_acceptance_authorization(self) -> None:
        hardware = p011.hardware_gate_report()
        self.assertEqual(hardware["release_authorization"], "BLOCKED")
        self.assertEqual(hardware["unattended_24_7"], "NOT_VALIDATED")
        self.assertEqual(hardware["scheduled_wake"], "UNVERIFIED")

    def test_device_preflight_is_posix_syntax_and_has_no_state_changing_commands(self) -> None:
        script = ROOT / "scripts/p011_device_preflight.sh"
        syntax = subprocess.run(["sh", "-n", str(script)], text=True, capture_output=True)
        self.assertEqual(syntax.returncode, 0, msg=syntax.stderr)
        code = "\n".join(line.split("#", 1)[0] for line in script.read_text().splitlines())
        forbidden = (
            r"\bdpkg\s+-i\b", r"\bdpkg\s+--remove\b", r"\bkill(?:all)?\b",
            r"\bunlink\b", r"\brm\s", r"\bchmod\b", r"\bmkdir\b",
            r"\blaunchctl\s+(?:load|bootstrap|enable|kickstart|start|restart)\b",
            r"\b(?:ios-caffeinate|ic)\s+(?:probe|start|stop)\b",
            r"\b(?:curl|wget|ssh|tailscale)\b",
        )
        for pattern in forbidden:
            self.assertNotRegex(code, pattern)

    def test_device_preflight_fails_closed_when_dependencies_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as empty_path:
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "scripts/p011_device_preflight.sh")],
                text=True,
                capture_output=True,
                env={**os.environ, "PATH": empty_path},
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("P011_DEVICE_PREFLIGHT=BLOCKED", result.stdout)


if __name__ == "__main__":
    unittest.main()
