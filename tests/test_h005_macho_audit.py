from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import h005_macho_audit as audit


class MachOAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binary = Path("build/h005/ios-power-preflight-inspector")
        self.outputs = {
            "file": "build/h005/ios-power-preflight-inspector: Mach-O 64-bit executable arm64",
            "otool -l": ("Load command 8\ncmd LC_BUILD_VERSION\nplatform 2\n"
                         "minos 12.0\nsdk 26.0\n"),
            "otool -L": ("/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit\n"
                         "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation\n"),
            "nm -u": ("U _IOServiceMatching\nU _IOServiceGetMatchingService\n"
                      "U _IORegistryEntryCreateCFProperties\nU _IOObjectRelease\nU _dlsym\n"),
            "strings": "IOPMCopyAssertionsByProcess\nIOPMCopyAssertionsStatus\n",
        }

    def fake_command(self, *args: str) -> str:
        key = " ".join(args[:2]) if args[0] in ("otool", "nm") else args[0]
        return self.outputs[key]

    def test_ios12_arm64_runtime_lookup_abi_passes(self) -> None:
        with patch.object(audit, "command", side_effect=self.fake_command):
            report = audit.inspect(self.binary, "12.4", "Xcode test", "Apple clang test")
        self.assertIn("minimum_os=12.0", report)
        self.assertIn("IOPMCopyAssertionsStatus=runtime_dlsym_only", report)
        self.assertIn("assertion_mutation_imports=NONE", report)

    def test_optional_iopm_direct_link_fails_closed(self) -> None:
        self.outputs["nm -u"] += "U _IOPMCopyAssertionsByProcess\n"
        with patch.object(audit, "command", side_effect=self.fake_command):
            with self.assertRaisesRegex(audit.InspectionError, "hard link dependency"):
                audit.inspect(self.binary, "12.4", "Xcode test", "Apple clang test")

    def test_wrong_minimum_os_is_rejected(self) -> None:
        self.outputs["otool -l"] = ("Load command 8\ncmd LC_BUILD_VERSION\nplatform 2\n"
                                     "minos 13.0\nsdk 26.0\n")
        with patch.object(audit, "command", side_effect=self.fake_command):
            with self.assertRaisesRegex(audit.InspectionError, "minimum iOS version"):
                audit.inspect(self.binary, "12.4", "Xcode test", "Apple clang test")

    def test_ios_simulator_platform_is_rejected(self) -> None:
        self.outputs["otool -l"] = ("Load command 8\ncmd LC_BUILD_VERSION\nplatform 7\n"
                                     "minos 12.0\nsdk 26.0\n")
        with patch.object(audit, "command", side_effect=self.fake_command):
            with self.assertRaisesRegex(audit.InspectionError, "do not identify the iOS platform"):
                audit.inspect(self.binary, "12.4", "Xcode test", "Apple clang test")

    def test_mutation_import_is_rejected(self) -> None:
        self.outputs["nm -u"] += "U _IOPMAssertionRelease\n"
        with patch.object(audit, "command", side_effect=self.fake_command):
            with self.assertRaisesRegex(audit.InspectionError, "mutation symbol"):
                audit.inspect(self.binary, "12.4", "Xcode test", "Apple clang test")


if __name__ == "__main__":
    unittest.main()
