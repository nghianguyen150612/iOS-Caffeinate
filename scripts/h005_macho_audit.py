#!/usr/bin/env python3
"""Inspect the standalone H005 iOS Mach-O's target, imports, and ABI assumptions."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


class InspectionError(Exception):
    pass


def command(*args: str) -> str:
    try:
        result = subprocess.run(args, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InspectionError(f"command failed: {' '.join(args)}") from exc
    return result.stdout


def inspect(binary: Path, sdk_version: str, xcode_version: str, clang_version: str) -> str:
    description = command("file", str(binary)).strip()
    load_commands = command("otool", "-l", str(binary))
    dependencies = command("otool", "-L", str(binary))
    undefined = command("nm", "-u", str(binary))
    strings = command("strings", str(binary))

    if "mach-o" not in description.lower() or "arm64" not in description.lower():
        raise InspectionError("binary is not a Mach-O ARM64 executable")
    build_commands = re.findall(
        r"\bcmd LC_BUILD_VERSION\b(.*?)(?=\n\s*Load command\b|\Z)",
        load_commands,
        flags=re.DOTALL,
    )
    ios_build_commands = [
        block for block in build_commands
        if re.search(r"^\s*platform\s+2\s*$", block, flags=re.MULTILINE)
        or re.search(r"^\s*platform\s+IOS\s*$", block, flags=re.MULTILINE)
    ]
    legacy_ios_command = "LC_VERSION_MIN_IPHONEOS" in load_commands
    if not ios_build_commands and not legacy_ios_command:
        raise InspectionError("Mach-O load commands do not identify the iOS platform")
    min_os_matches = any(
        re.search(r"^\s*minos\s+12\.0\s*$", block, flags=re.MULTILINE)
        for block in ios_build_commands
    ) or (legacy_ios_command and re.search(
        r"\bcmd LC_VERSION_MIN_IPHONEOS\b.*?^\s*version\s+12\.0\s*$",
        load_commands,
        flags=re.DOTALL | re.MULTILINE,
    ))
    if not min_os_matches:
        raise InspectionError("Mach-O minimum iOS version is not 12.0")
    if "LC_CODE_SIGNATURE" in load_commands:
        raise InspectionError("cross-build input must be unsigned before the pinned H005B signing step")
    if "iokit.framework" not in dependencies.lower():
        raise InspectionError("IOKit.framework is missing from the load dependencies")
    if "corefoundation.framework" not in dependencies.lower():
        raise InspectionError("CoreFoundation.framework is missing from the load dependencies")

    required_imports = (
        "IOServiceMatching",
        "IOServiceGetMatchingService",
        "IORegistryEntryCreateCFProperties",
        "IOObjectRelease",
        "dlsym",
        "alarm",
    )
    for symbol in required_imports:
        if symbol not in undefined:
            raise InspectionError(f"expected IOKit/runtime import is absent: {symbol}")

    dynamic_only = ("IOPMCopyAssertionsByProcess", "IOPMCopyAssertionsStatus")
    for symbol in dynamic_only:
        if symbol not in strings:
            raise InspectionError(f"runtime lookup name is absent from the binary: {symbol}")
        if symbol in undefined:
            raise InspectionError(f"optional IOPM symbol became a hard link dependency: {symbol}")

    forbidden_mutations = (
        "IOPMAssertionCreate",
        "IOPMAssertionRelease",
        "IOPMAssertionSetLevel",
        "IOPMAssertionSetProperty",
        "IOPMAssertionSetTimeout",
    )
    for symbol in forbidden_mutations:
        if symbol in undefined or symbol in strings:
            raise InspectionError(f"assertion mutation symbol unexpectedly appears: {symbol}")

    return "\n".join((
        "H005_MACHO_ABI_INSPECTION_PASS",
        f"binary={binary}",
        f"file={description}",
        f"iphoneos_sdk={sdk_version}",
        f"xcode={xcode_version}",
        f"clang={clang_version}",
        "target=arm64-apple-ios12.0",
        "platform_load_command=IOS",
        "minimum_os=12.0",
        "linked_frameworks=IOKit,CoreFoundation",
        "IOPMCopyAssertionsByProcess=runtime_dlsym_only",
        "IOPMCopyAssertionsStatus=runtime_dlsym_only",
        "assertion_mutation_imports=NONE",
        "execution_timeout_seconds=15",
        "runtime_behavior=UNVERIFIED_ON_IOS_12.5.7",
        "device_transfer=NOT_PERFORMED",
        "",
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--sdk-version", required=True)
    parser.add_argument("--xcode-version", required=True)
    parser.add_argument("--clang-version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()

    try:
        report = inspect(arguments.binary, arguments.sdk_version,
                         arguments.xcode_version, arguments.clang_version)
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(report, encoding="utf-8")
    except (InspectionError, OSError) as exc:
        print(f"H005_MACHO_ABI_INSPECTION_FAIL: {exc}", file=sys.stderr)
        return 1
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
