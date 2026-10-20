#!/usr/bin/env python3
"""Offline P013 plist and source-evidence validator; never runs launchctl."""

from __future__ import annotations

import argparse
import plistlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / "packaging/com.ioscaffeinate.daemon.plist"
P013_INPUTS = (
    ".github/workflows/ci.yml",
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/PLAN.md",
    "docs/v0.2/ROADMAP.md",
    "packaging/rootful/DEBIAN/prerm",
    "scripts/build-linux-test.sh",
    "scripts/build-macos.sh",
    "src/service.c",
    "src/service.h",
    "src/daemon.c",
    "src/cli.c",
    "tests/p013_service_unit.c",
    "tests/daemon_readonly_test.c",
    "tests/test_p013_service.py",
    "docs/v0.2/P013-ARCHITECTURE.md",
    "docs/v0.2/P013-LAUNCHD-COMPATIBILITY.md",
    "docs/v0.2/P013-SERVICE-STATES.md",
    "docs/v0.2/P013-SECURITY.md",
    "docs/v0.2/P013-PACKAGING.md",
    "docs/v0.2/P013-DEVICE-ACCEPTANCE.md",
    "docs/v0.2/P013-ROLLBACK.md",
    "docs/v0.2/P013-VALIDATION.md",
    "docs/v0.2/P013-MANIFEST.md",
)
SECRET_PATTERNS = (
    re.compile(r"tskey-[A-Za-z0-9]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b100\.(?:6[4-9]|[78]\d|9\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_plist(path: Path) -> dict[str, object]:
    require(path.is_file() and not path.is_symlink(), f"plist is missing or linked: {path}")
    value = plistlib.loads(path.read_bytes())
    require(isinstance(value, dict), f"plist root must be a dictionary: {path}")
    return value


def validate_layout(staged_path: Path, managed_path: Path) -> list[str]:
    staged = read_plist(staged_path)
    managed = read_plist(managed_path)
    expected_arguments = ["/usr/local/bin/ios-caffeinated", "--foreground"]
    expected_logs = {
        "StandardOutPath": "/var/log/ioscaffeinate/daemon.log",
        "StandardErrorPath": "/var/log/ioscaffeinate/daemon.err",
    }
    for label, plist in (("staged", staged), ("managed", managed)):
        require(plist.get("Label") == "com.ioscaffeinate.daemon", f"{label} label changed")
        require(plist.get("ProgramArguments") == expected_arguments, f"{label} executable/arguments changed")
        for key, path in expected_logs.items():
            require(plist.get(key) == path, f"{label} log path changed: {key}")
        require(plist.get("RunAtLoad") is False, f"{label} must not start at plist load")
    require(staged.get("Disabled") is True, "packaged template must remain Disabled=true")
    require(staged.get("KeepAlive") is True, "packaged template contract changed unexpectedly")
    require(managed.get("Disabled") is False, "managed profile must represent explicit enablement")
    require(managed.get("KeepAlive") is False, "managed profile must suppress uncontrolled crash relaunch")
    return [
        "staged_template=PASS Disabled=true RunAtLoad=false KeepAlive=true",
        "managed_profile=PASS Disabled=false RunAtLoad=false KeepAlive=false",
        "managed_label_and_paths=PASS",
    ]


def validate_sensitive_content() -> None:
    for relative in P013_INPUTS:
        path = ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            require(pattern.search(text) is None, f"credential or private network value found in {relative}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--managed", type=Path, required=True, help="managed live-profile fixture emitted by the C generator")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch(r"[0-9a-f]{40}", args.source_sha) is not None, "source SHA must be a 40-digit Git SHA")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    require(head == args.source_sha, "source SHA does not match the checked-out commit")
    result = validate_layout(STAGED, args.managed)
    validate_sensitive_content()
    result.extend((
        "launchctl_execution=NOT_PERFORMED",
        "service_activation=NOT_PERFORMED",
        "power_assertion=NOT_ACQUIRED",
        "hardware_compatibility=UNVERIFIED",
        "source_sha=" + args.source_sha,
    ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(result) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"P013 validation failed: {error}") from None
