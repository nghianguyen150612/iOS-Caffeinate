#!/usr/bin/env python3
"""Shared validation for the explicitly approved Amethyst signing profile."""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import stat
import subprocess
from pathlib import Path


PROFILE_ID = "amethyst-ios12-rootful"
PROFILE_RELATIVE_PATH = Path("packaging/signing/profiles/amethyst-ios12-rootful.plist")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ENTITLEMENTS = {"com.apple.private.security.no-container": True}


class SigningError(ValueError):
    """Signing input or signer output does not satisfy the approved contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_approved_profile(path: Path) -> tuple[dict[str, bool], str]:
    if path.is_symlink() or not path.is_file():
        raise SigningError(f"entitlement profile must be a regular file: {path}")
    try:
        raw = path.read_bytes()
        value = plistlib.loads(raw)
    except (plistlib.InvalidFileException, ValueError, OSError) as error:
        raise SigningError(f"malformed entitlement profile: {error}") from None
    if not isinstance(value, dict) or value != EXPECTED_ENTITLEMENTS:
        raise SigningError(
            "profile must contain exactly com.apple.private.security.no-container=true; "
            "additional, missing, or changed entitlements are refused"
        )
    if any(type(item) is not bool for item in value.values()):
        raise SigningError("entitlement values must use exact boolean types")
    approved_bytes = (PROJECT_ROOT / PROFILE_RELATIVE_PATH).read_bytes()
    if raw != approved_bytes:
        raise SigningError("profile bytes do not match the versioned approved P010 profile")
    return value, sha256(path)


def validate_signer(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise SigningError("--sign-with-ldid must be an absolute, executable ldid path supplied by the operator")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise SigningError("refusing an ldid path that is not a regular file")
    if metadata.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWGRP | stat.S_IWOTH):
        raise SigningError("refusing an ldid executable with set-id or group/world-writable permissions")
    return path.resolve()


def signer_identity(path: Path, expected_sha256: str | None = None) -> tuple[str, str]:
    """Return the ldid version banner and exact executable digest.

    Procursus ldid prints ``Link Identity Editor <version>`` in its no-argument
    usage banner. Its executable digest is computed and, when pinned, compared
    before the binary is run. The banner is version identification only, not
    signature evidence.
    """
    digest = sha256(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise SigningError("signing tool SHA-256 does not match the pinned executable")
    try:
        result = subprocess.run([str(path)], capture_output=True, text=True, check=False)
    except OSError as error:
        raise SigningError(f"could not identify signing tool: {error}") from None
    output = result.stdout + result.stderr
    match = re.search(r"Link Identity Editor\s+([^\s]+)", output)
    if not match:
        raise SigningError("unsupported ldid: version banner 'Link Identity Editor <version>' is unavailable")
    return match.group(1), digest


def extract_entitlements(signer: Path, binary: Path) -> dict[str, bool]:
    try:
        result = subprocess.run([str(signer), "-e", str(binary)], capture_output=True, check=False)
    except OSError as error:
        raise SigningError(f"could not extract embedded entitlements: {error}") from None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise SigningError(f"ldid entitlement extraction failed ({result.returncode}): {detail}")
    try:
        value = plistlib.loads(result.stdout)
    except (plistlib.InvalidFileException, ValueError) as error:
        raise SigningError(f"ldid returned malformed embedded entitlements: {error}") from None
    if not isinstance(value, dict) or any(type(item) is not bool for item in value.values()):
        raise SigningError("embedded entitlement payload is not an exact boolean dictionary")
    return value


def require_exact_embedded_entitlements(signer: Path, binary: Path) -> None:
    actual = extract_entitlements(signer, binary)
    if actual != EXPECTED_ENTITLEMENTS:
        raise SigningError(f"embedded entitlement set does not exactly match {PROFILE_ID}")
