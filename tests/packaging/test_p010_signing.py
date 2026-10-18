#!/usr/bin/env python3
"""P010 profile, signing, provenance, release gate, and package regressions."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests/packaging"))

from signing_profile import PROFILE_ID, PROFILE_RELATIVE_PATH, SigningError, load_approved_profile, validate_signer  # noqa: E402
from validate_rootful_package import inspect_package  # noqa: E402
from p010_release_manifest import release_status  # noqa: E402
import p010_evidence  # noqa: E402
import p010_signed_candidate_manifest  # noqa: E402
from test_rootful_package import write_source_inputs  # noqa: E402


FAKE_LDID = r'''#!/usr/bin/env python3
import os, pathlib, struct, sys
PROFILE = pathlib.Path(os.environ["P010_TEST_PROFILE"]).read_bytes()
args = sys.argv[1:]
if not args:
    print("Link Identity Editor p010-fixture-1", file=sys.stderr)
    sys.exit(1)
if args[0] == "-e":
    if os.environ.get("P010_TEST_NO_EXTRACT") == "1":
        print("entitlement extraction unsupported", file=sys.stderr)
        sys.exit(2)
    data = pathlib.Path(args[1]).read_bytes()
    ncmds = struct.unpack_from("<I", data, 16)[0]
    sizeofcmds = struct.unpack_from("<I", data, 20)[0]
    offset = 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", data, offset)
        if command == 0x1d:
            dataoff, datasize = struct.unpack_from("<II", data, offset + 8)
            sys.stdout.buffer.write(data[dataoff:dataoff + datasize])
            sys.exit(0)
        offset += size
    sys.exit(3)
if args[0].startswith("-S"):
    if os.environ.get("P010_TEST_SIGN_FAIL") == "1":
        print("injected signing failure", file=sys.stderr)
        sys.exit(9)
    if args[0][2:] != os.environ["P010_TEST_PROFILE"]:
        print("wrong entitlement argument", file=sys.stderr)
        sys.exit(8)
    path = pathlib.Path(args[1])
    data = path.read_bytes()
    if os.environ.get("P010_TEST_MUTATE_SOURCE") == "1":
        altered = bytearray(data)
        altered[-1] ^= 1
        data = bytes(altered)
    ncmds = struct.unpack_from("<I", data, 16)[0]
    sizeofcmds = struct.unpack_from("<I", data, 20)[0]
    end = 32 + sizeofcmds
    linkedit_size = len(data) + 16 + len(PROFILE)
    offset = 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", data, offset)
        if command == 0x19 and data[offset + 8:offset + 24].split(b"\x00", 1)[0] == b"__LINKEDIT":
            altered = bytearray(data)
            struct.pack_into("<Q", altered, offset + 32, linkedit_size)
            struct.pack_into("<Q", altered, offset + 48, linkedit_size)
            data = bytes(altered)
        offset += size
    signature = struct.pack("<IIII", 0x1d, 16, len(data) + 16, len(PROFILE))
    header = bytearray(data[:32])
    struct.pack_into("<I", header, 16, ncmds + 1)
    struct.pack_into("<I", header, 20, sizeofcmds + 16)
    path.write_bytes(bytes(header) + data[32:end] + signature + data[end:] + PROFILE)
    sys.exit(0)
sys.exit(4)
'''


class P010SigningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("dpkg-deb"):
            raise unittest.SkipTest("dpkg-deb is required for P010 package signing tests")
        cls.temp = tempfile.TemporaryDirectory(prefix="ioscaffeinate-p010-tests-")
        cls.root = Path(cls.temp.name)
        cls.profile = ROOT / PROFILE_RELATIVE_PATH
        cls.signer = cls.root / "ldid-fixture"
        cls.signer.write_text(FAKE_LDID)
        cls.signer.chmod(0o755)
        cls.env = {**os.environ, "P010_TEST_PROFILE": str(cls.profile)}
        cls.inputs = cls.root / "input"
        write_source_inputs(cls.inputs)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def builder(self, output: Path, *, profile: Path | None = None, signer: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        command = [
            str(ROOT / "scripts/package-rootful.sh"),
            "--input-dir", str(self.inputs),
            "--output-dir", str(output),
        ]
        if signer:
            command.extend(("--sign-with-ldid", str(signer)))
        if profile:
            command.extend(("--entitlements", str(profile)))
        return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, env=env or self.env)

    def test_profile_is_exact_and_versioned(self) -> None:
        entitlements, digest = load_approved_profile(self.profile)
        self.assertEqual(PROFILE_ID, "amethyst-ios12-rootful")
        self.assertEqual(entitlements, {"com.apple.private.security.no-container": True})
        self.assertEqual(digest, hashlib.sha256(self.profile.read_bytes()).hexdigest())

    def test_additional_privileged_entitlement_is_rejected(self) -> None:
        malicious = self.root / "extra.plist"
        malicious.write_bytes(plistlib.dumps({
            "com.apple.private.security.no-container": True,
            "platform-application": True,
        }))
        with self.assertRaisesRegex(SigningError, "additional"):
            load_approved_profile(malicious)

    def test_signer_symlink_is_rejected(self) -> None:
        alias = self.root / "ldid-alias"
        alias.symlink_to(self.signer)
        with self.assertRaisesRegex(SigningError, "absolute, executable"):
            validate_signer(alias)

    def test_signing_requires_explicit_tool_and_profile_pair(self) -> None:
        result = self.builder(self.root / "missing-profile", signer=self.signer)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be supplied together", result.stderr)
        result = self.builder(self.root / "missing-signer", profile=self.profile)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be supplied together", result.stderr)

    def test_signs_both_isolated_copies_and_tracks_exact_hashes(self) -> None:
        before = {name: hashlib.sha256((self.inputs / name).read_bytes()).hexdigest() for name in ("ios-caffeinate", "ios-caffeinated")}
        output = self.root / "signed"
        result = self.builder(output, profile=self.profile, signer=self.signer)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        package = next(output.glob("*.deb"))
        with patch.dict(os.environ, self.env):
            report = inspect_package(package, self.signer)
        self.assertIn("signing_state=SIGNATURE_PRESENT", report)
        self.assertIn("embedded_entitlements=EXACT_MATCH", report)
        self.assertIn("signature_verification=PENDING", report)
        self.assertIn("device_package_acceptance=NOT_ACCEPTED", report)
        self.assertEqual(before, {name: hashlib.sha256((self.inputs / name).read_bytes()).hexdigest() for name in before})
        sidecar = json.loads(Path(str(package) + ".manifest.json").read_text())
        self.assertEqual(sidecar["signing"]["profile_id"], PROFILE_ID)
        self.assertEqual(sidecar["signing"]["source_binary_sha256"], before)
        self.assertEqual(set(sidecar["signing"]["final_binary_sha256"]), set(before))
        self.assertTrue(all(sidecar["signing"]["final_binary_sha256"][name] != before[name] for name in before))
        self.assertEqual(sidecar["package"]["sha256"], hashlib.sha256(package.read_bytes()).hexdigest())
        repeat = self.root / "signed-repeat"
        repeated = self.builder(repeat, profile=self.profile, signer=self.signer)
        self.assertEqual(repeated.returncode, 0, msg=repeated.stderr)
        repeated_package = next(repeat.glob("*.deb"))
        self.assertEqual(hashlib.sha256(package.read_bytes()).digest(), hashlib.sha256(repeated_package.read_bytes()).digest())
        alternate_signer = self.root / "ldid-fixture-alternate"
        alternate_signer.write_bytes(self.signer.read_bytes() + b"\n# different signer identity\n")
        alternate_signer.chmod(0o755)
        with patch.dict(os.environ, self.env):
            with self.assertRaisesRegex(ValueError, "ldid SHA-256 differs"):
                inspect_package(package, alternate_signer)

    def test_signed_validation_without_entitlement_extractor_is_blocked(self) -> None:
        output = self.root / "blocked-extractor"
        env = {**self.env, "P010_TEST_NO_EXTRACT": "1"}
        result = self.builder(output, profile=self.profile, signer=self.signer, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("entitlement extraction failed", result.stderr)

    def test_unrelated_signed_executable_is_rejected(self) -> None:
        output = self.root / "unrelated-signer-output"
        env = {**self.env, "P010_TEST_MUTATE_SOURCE": "1"}
        result = self.builder(output, profile=self.profile, signer=self.signer, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("signature-only transformation", result.stderr)
        self.assertFalse(list(output.glob("*.deb")) if output.exists() else False)

    def test_signer_failure_does_not_emit_package(self) -> None:
        output = self.root / "sign-failure"
        env = {**self.env, "P010_TEST_SIGN_FAIL": "1"}
        result = self.builder(output, profile=self.profile, signer=self.signer, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list(output.glob("*.deb")) if output.exists() else False)

    def test_release_authorization_stays_blocked_without_package_acceptance(self) -> None:
        self.assertEqual(release_status("PENDING", False), "BLOCKED")
        self.assertEqual(release_status("DEVICE_PACKAGE_ACCEPTED", False), "BLOCKED")
        self.assertEqual(release_status("DEVICE_PACKAGE_ACCEPTED", True), "RC_REVIEW_REQUIRED")

    def test_operator_bundle_does_not_convert_summary_into_accepted_evidence(self) -> None:
        output = self.root / "operator-evidence"
        bundle = p010_evidence.prepare(output)
        self.assertEqual(bundle["evidence_origin"], "OPERATOR_RECORDED")
        self.assertEqual(bundle["review_status"], "REVIEW_REQUIRED")
        self.assertEqual(bundle["raw_evidence_files"], [])
        self.assertEqual(bundle["raw_provenance_records"], [])
        self.assertEqual(bundle["release_authorization"], "BLOCKED")
        self.assertTrue(all(value != "PASS" for value in bundle["p009_gates"].values()))
        summary = json.loads((output / "operator-reported-observations.json").read_text())
        self.assertFalse(summary["p009_review"]["raw_device_logs_supplied"])
        self.assertTrue(summary["p009_review"]["human_review_field_is_not_approval"])

    def test_external_manifest_must_match_package_manifest(self) -> None:
        output = self.root / "unsigned-for-sidecar-test"
        result = self.builder(output)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        package = next(output.glob("*.deb"))
        sidecar = Path(str(package) + ".manifest.json")
        manifest = json.loads(sidecar.read_text())
        manifest["signing"]["unexpected"] = True
        sidecar.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "external and embedded signing records disagree"):
            inspect_package(package)

    def test_exact_source_release_manifest_keeps_candidate_blocked(self) -> None:
        dist = self.root / "manifest-dist"
        package_dir = dist / "package"
        package_dir.mkdir(parents=True)
        built = self.builder(package_dir)
        self.assertEqual(built.returncode, 0, msg=built.stderr)
        source_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        output = package_dir / "P010-RELEASE-MANIFEST.json"
        env = {
            **self.env,
            "P010_SOURCE_SHA": source_sha,
            "P010_WORKFLOW_URL": "https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/1",
            "P010_LINUX_PROTOCOL_RESULT": "success",
            "P010_IOS_CROSS_BUILD_RESULT": "success",
            "P010_IOS_INSPECTION_RESULT": "success",
            "P010_ROOTFUL_PACKAGE_RESULT": "success",
            "P010_P009_RESULT": "success",
            "GITHUB_REPOSITORY": "nghianguyen150612/iOS-Caffeinate",
        }
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/p010_release_manifest.py"), "--dist", str(dist), "--output", str(output)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        manifest = json.loads(output.read_text())
        self.assertEqual(manifest["source"]["commit_sha"], source_sha)
        self.assertEqual(manifest["signing"]["profile_id"], PROFILE_ID)
        self.assertIsNone(manifest["signing"]["signing_tool_sha256"])
        self.assertEqual(manifest["artifacts"]["signed_candidate_package"], None)
        self.assertEqual(manifest["device_evidence"]["device_package_acceptance"], "PENDING")
        self.assertEqual(manifest["release_authorization_status"], "BLOCKED")

        signed_dir = dist / "signed-candidate"
        signed_build = self.builder(signed_dir, profile=self.profile, signer=self.signer)
        self.assertEqual(signed_build.returncode, 0, msg=signed_build.stderr)
        signed_package = next(signed_dir.glob("*.deb"))
        signed_sidecar_path = Path(str(signed_package) + ".manifest.json")
        signed_sidecar = json.loads(signed_sidecar_path.read_text())
        # Model a clean committed checkout; the fixture run itself may be on a dirty developer tree.
        signed_sidecar["source_tree_clean"] = True
        signed_sidecar_path.write_text(json.dumps(signed_sidecar))
        signed_manifest_path = signed_dir / "P010-SIGNED-CANDIDATE-MANIFEST.json"
        with patch.object(
            p010_signed_candidate_manifest.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "result=PASS\n", ""),
        ), patch.object(
            sys,
            "argv",
            [
                "p010_signed_candidate_manifest.py",
                "--ci-manifest", str(output),
                "--package", str(signed_package),
                "--ldid", str(self.signer),
                "--output", str(signed_manifest_path),
            ],
        ):
            self.assertEqual(p010_signed_candidate_manifest.main(), 0)
        candidate = json.loads(signed_manifest_path.read_text())
        self.assertEqual(candidate["source"]["commit_sha"], source_sha)
        self.assertEqual(candidate["signing"]["profile_id"], PROFILE_ID)
        self.assertEqual(candidate["signing"]["signing_tool_version"], "p010-fixture-1")
        self.assertEqual(candidate["signing"]["signature_integrity"], "PENDING")
        self.assertEqual(candidate["device_package_acceptance"], "NOT_ACCEPTED")
        self.assertEqual(candidate["release_authorization_status"], "BLOCKED")

    def test_debian_rc_version_orders_before_stable_version(self) -> None:
        result = subprocess.run(
            ["dpkg", "--compare-versions", "0.1.0~rc1-1", "lt", "0.1.0-1"],
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
