from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from p020_scan_candidate import inspect_payload, scan_package  # noqa: E402


class P020CandidateScanTests(unittest.TestCase):
    def test_rejects_private_key_and_credential_shaped_values(self) -> None:
        fixtures = (
            b"-----BEGIN PRIVATE KEY-----\nnot-a-real-key",
            b"-----BEGIN ENCRYPTED PRIVATE KEY-----\nnot-a-real-key",
            b"-----BEGIN OPENSSH PRIVATE KEY-----\nnot-a-real-key",
            b"GH token ghp_" + b"A" * 25,
            b"AWS id AKIA" + b"A" * 16,
            b"Authorization: Bearer " + b"A" * 24,
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture[:24]):
                self.assertTrue(inspect_payload(fixture))

    def test_ignores_broad_prefixes_and_scanner_source_patterns(self) -> None:
        fixture = b"ASIA AKIA gh[pousr]_ AWS_SECRET_ACCESS_KEY Authorization: Bearer"
        self.assertEqual(inspect_payload(fixture, {}), [])

    def test_detects_runner_secret_value_without_disclosing_it(self) -> None:
        issues = inspect_payload(b"payload=" + b"S" * 24, {"PRIVATE_KEY_FOR_TEST": "S" * 24})
        self.assertEqual(issues, ["runner-secret-environment-value"])
        self.assertNotIn("S" * 24, repr(issues))

    def test_rejects_absolute_ci_workspace_path(self) -> None:
        self.assertIn("host-development-path", inspect_payload(b"/home/runner/work/project/source.c"))

    def test_package_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "candidate.deb"
            target.write_bytes(b"not a package")
            alias = root / "alias.deb"
            alias.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "regular file"):
                scan_package(alias)


if __name__ == "__main__":
    unittest.main()
