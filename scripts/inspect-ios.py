#!/usr/bin/env python3
"""Fail closed on non-device/non-arm64/non-iOS12 or signed CI artifacts.

Run on macOS with Xcode after build, or after downloading the binary artifact.
"""
import hashlib
import re
import subprocess
from pathlib import Path


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True, check=True)
    print("$ " + " ".join(args))
    print(result.stdout.rstrip())
    return result.stdout


def require(condition, message):
    if not condition:
        raise SystemExit("FAIL: " + message)


for name in ("ios-caffeinate", "ios-caffeinated"):
    path = str(Path("dist") / name)
    kind = run("file", path)
    require("Mach-O 64-bit executable arm64" in kind, f"{name}: not an ARM64 Mach-O executable")
    require(run("xcrun", "lipo", "-archs", path).strip() == "arm64", "unexpected architecture slice")
    header = run("xcrun", "otool", "-hv", path)
    require("EXECUTE" in header and "NOUNDEFS" in header, "not executable or unresolved build-time symbols")
    loads = run("xcrun", "otool", "-l", path)
    commands = re.split(r"Load command \d+\n", loads)[1:]
    versions = [c for c in commands if re.search(r"cmd LC_(BUILD_VERSION|VERSION_MIN_\w+)", c)]
    require(len(versions) == 1, "missing/ambiguous platform version command")
    version = versions[0]
    if "LC_BUILD_VERSION" in version:
        require(re.search(r"\bplatform\s+(?:IOS|2)\s", version) is not None, "not iOS device platform")
        minimum = re.search(r"\bminos\s+(\S+)", version)
    else:
        require("LC_VERSION_MIN_IPHONEOS" in version, "not legacy iPhoneOS device target")
        minimum = re.search(r"\bversion\s+(\S+)", version)
    require(minimum is not None and minimum[1] in ("12.0", "12.0.0"), "minimum target must be iOS 12.0")
    run("xcrun", "vtool", "-show-build", path)
    deps = run("xcrun", "otool", "-L", path)
    libraries = set(re.findall(r"^\s+(/\S+)\s+\(compatibility", deps, re.M))
    expected = {
        "/usr/lib/libSystem.B.dylib",
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    }
    require(libraries == expected, f"unexpected linked libraries: {libraries}")
    require("/usr/lib/dyld" in loads, "unexpected dynamic loader")
    require("LC_CODE_SIGNATURE" not in loads, "artifact must be unsigned")
    signed = subprocess.run(["codesign", "-d", path], text=True, capture_output=True)
    print(signed.stderr.rstrip())
    require(signed.returncode != 0 and "not signed at all" in signed.stderr, "unsigned state not established")
    print(f"SHA256 {name} {hashlib.sha256(Path(path).read_bytes()).hexdigest()}")
print("PASS: both unsigned iOS 12.0 ARM64 device executables inspected; hardware UNVERIFIED")
