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
from macho_code_signature import CodeSignatureError, audit_code_signature  # noqa: E402


FAKE_LDID = r'''#!/usr/bin/env python3
import hashlib, os, pathlib, plistlib, struct, sys
PROFILE_PATH = pathlib.Path(os.environ["P010_TEST_PROFILE"])
PROFILE = PROFILE_PATH.read_bytes()
ENTITLEMENTS = plistlib.loads(PROFILE)
KEY = b"com.apple.private.security.no-container"

def blob(magic, payload):
    return struct.pack(">II", magic, len(payload) + 8) + payload

def signature(binary, flags=2):
    if os.environ.get("P010_TEST_UNMARKED") == "1":
        flags = 0
    ncmds, sizeofcmds = struct.unpack_from("<II", binary, 16)
    command_end = 32 + sizeofcmds
    if command_end + 16 > len(binary) or any(binary[command_end:command_end + 16]):
        raise ValueError("no zero-filled load-command padding")
    dataoff = (len(binary) + 15) & ~15
    prefix = bytearray(binary)
    struct.pack_into("<II", prefix, 16, ncmds + 1, sizeofcmds + 16)
    struct.pack_into("<IIII", prefix, command_end, 0x1d, 16, dataoff, 0)
    offset = 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", prefix, offset)
        if command == 0x19 and prefix[offset + 8:offset + 24].split(b"\x00", 1)[0] == b"__LINKEDIT":
            fileoff = struct.unpack_from("<Q", prefix, offset + 40)[0]
            offset_to_signature = dataoff + 4096
            struct.pack_into("<Q", prefix, offset + 32, max(offset_to_signature - fileoff, 0))
            struct.pack_into("<Q", prefix, offset + 48, max(offset_to_signature - fileoff, 0))
        offset += size
    prefix.extend(bytes(dataoff - len(prefix)))

    requirements = struct.pack(">III", 0xfade0c01, 12, 0)
    xml = blob(0xfade7171, plistlib.dumps(ENTITLEMENTS, fmt=plistlib.FMT_XML, sort_keys=True))
    der_payload = b"\x31" + bytes((len(KEY) + 7,)) + b"\x30" + bytes((len(KEY) + 5,)) + b"\x0c" + bytes((len(KEY),)) + KEY + b"\x01\x01\x01"
    der = blob(0xfade7172, der_payload)

    def make_cd(code_bytes):
        page_size = 4096
        code_slots = (dataoff + page_size - 1) // page_size
        identifier = pathlib.Path(binary_path).name.encode() + b"\x00"
        n_special = 7
        ident_offset = 88
        hash_offset = ident_offset + len(identifier) + n_special * 32
        cd_length = hash_offset + code_slots * 32
        cd = bytearray(cd_length)
        struct.pack_into(">IIIIIIIII", cd, 0, 0xfade0c02, cd_length, 0x20400, flags,
                         hash_offset, ident_offset, n_special, code_slots, dataoff)
        struct.pack_into(">4B", cd, 36, 32, 2, 0, 12)
        struct.pack_into(">I", cd, 40, 0)
        struct.pack_into(">II", cd, 44, 0, 0)
        struct.pack_into(">IQ", cd, 52, 0, 0)
        struct.pack_into(">QQQ", cd, 64, 0, 0, 0)
        cd[ident_offset:ident_offset + len(identifier)] = identifier
        special = {2: requirements, 5: xml, 7: der}
        for slot, value in special.items():
            start = hash_offset - slot * 32
            cd[start:start + 32] = hashlib.sha256(value).digest()
        for slot in range(code_slots):
            start = slot * page_size
            value = code_bytes[start:min(start + page_size, dataoff)]
            pos = hash_offset + slot * 32
            cd[pos:pos + 32] = hashlib.sha256(value).digest()
        return bytes(cd)

    def superblob(cd):
        children = [(0, cd), (2, requirements), (5, xml), (7, der)]
        table_end = 12 + len(children) * 8
        indexes = []
        offset = table_end
        for kind, value in children:
            indexes.append((kind, offset))
            offset += len(value)
        out = bytearray(struct.pack(">III", 0xfade0cc0, offset, len(children)))
        for kind, child_offset in indexes:
            out.extend(struct.pack(">II", kind, child_offset))
        for _kind, value in children:
            out.extend(value)
        return bytes(out)

    placeholder_cd = make_cd(prefix)
    signature_bytes = superblob(placeholder_cd)
    struct.pack_into("<I", prefix, command_end + 12, len(signature_bytes))
    offset = 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", prefix, offset)
        if command == 0x19 and prefix[offset + 8:offset + 24].split(b"\x00", 1)[0] == b"__LINKEDIT":
            fileoff = struct.unpack_from("<Q", prefix, offset + 40)[0]
            signature_end = dataoff + len(signature_bytes)
            struct.pack_into("<Q", prefix, offset + 32, signature_end - fileoff)
            struct.pack_into("<Q", prefix, offset + 48, signature_end - fileoff)
        offset += size
    signature_bytes = superblob(make_cd(prefix))
    if len(signature_bytes) != struct.unpack_from("<I", prefix, command_end + 12)[0]:
        raise ValueError("signature size changed unexpectedly")
    return bytes(prefix) + signature_bytes

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
    offset = 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", data, offset)
        if command == 0x1d:
            dataoff, datasize = struct.unpack_from("<II", data, offset + 8)
            sb = data[dataoff:dataoff + datasize]
            _, _, count = struct.unpack_from(">III", sb)
            for index in range(count):
                kind, child = struct.unpack_from(">II", sb, 12 + index * 8)
                if kind == 5:
                    _, length = struct.unpack_from(">II", sb, child)
                    sys.stdout.buffer.write(sb[child + 8:child + length])
                    sys.exit(0)
        offset += size
    sys.exit(3)
if len(args) == 3 and args[0] == "-Cadhoc" and args[1].startswith("-S"):
    if os.environ.get("P010_TEST_SIGN_FAIL") == "1":
        print("injected signing failure", file=sys.stderr)
        sys.exit(9)
    if args[1][2:] != os.environ["P010_TEST_PROFILE"]:
        print("wrong entitlement argument", file=sys.stderr)
        sys.exit(8)
    path = pathlib.Path(args[2])
    binary_path = path
    data = bytearray(path.read_bytes())
    if os.environ.get("P010_TEST_MUTATE_SOURCE") == "1":
        data[-1] ^= 1
    try:
        path.write_bytes(signature(data))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(7)
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

    def signed_fixture(self, name: str, *, env: dict[str, str] | None = None) -> Path:
        directory = Path(tempfile.mkdtemp(prefix=f"signature-fixture-{name}-", dir=self.root))
        binary = directory / name
        shutil.copyfile(self.inputs / name, binary)
        result = subprocess.run(
            [str(self.signer), "-Cadhoc", f"-S{self.profile}", str(binary)],
            capture_output=True, text=True, env=env or self.env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return binary

    @staticmethod
    def signature_blob_offset(binary: bytearray) -> int:
        count = int.from_bytes(binary[16:20], "little")
        offset = 32
        for _ in range(count):
            command = int.from_bytes(binary[offset:offset + 4], "little")
            size = int.from_bytes(binary[offset + 4:offset + 8], "little")
            if command == 0x1d:
                return int.from_bytes(binary[offset + 8:offset + 12], "little")
            offset += size
        raise AssertionError("fixture is missing LC_CODE_SIGNATURE")

    @staticmethod
    def superblob_child(binary: bytearray, signature_offset: int, wanted: int) -> tuple[int, int]:
        count = int.from_bytes(binary[signature_offset + 8:signature_offset + 12], "big")
        for index in range(count):
            kind = int.from_bytes(binary[signature_offset + 12 + index * 8:signature_offset + 16 + index * 8], "big")
            child = int.from_bytes(binary[signature_offset + 16 + index * 8:signature_offset + 20 + index * 8], "big")
            if kind == wanted:
                length = int.from_bytes(binary[signature_offset + child + 4:signature_offset + child + 8], "big")
                return signature_offset + child, length
        raise AssertionError(f"fixture SuperBlob is missing index {wanted}")

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

    def test_independent_signature_parser_checks_ad_hoc_code_and_special_slots(self) -> None:
        for name in ("ios-caffeinate", "ios-caffeinated"):
            binary = self.signed_fixture(name)
            audit = audit_code_signature(binary.read_bytes(), expected_identifier=name)
            self.assertTrue(audit["independent_code_directory_verified"])
            self.assertTrue(audit["entitlements_exact_match"])
            self.assertTrue(audit["adhoc_flag_present"])
            self.assertEqual(audit["signature_kind"], "ADHOC")
            self.assertEqual(audit["code_directory"]["special_slots_verified"], [2, 5, 7])

    def test_independent_signature_parser_detects_modified_executable_bytes(self) -> None:
        binary = self.signed_fixture("ios-caffeinate")
        data = bytearray(binary.read_bytes())
        data[128] ^= 1
        with self.assertRaisesRegex(CodeSignatureError, "executable hash mismatch"):
            audit_code_signature(bytes(data), expected_identifier="ios-caffeinate")

    def test_independent_signature_parser_rejects_unmarked_ldid_output(self) -> None:
        unmarked = self.signed_fixture("ios-caffeinate", env={**self.env, "P010_TEST_UNMARKED": "1"})
        audit = audit_code_signature(unmarked.read_bytes(), expected_identifier="ios-caffeinate")
        self.assertTrue(audit["independent_code_directory_verified"])
        self.assertFalse(audit["adhoc_flag_present"])
        self.assertEqual(audit["signature_kind"], "UNMARKED_LDID_SIGNATURE")

    def test_independent_signature_parser_rejects_malformed_superblob_offsets(self) -> None:
        binary = self.signed_fixture("ios-caffeinate")
        data = bytearray(binary.read_bytes())
        ncmds = int.from_bytes(data[16:20], "little")
        offset = 32
        signature_offset = None
        for _ in range(ncmds):
            command = int.from_bytes(data[offset:offset + 4], "little")
            size = int.from_bytes(data[offset + 4:offset + 8], "little")
            if command == 0x1d:
                signature_offset = int.from_bytes(data[offset + 8:offset + 12], "little")
                break
            offset += size
        assert signature_offset is not None
        data[signature_offset + 16:signature_offset + 20] = b"\xff\xff\xff\xff"
        with self.assertRaisesRegex(CodeSignatureError, "out of bounds"):
            audit_code_signature(bytes(data), expected_identifier="ios-caffeinate")

    def test_independent_signature_parser_rejects_truncated_signature_and_wrong_architecture(self) -> None:
        binary = self.signed_fixture("ios-caffeinate").read_bytes()
        with self.assertRaisesRegex(CodeSignatureError, "truncated|trailing|out of bounds"):
            audit_code_signature(binary[:-1], expected_identifier="ios-caffeinate")
        wrong_arch = bytearray(binary)
        wrong_arch[4:8] = (0x01000007).to_bytes(4, "little")
        with self.assertRaisesRegex(CodeSignatureError, "generic ARM64"):
            audit_code_signature(bytes(wrong_arch), expected_identifier="ios-caffeinate")

    def test_independent_signature_parser_rejects_missing_code_directory(self) -> None:
        data = bytearray(self.signed_fixture("ios-caffeinate").read_bytes())
        signature_offset = self.signature_blob_offset(data)
        data[signature_offset + 12:signature_offset + 16] = (1).to_bytes(4, "big")
        with self.assertRaisesRegex(CodeSignatureError, "signature slots"):
            audit_code_signature(bytes(data), expected_identifier="ios-caffeinate")

    def test_independent_signature_parser_checks_special_slot_hashes(self) -> None:
        data = bytearray(self.signed_fixture("ios-caffeinate").read_bytes())
        signature_offset = self.signature_blob_offset(data)
        code_directory, _ = self.superblob_child(data, signature_offset, 0)
        hash_offset = int.from_bytes(data[code_directory + 16:code_directory + 20], "big")
        hash_size = data[code_directory + 36]
        data[code_directory + hash_offset - 5 * hash_size] ^= 1
        with self.assertRaisesRegex(CodeSignatureError, "special-slot 5 hash mismatch"):
            audit_code_signature(bytes(data), expected_identifier="ios-caffeinate")

    def test_independent_signature_parser_rejects_extra_entitlement_even_with_updated_slot_hash(self) -> None:
        data = bytearray(self.signed_fixture("ios-caffeinate").read_bytes())
        signature_offset = self.signature_blob_offset(data)
        code_directory, _ = self.superblob_child(data, signature_offset, 0)
        entitlement_offset, entitlement_length = self.superblob_child(data, signature_offset, 5)
        xml = bytes(data[entitlement_offset:entitlement_offset + entitlement_length])
        changed = xml.replace(b"com.apple.private.security.no-container", b"com.apple.private.security.no-containex")
        self.assertEqual(len(changed), len(xml))
        data[entitlement_offset:entitlement_offset + entitlement_length] = changed
        hash_offset = int.from_bytes(data[code_directory + 16:code_directory + 20], "big")
        hash_size = data[code_directory + 36]
        slot_start = code_directory + hash_offset - 5 * hash_size
        data[slot_start:slot_start + hash_size] = hashlib.sha256(changed).digest()[:hash_size]
        with self.assertRaisesRegex(CodeSignatureError, "entitlement set differs"):
            audit_code_signature(bytes(data), expected_identifier="ios-caffeinate")

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
