#!/usr/bin/env python3
"""Deterministically validate H004 documentation against checked-in H003 receipts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "v0.2"
PACKAGE_RECEIPT = DOCS / "H003-P011-HOST-PREFLIGHT.json"
SIGNER_RECEIPT = DOCS / "H003-SIGNER-PROVENANCE.json"
EXPECTED = {
    "package": "439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c",
    "signer": "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c",
    "profile": "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca",
}
REQUIRED_DOCS = {
    "H004-PHASE0-CHECKLIST.md": [
        "P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING",
        "RELEASE_BLOCKED",
        "independent physical recovery",
        "OBSERVATIONS_RECORDED_REVIEW_PENDING",
        "assertion ownership/state or P014 recovery state remains `UNKNOWN`",
        "blocks progression beyond Phase 0",
            "MISSING_FIRST_INSTALL_REVIEW_REQUIRED",
            "missing journal alone",
    ],
    "H004-READONLY-COMMANDS.md": [
        "dpkg-query",
        "Expected bootstrap identity is Amethyst/Procursus rootful",
        "ioscaffeinated.sock.lock",
        "recovery-state.json",
        "server policy",
        "schedule list",
        "health sources",
        "evidence inventory",
        "vm_stat",
    ],
    "H004-STOP-CONDITIONS.md": [
        "do not continue",
        "do not repair",
        "SSH",
        "Tailscale",
        "P014 journal",
            "missing journal with prior project runtime history or unknown history",
            "Do not reset or create a journal during Phase 0",
        "assertion state/ownership/release status is `UNKNOWN`",
    ],
    "H004-EVIDENCE-GUIDE.md": [
        "DEVICE_REPORTED",
        "OPERATOR_RECORDED",
        "SIMULATED",
        "manifest.json",
        "privacy review",
    ],
    "H004-RESULT-TEMPLATE.md": [
        "UNKNOWN",
        "UNAVAILABLE",
        "source class",
        "exit code",
        "OBSERVATIONS_RECORDED_REVIEW_PENDING",
        "DEVICE_VERIFIED",
    ],
    "H005-POWER-ASSERTION-INSPECTOR.md": [
        "IOPMCopyAssertionsByProcess",
        "IOPMCopyAssertionsStatus",
        "AVAILABLE_MAC_OS_X_VERSION_10_5_AND_LATER",
        "DriverPMAssertionsDetailed",
        "NO_ASSERTIONS_OBSERVED",
        "ASSERTIONS_PRESENT",
        "UNAVAILABLE",
        "UNKNOWN",
        "assertion_mutation_attempted",
        "Do not stage or transfer this diagnostic under H004",
    ],
    "H005-DPKG-AUDIT-EXCEPTION.md": [
        "missing the `md5sums` control file",
        "173 entries",
        "cy+cpu.*",
        "H005_DPKG_AUDIT_TECHNICAL_SHAPE_MATCH_REVIEW_REQUIRED",
        "never accepts the exception",
        "independent human reviewer",
        "only the `/.` marker",
    ],
    "H005-ACCEPTANCE-HANDOFF.md": [
        "2026-10-25 20:41:49",
        "owner `en0`, ID `500`, level `255`",
        "Process-level assertion ownership",
        "Historical October 18 trial logs",
        "physical acceptance has not been performed",
        "Do not stage or transfer the H005 binary",
        "independent local physical recovery",
    ],
}


class ValidationError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON receipt {path.relative_to(ROOT)}: {exc}") from exc
    require(isinstance(value, dict), f"receipt is not a JSON object: {path.relative_to(ROOT)}")
    return value


def main() -> int:
    package = read_json(PACKAGE_RECEIPT)
    signer = read_json(SIGNER_RECEIPT)

    require(package.get("status") == "P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING",
            "H003 P011 host receipt status changed")
    require(package.get("package", {}).get("expected_sha256") == EXPECTED["package"],
            "H003 package SHA-256 differs from the canonical H003 receipt")
    verified = package.get("verified_package", {})
    require(verified.get("signer_sha256") == EXPECTED["signer"],
            "H003 P011 signer SHA-256 differs from the expected pin")
    require(verified.get("profile_sha256") == EXPECTED["profile"],
            "H003 approved profile SHA-256 differs from the expected pin")
    require(signer.get("result") == "VERIFIED", "H003 signer provenance is not VERIFIED")
    require(signer.get("executable", {}).get("sha256") == EXPECTED["signer"],
            "H003 signer receipt does not match the signer pin")
    for label, digest in EXPECTED.items():
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                f"{label} pin is not a 64-character lowercase SHA-256")

    for filename, required_phrases in REQUIRED_DOCS.items():
        path = DOCS / filename
        require(path.is_file(), f"required H004 document is missing: {path.relative_to(ROOT)}")
        content = path.read_text(encoding="utf-8")
        for phrase in required_phrases:
            require(phrase.casefold() in content.casefold(),
                    f"{filename} is missing required content: {phrase}")
    for filename in (
        "H004-PHASE0-CHECKLIST.md",
        "H004-EVIDENCE-GUIDE.md",
        "H004-RESULT-TEMPLATE.md",
    ):
        content = (DOCS / filename).read_text(encoding="utf-8")
        for key, digest in EXPECTED.items():
            require(digest in content, f"{filename} is missing the H003 {key} identity")

    markdown_files = [DOCS / name for name in REQUIRED_DOCS]
    markdown_files.extend([
        DOCS / "OPERATOR-GUIDE.md",
        DOCS / "P011-DEVICE-ACCEPTANCE.md",
        DOCS / "P018-DEVICE-ACCEPTANCE.md",
        DOCS / "P019-OPERATOR-RUNBOOK.md",
        DOCS / "P014-DEVICE-ACCEPTANCE.md",
        DOCS / "P020-HARDWARE-HANDOFF.md",
    ])
    for path in markdown_files:
        content = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(content.splitlines(), start=1):
            require(line == line.rstrip(),
                    f"{path.relative_to(ROOT)}:{line_number} has trailing whitespace")
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
            if "://" in target or target.startswith("#"):
                continue
            local_target = target.split("#", 1)[0].split("?", 1)[0]
            if local_target:
                resolved = (path.parent / local_target).resolve()
                require(resolved.exists(),
                        f"{path.relative_to(ROOT)} has a broken local link: {target}")

    for filename in REQUIRED_DOCS:
        content = (DOCS / filename).read_text(encoding="utf-8")
        require(content.count("```") % 2 == 0,
                f"{filename} has an unmatched Markdown code fence")
        blocks = re.findall(r"```(?:sh|shell)\s*\n(.*?)\n```", content, flags=re.DOTALL)
        for index, block in enumerate(blocks, start=1):
            result = subprocess.run(["/bin/sh", "-n"], input=block, text=True,
                                    capture_output=True, check=False)
            require(result.returncode == 0,
                    f"{filename} shell block {index} fails /bin/sh -n: {result.stderr.strip()}")

    checklist = (DOCS / "H004-PHASE0-CHECKLIST.md").read_text(encoding="utf-8")
    require("39798613948" in checklist and "39798613926" in checklist,
            "checklist does not bind the H003 exact-head CI run references")
    require("fb39559766144ab0cf4327273ff3188c58200b6b" in checklist,
            "checklist does not name the requested H003 source SHA")
    require("P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING" in package["status"],
            "host receipt must remain explicitly pending device acceptance")

    print("H004_OPERATOR_PACKAGE_VALIDATION_PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"H004_OPERATOR_PACKAGE_VALIDATION_FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
