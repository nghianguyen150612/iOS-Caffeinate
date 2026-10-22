#!/usr/bin/env python3
"""Check a Debian candidate for credential-shaped content and CI paths."""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path


SIGNATURE_PATTERNS = (
    ("private-key", re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("github-token", re.compile(rb"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("slack-token", re.compile(rb"(?<![A-Za-z0-9])(?:xox[baprs]-|xapp-)[A-Za-z0-9-]{20,}")),
    ("aws-access-key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("bearer-token", re.compile(rb"Authorization:\s*Bearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}", re.I)),
    ("aws-secret-key", re.compile(rb"AWS_SECRET_ACCESS_KEY\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}\b")),
)
HOST_PATH_MARKERS = (
    b"/Users/runner/work/",
    b"/home/runner/work/",
    b"GITHUB_WORKSPACE",
    b"RUNNER_TEMP",
    b"/Users/",
    b"/home/runner/",
)


def inspect_payload(data: bytes, environment: dict[str, str] | None = None) -> list[str]:
    """Return redacted issue identifiers; never include matched credential bytes."""
    issues = [name for name, pattern in SIGNATURE_PATTERNS if pattern.search(data)]
    if any(marker in data for marker in HOST_PATH_MARKERS):
        issues.append("host-development-path")
    env = os.environ if environment is None else environment
    for name, value in env.items():
        if re.search(r"TOKEN|SECRET|PASSWORD|PRIVATE_KEY|CREDENTIAL", name, re.I) and len(value) >= 8:
            if value.encode() in data:
                issues.append("runner-secret-environment-value")
                break
    return issues


def scan_package(package: Path) -> list[str]:
    if package.is_symlink() or not package.is_file():
        raise ValueError("candidate package must be a regular file")
    result = subprocess.run(
        ["dpkg-deb", "--fsys-tarfile", str(package)],
        check=True,
        capture_output=True,
    )
    issues: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if stream is None:
                issues.append(f"unreadable-payload:{member.name}")
                continue
            for issue in inspect_payload(stream.read()):
                issues.append(f"{issue}:{member.name}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    try:
        issues = scan_package(args.package.absolute())
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(f"FAIL: candidate scan could not be completed: {error}", file=sys.stderr)
        return 1
    if issues:
        print("FAIL: candidate scan found " + ", ".join(issues), file=sys.stderr)
        return 1
    print("PASS: no credential-shaped content or absolute CI workspace paths found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
