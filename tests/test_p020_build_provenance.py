from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import p020_build_provenance as provenance  # noqa: E402


class P020BuildProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ioscaf-p020-provenance-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output_dir = self.root / "build" / "p020"
        first_dir = self.output_dir / "first"
        second_dir = self.output_dir / "second"
        first_dir.mkdir(parents=True)
        second_dir.mkdir(parents=True)
        (self.output_dir / "first-build-info.json").write_text(json.dumps(self.build_info()))
        (self.output_dir / "second-build-info.json").write_text(json.dumps(self.build_info()))
        for directory in (first_dir, second_dir):
            (directory / "ios-caffeinate").write_bytes(b"unsigned arm64 cli")
            (directory / "ios-caffeinated").write_bytes(b"unsigned arm64 daemon")
            (directory / "candidate.deb").write_bytes(b"isolated unsigned package")
        self.args = argparse.Namespace(
            output=self.output_dir / "P020-BUILD-PROVENANCE.json",
            first_build_info=self.output_dir / "first-build-info.json",
            second_build_info=self.output_dir / "second-build-info.json",
            first_binary_dir=first_dir, second_binary_dir=second_dir,
            first_package=first_dir / "candidate.deb", second_package=second_dir / "candidate.deb",
            branch="release/p020-v02-integration", run_id="123",
            run_url="https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/123",
            event="pull_request",
        )

    @staticmethod
    def build_info() -> dict[str, object]:
        return {
            "target_triple": "arm64-apple-ios12.0", "minimum_ios_version": "12.0",
            "sdk": {"name": "iPhoneOS", "version": "18.0"}, "xcode": "Xcode 16.0",
            "clang": "Apple clang version 16.0.0", "source_commit_sha": "1" * 40,
            "source_tree_clean": True, "package_version": "0.2.0~rc1-1", "build_kind": "DEVELOPMENT",
            "release_channel": "PRE_RELEASE", "signing_status": "UNSIGNED",
        }

    def test_capture_records_exact_reproduction_and_unsigned_state(self) -> None:
        with patch.object(provenance, "git_value", side_effect=["1" * 40, "2" * 40, "1761120000", ""]), \
             patch.object(provenance, "_package_version", return_value="0.2.0~rc1-1"), \
             patch.object(provenance, "_package_tool_version", return_value="Debian dpkg-deb package archive backend version 1.22.6."), \
             patch.object(provenance, "inspect_package"):
            result = provenance.capture(self.args)
        self.assertEqual(result["candidate_state"], "UNSIGNED_DEVELOPMENT")
        self.assertEqual(result["reproducibility"]["status"], "REPRODUCIBLE")
        self.assertEqual(result["signing"]["provenance_status"], "SIGNER_PROVENANCE_BLOCKED")
        self.assertFalse(result["validation"]["persistent_state_seeded"])
        self.assertTrue(self.args.output.is_file())

    def test_different_independent_outputs_are_characterized_not_called_reproducible(self) -> None:
        (self.args.second_binary_dir / "ios-caffeinate").write_bytes(b"different unsigned cli")
        with patch.object(provenance, "git_value", side_effect=["1" * 40, "2" * 40, "1761120000", ""]), \
             patch.object(provenance, "_package_version", return_value="0.2.0~rc1-1"), \
             patch.object(provenance, "_package_tool_version", return_value="Debian dpkg-deb package archive backend version 1.22.6."), \
             patch.object(provenance, "inspect_package"):
            result = provenance.capture(self.args)
        self.assertEqual(result["reproducibility"]["status"], "NON_REPRODUCIBLE")
        self.assertFalse(result["reproducibility"]["artifact_hashes_match"])
        self.assertIn("first differing offset", result["reproducibility"]["analysis"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
