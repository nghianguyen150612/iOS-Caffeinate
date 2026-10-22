#!/usr/bin/env python3
"""Read-only verification of the published iOS-Caffeinate v0.1.0 release.

The verifier checks the pinned GitHub release identity, package checksum,
package sidecars, P010 manifests, signing profile identity, and the existing
P010 rootful package validator. It never installs a package or runs maintainer
scripts. A successful result is cloud artifact verification, not cryptographic
trust, device acceptance, or release authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from signing_profile import PROFILE_ID, PROFILE_RELATIVE_PATH, load_approved_profile  # noqa: E402
from validate_rootful_package import PACKAGE as DEBIAN_PACKAGE  # noqa: E402
from validate_rootful_package import inspect_package  # noqa: E402


REPOSITORY = "nghianguyen150612/iOS-Caffeinate"
TAG = "v0.1.0"
RELEASE_URL = f"https://github.com/{REPOSITORY}/releases/tag/{TAG}"
SOURCE_COMMIT = "0cfdc645dc1d67ddc4320a00bb114763b9669b66"
PACKAGE_VERSION = "0.1.0-1"
DEBIAN_ARCHITECTURE = "iphoneos-arm"
PACKAGE_FILENAME = "ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb"
EXPECTED_PACKAGE_SHA256 = "439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c"
EXPECTED_PACKAGE_SIZE = 95572
EXPECTED_PROFILE_SHA256 = "cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca"
EXPECTED_SIGNER_VERSION = "2.1.5-procursus7"
EXPECTED_SIGNER_SHA256 = "15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c"
EXPECTED_ASSETS = (
    PACKAGE_FILENAME,
    f"{PACKAGE_FILENAME}.files.sha256",
    f"{PACKAGE_FILENAME}.manifest.json",
    f"{PACKAGE_FILENAME}.manifest.txt",
    f"{PACKAGE_FILENAME}.sha256",
    "P010-RELEASE-MANIFEST.json",
    "P010-SIGNED-CANDIDATE-MANIFEST.json",
    "signed-validation.txt",
)
MAX_ASSET_BYTES = 4 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 16 * 1024 * 1024
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{TAG}"
ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}


class PreflightError(ValueError):
    """Untrusted release input failed a required validation check."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "JSON contains a duplicate object key")
        result[key] = value
    return result


def reject_json_constant(_: str) -> None:
    raise PreflightError("JSON contains a non-standard numeric value")


def parse_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_json_pairs,
            parse_constant=reject_json_constant,
        )
    except PreflightError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PreflightError(f"{label} is not valid UTF-8 JSON") from None
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def read_json(path: Path, label: str) -> dict[str, Any]:
    require(not path.is_symlink() and path.is_file(), f"{label} is missing or not a regular file")
    require(path.stat().st_size <= MAX_ASSET_BYTES, f"{label} exceeds its size limit")
    return parse_json(path.read_bytes(), label)


def validate_release_identity(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Check a GitHub REST release response and return its exact asset map."""
    require(document.get("tag_name") == TAG, "GitHub release tag does not match v0.1.0")
    require(document.get("html_url") == RELEASE_URL, "GitHub release URL does not match the official v0.1.0 release")
    require(document.get("name") == "iOS-Caffeinate v0.1.0", "GitHub release title is unexpected")
    require(document.get("draft") is False and document.get("prerelease") is False, "v0.1.0 is not a published stable release")
    assets = document.get("assets")
    require(isinstance(assets, list), "GitHub release assets are missing or malformed")
    by_name: dict[str, dict[str, Any]] = {}
    for item in assets:
        require(isinstance(item, dict), "GitHub release contains a malformed asset record")
        name = item.get("name")
        require(isinstance(name, str) and name not in by_name, "GitHub release has a duplicate or invalid asset name")
        by_name[name] = item
    require(set(by_name) == set(EXPECTED_ASSETS), "GitHub v0.1.0 release asset names differ from the published stable package set")
    for name, item in by_name.items():
        size = item.get("size")
        require(type(size) is int and 0 < size <= MAX_ASSET_BYTES, f"GitHub release asset has an invalid size: {name}")
        require(item.get("state") == "uploaded", f"GitHub release asset is not fully uploaded: {name}")
        expected_url = f"https://github.com/{REPOSITORY}/releases/download/{TAG}/{urllib.parse.quote(name, safe='')}"
        require(item.get("browser_download_url") == expected_url, f"GitHub release asset URL is unexpected: {name}")
    require(by_name[PACKAGE_FILENAME].get("size") == EXPECTED_PACKAGE_SIZE, "published Debian package size differs from the v0.1.0 release record")
    return by_name


def _check_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and parsed.hostname in allowed_hosts, "refusing an unapproved release download URL")
    require(not parsed.username and not parsed.password, "release URL must not contain credentials")


class RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> urllib.request.Request | None:
        _check_url(newurl, {"api.github.com", *ALLOWED_DOWNLOAD_HOSTS})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bytes(url: str, *, accept: str, limit: int, allowed_hosts: set[str]) -> bytes:
    _check_url(url, allowed_hosts)
    request = urllib.request.Request(
        url,
        headers={"Accept": accept, "User-Agent": "iOS-Caffeinate-P011-read-only-preflight/1"},
        method="GET",
    )
    opener = urllib.request.build_opener(RestrictedRedirectHandler())
    try:
        with opener.open(request, timeout=30) as response:
            _check_url(response.geturl(), {"api.github.com", *ALLOWED_DOWNLOAD_HOSTS})
            declared = response.headers.get("Content-Length")
            if declared is not None:
                require(declared.isdigit() and int(declared) <= limit, "GitHub response exceeds its size limit")
            data = response.read(limit + 1)
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise PreflightError(f"GitHub release retrieval failed: {type(error).__name__}") from None
    require(len(data) <= limit, "GitHub response exceeds its size limit")
    return data


def fetch_release_metadata() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    raw = fetch_bytes(API_URL, accept="application/vnd.github+json", limit=MAX_ASSET_BYTES, allowed_hosts={"api.github.com"})
    document = parse_json(raw, "GitHub release API response")
    return document, validate_release_identity(document)


def download_release_assets(output_dir: Path) -> dict[str, Any]:
    require(not output_dir.is_symlink(), "download directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    require(output_dir.is_dir(), "download destination is not a directory")
    require(not any(output_dir.iterdir()), "download directory must be empty to avoid overwriting existing files")
    _, assets = fetch_release_metadata()
    total = 0
    for name in EXPECTED_ASSETS:
        item = assets[name]
        url = item["browser_download_url"]
        content = fetch_bytes(url, accept="application/octet-stream", limit=MAX_ASSET_BYTES, allowed_hosts=ALLOWED_DOWNLOAD_HOSTS)
        require(len(content) == item["size"], f"GitHub asset size mismatch: {name}")
        total += len(content)
        require(total <= MAX_TOTAL_ASSET_BYTES, "GitHub release asset set exceeds the total download limit")
        destination = output_dir / name
        with destination.open("xb") as stream:
            stream.write(content)
    return {"release_api": "VERIFIED", "downloaded_assets": len(assets), "download_directory": str(output_dir)}


def validate_debian_identity(fields: dict[str, str]) -> None:
    require(fields.get("Package") == DEBIAN_PACKAGE, f"wrong package identifier: {fields.get('Package')}")
    require(fields.get("Version") == PACKAGE_VERSION, f"unexpected Debian package version: {fields.get('Version')}")
    require(fields.get("Architecture") == DEBIAN_ARCHITECTURE, f"wrong Debian architecture: {fields.get('Architecture')}")


def debian_fields(package: Path) -> dict[str, str]:
    require(shutil.which("dpkg-deb") is not None, "dpkg-deb is required for Debian metadata inspection")
    result = subprocess.run(
        ["dpkg-deb", "--field", str(package)],
        text=True,
        capture_output=True,
        check=False,
    )
    require(result.returncode == 0, "dpkg-deb could not read the package control metadata")
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            if key in {"Package", "Version", "Architecture"}:
                require(key not in fields, f"duplicate Debian control field: {key}")
                fields[key] = value.strip()
    return fields


def validate_profile_identity(signing: dict[str, Any], *, require_embedded: bool, require_path: bool = True) -> None:
    require(signing.get("profile_id") == PROFILE_ID, "signing metadata does not name the approved Amethyst iOS 12 rootful profile")
    if require_path:
        require(signing.get("profile_path") == PROFILE_RELATIVE_PATH.as_posix(), "signing metadata points to an unexpected profile path")
    require(signing.get("profile_sha256") == EXPECTED_PROFILE_SHA256, "signing metadata profile SHA-256 mismatch")
    if require_embedded:
        require(signing.get("signing_tool_version") == EXPECTED_SIGNER_VERSION, "signing metadata tool version mismatch")
        require(signing.get("signing_tool_sha256") == EXPECTED_SIGNER_SHA256, "signing metadata tool SHA-256 mismatch")
        require(signing.get("embedded_entitlements") == "EXACT_MATCH", "release manifest does not record exact embedded entitlement matching")
    profile, digest = load_approved_profile(ROOT / PROFILE_RELATIVE_PATH)
    require(profile == {"com.apple.private.security.no-container": True}, "versioned profile entitlement set is unexpected")
    require(digest == EXPECTED_PROFILE_SHA256, "repository signing profile differs from the published v0.1.0 profile")


def validate_release_manifests(asset_dir: Path, package_sha: str, package_sidecar: dict[str, Any]) -> dict[str, Any]:
    release = read_json(asset_dir / "P010-RELEASE-MANIFEST.json", "P010 release manifest")
    candidate = read_json(asset_dir / "P010-SIGNED-CANDIDATE-MANIFEST.json", "P010 signed-candidate manifest")
    require(release.get("manifest_version") == 1 and candidate.get("manifest_version") == 1, "unsupported P010 manifest version")
    require(release.get("release_candidate") == TAG and candidate.get("release_candidate") == TAG, "P010 manifest release tag mismatch")
    require(release.get("package_version") == PACKAGE_VERSION and candidate.get("package_version") == PACKAGE_VERSION, "P010 manifest Debian version mismatch")
    for manifest in (release, candidate):
        source = manifest.get("source")
        require(isinstance(source, dict), "P010 manifest source record is malformed")
        require(source.get("repository") == REPOSITORY and source.get("commit_sha") == SOURCE_COMMIT, "P010 manifest source identity mismatch")
    require(release.get("release_authorization_status") == "BLOCKED", "P010 release manifest overstates release authorization")
    require(release.get("stable_v0_1_0_authorization_status") == "BLOCKED", "P010 stable authorization must remain blocked")
    release_signing = release.get("signing")
    candidate_signing = candidate.get("signing")
    require(isinstance(release_signing, dict) and isinstance(candidate_signing, dict), "P010 signing manifest data is malformed")
    validate_profile_identity(release_signing, require_embedded=False)
    validate_profile_identity(candidate_signing, require_embedded=True)
    require(candidate_signing.get("signature_integrity") == "PENDING", "P010 signature-integrity state differs from the published record")
    require(candidate_signing.get("signature_integrity") == "PENDING", "P010 signature-integrity state differs from the published record")
    require(candidate.get("device_execution") == "NOT_VERIFIED", "P010 candidate overstates device execution")
    require(candidate.get("device_package_acceptance") == "NOT_ACCEPTED", "P010 candidate overstates device package acceptance")
    require(candidate.get("release_authorization_status") == "BLOCKED", "P010 candidate overstates release authorization")
    require(candidate.get("stable_v0_1_0_authorization_status") == "BLOCKED", "P010 candidate overstates stable authorization")
    evidence = candidate.get("device_evidence")
    require(isinstance(evidence, dict), "P010 device evidence record is malformed")
    require(evidence.get("device_execution_verification") == "PENDING_P009_REVIEW", "P010 device execution review state is unexpected")
    require(evidence.get("device_package_acceptance") == "PENDING", "P010 device package acceptance must remain pending")
    artifacts = candidate.get("artifacts")
    require(isinstance(artifacts, dict), "P010 signed-candidate artifact record is malformed")
    signed_package = artifacts.get("signed_candidate_package")
    require(isinstance(signed_package, dict), "P010 signed package record is malformed")
    require(signed_package.get("path") == PACKAGE_FILENAME, "P010 candidate names a different package")
    require(signed_package.get("sha256") == package_sha == EXPECTED_PACKAGE_SHA256, "P010 candidate package hash mismatch")
    require(signed_package.get("architecture") == DEBIAN_ARCHITECTURE, "P010 candidate package architecture mismatch")
    final_hashes = package_sidecar.get("signing", {}).get("final_binary_sha256", {})
    require(artifacts.get("final_signed_binaries") == {
        "ios-caffeinate_sha256": final_hashes.get("ios-caffeinate"),
        "ios-caffeinated_sha256": final_hashes.get("ios-caffeinated"),
    }, "P010 final binary hashes differ from the package sidecar")
    require(artifacts.get("unsigned_ci_binaries") == {
        "ios-caffeinate_sha256": package_sidecar["signing"]["source_binary_sha256"]["ios-caffeinate"],
        "ios-caffeinated_sha256": package_sidecar["signing"]["source_binary_sha256"]["ios-caffeinated"],
    }, "P010 unsigned source binary hashes differ from the package sidecar")
    return candidate


def validate_package_checksum_sidecar(asset_dir: Path, package_sha: str) -> None:
    sidecar = asset_dir / f"{PACKAGE_FILENAME}.sha256"
    require(not sidecar.is_symlink() and sidecar.is_file(), "package SHA-256 sidecar is missing or unsafe")
    require(sidecar.stat().st_size <= 1024, "package SHA-256 sidecar exceeds its size limit")
    raw = sidecar.read_text(encoding="utf-8")
    expected = f"{package_sha}  {PACKAGE_FILENAME}\n"
    require(raw == expected, "package SHA-256 sidecar does not exactly match the published package")


def validate_package_build_manifest(package_sidecar: dict[str, Any], package_sha: str) -> dict[str, Any]:
    require(package_sidecar.get("schema_version") == 1, "unsupported package sidecar schema")
    require(package_sidecar.get("package_identifier") == DEBIAN_PACKAGE, "package sidecar identity mismatch")
    require(package_sidecar.get("package_version") == PACKAGE_VERSION, "package sidecar version mismatch")
    require(package_sidecar.get("architecture") == DEBIAN_ARCHITECTURE, "package sidecar Debian architecture mismatch")
    require(package_sidecar.get("source_commit_sha") == SOURCE_COMMIT, "package sidecar source commit mismatch")
    require(package_sidecar.get("source_tree_clean") is True, "package sidecar does not record a clean source tree")
    require(package_sidecar.get("package") == {"file": PACKAGE_FILENAME, "sha256": package_sha}, "package sidecar filename or SHA-256 mismatch")
    signing = package_sidecar.get("signing")
    require(isinstance(signing, dict), "package sidecar signing record is malformed")
    require(signing.get("state") == "SIGNATURE_PRESENT", "unsigned or unrecognized package rejected")
    validate_profile_identity(signing, require_embedded=True, require_path=False)
    require(signing.get("signature_verification") == "PENDING", "package sidecar signature-verification state is unexpected")
    require(signing.get("device_execution_verification") == "NOT_VERIFIED", "package sidecar overstates device execution")
    require(signing.get("device_package_acceptance") == "NOT_ACCEPTED", "package sidecar overstates device package acceptance")
    return signing


def validate_human_validation_report(asset_dir: Path, package_sha: str) -> dict[str, str]:
    path = asset_dir / "signed-validation.txt"
    require(not path.is_symlink() and path.is_file(), "signed-validation.txt is missing or not regular")
    require(path.stat().st_size <= MAX_ASSET_BYTES, "signed-validation.txt exceeds its size limit")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        require(key not in values, f"signed-validation.txt has a duplicate field: {key}")
        values[key] = value
    expected = {
        "package": DEBIAN_PACKAGE,
        "version": PACKAGE_VERSION,
        "architecture": DEBIAN_ARCHITECTURE,
        "artifact_sha256": package_sha,
        "signing_state": "SIGNATURE_PRESENT",
        "embedded_entitlements": "EXACT_MATCH",
        "signature_verification": "PENDING",
        "device_execution": "NOT_VERIFIED",
        "device_package_acceptance": "NOT_ACCEPTED",
        "package_installation": "NOT-PERFORMED",
        "device_validation": "UNVERIFIED",
        "result": "PASS",
    }
    for key, value in expected.items():
        require(values.get(key) == value, f"signed-validation.txt mismatch: {key}")
    return values


def hardware_gate_report() -> dict[str, Any]:
    """Return P009-vocabulary hardware gates with no supplied physical evidence."""
    gate_names = (
        "device_identity_verified", "ios_runtime_verified", "package_integrity_verified",
        "signature_acceptance_verified", "installation_verified", "rollback_verified",
        "iokit_acquire_verified", "iokit_release_verified", "bounded_hold_verified",
        "explicit_stop_verified", "natural_expiry_verified", "sigterm_cleanup_verified",
        "screen_locked_lan_verified", "screen_locked_tailscale_verified", "authenticated_ssh_verified",
        "independent_observer_verified", "battery_observation_available", "thermal_observation_available",
        "physical_recovery_confirmed", "launchd_remains_disabled", "no_unresolved_assertion",
        "scheduled_wake_verified",
    )
    states = {name: "PENDING" for name in gate_names}
    return {
        "gate_states": states,
        "device_acceptance": "PENDING",
        "release_authorization": "BLOCKED" if any(state != "PASS" for state in states.values()) else "REVIEW_REQUIRED",
        "unattended_24_7": "NOT_VALIDATED",
        "scheduled_wake": "UNVERIFIED",
    }


def verify_local_assets(package_path: Path, asset_dir: Path, ldid: Path | None) -> dict[str, Any]:
    require(not asset_dir.is_symlink() and asset_dir.is_dir(), "release asset directory is missing or unsafe")
    require(package_path.name == PACKAGE_FILENAME, "package filename does not match the published v0.1.0 asset")
    require(not package_path.is_symlink() and package_path.is_file(), "package is missing or not a regular file")
    require(package_path.parent.resolve() == asset_dir.resolve(), "package and release sidecars must be in the same asset directory")
    require(package_path.stat().st_size == EXPECTED_PACKAGE_SIZE, "package size differs from the published v0.1.0 asset")
    actual_package_sha = sha256(package_path)
    require(actual_package_sha == EXPECTED_PACKAGE_SHA256, "signed package SHA-256 differs from the published v0.1.0 release")
    missing = [name for name in EXPECTED_ASSETS if not (asset_dir / name).is_file() or (asset_dir / name).is_symlink()]
    require(not missing, "required stable release asset(s) are missing or unsafe: " + ", ".join(missing))
    debian_identity = debian_fields(package_path)
    validate_debian_identity(debian_identity)
    validate_package_checksum_sidecar(asset_dir, actual_package_sha)
    package_sidecar = read_json(asset_dir / f"{PACKAGE_FILENAME}.manifest.json", "package build manifest")
    signing = validate_package_build_manifest(package_sidecar, actual_package_sha)
    candidate = validate_release_manifests(asset_dir, actual_package_sha, package_sidecar)
    validation_report = validate_human_validation_report(asset_dir, actual_package_sha)

    if ldid is not None:
        require(ldid.is_absolute() and not ldid.is_symlink() and ldid.is_file(), "--ldid must be an absolute regular executable path")
    require(shutil.which("dpkg-deb") is not None, "dpkg-deb is required by the existing P010 package validator")
    p010_status = "PASS"
    p010_report_lines: list[str] = []
    p010_blocker = None
    try:
        p010_report_lines = inspect_package(package_path, ldid).splitlines()
    except ValueError as error:
        detail = str(error)
        exact_signer_gate = detail.startswith((
            "BLOCKED:",
            "validator ldid SHA-256 differs from signing tool recorded by builder",
            "validator ldid version differs from signing tool recorded by builder",
        ))
        if not exact_signer_gate:
            raise
        p010_status = "BLOCKED"
        p010_blocker = detail if detail.startswith("BLOCKED:") else f"BLOCKED: {detail}"
    return {
        "package_sha256": actual_package_sha,
        "package_size_bytes": package_path.stat().st_size,
        "debian": debian_identity,
        "profile_id": PROFILE_ID,
        "profile_sha256": EXPECTED_PROFILE_SHA256,
        "signer_version": EXPECTED_SIGNER_VERSION,
        "signer_sha256": EXPECTED_SIGNER_SHA256,
        "signing_state": signing["state"],
        "published_manifest_embedded_entitlements": signing["embedded_entitlements"],
        "p010_embedded_entitlement_reinspection": "EXACT_MATCH" if p010_status == "PASS" else "PENDING_HOST_LDID_VALIDATION",
        "signature_verification": signing["signature_verification"],
        "cryptographic_trust": "NOT_ESTABLISHED_BY_SIGNATURE_PRESENCE_OR_THIS_PREFLIGHT",
        "p010_validator": p010_status,
        "p010_blocker": p010_blocker,
        "p010_report": p010_report_lines,
        "p010_signed_candidate_manifest": candidate["release_candidate"],
        "signed_validation_report": validation_report["result"],
    }


def initial_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "BLOCKED",
        "release": {"repository": REPOSITORY, "tag": TAG, "url": RELEASE_URL, "release_channel": "PUBLIC_STABLE"},
        "package": {
            "file": PACKAGE_FILENAME,
            "expected_sha256": EXPECTED_PACKAGE_SHA256,
            "identity": DEBIAN_PACKAGE,
            "version": PACKAGE_VERSION,
            "architecture": DEBIAN_ARCHITECTURE,
        },
        "checks": {},
        "errors": [],
        "hardware": hardware_gate_report(),
    }


def human_report(report: dict[str, Any]) -> str:
    lines = [
        "P011 v0.1.0 release preflight",
        f"release={report['release']['repository']}@{report['release']['tag']} ({report['release']['release_channel']})",
        f"status={report['status']}",
    ]
    package = report.get("verified_package")
    if isinstance(package, dict):
        lines.extend([
            f"package={package['debian']['Package']} version={package['debian']['Version']} architecture={package['debian']['Architecture']}",
            f"package_sha256={package['package_sha256']}",
            f"profile={package['profile_id']} profile_sha256={package['profile_sha256']}",
            f"published_manifest_embedded_entitlements={package['published_manifest_embedded_entitlements']}",
            f"p010_embedded_entitlement_reinspection={package['p010_embedded_entitlement_reinspection']}",
            f"signature_verification={package['signature_verification']}",
            f"cryptographic_trust={package['cryptographic_trust']}",
            f"p010_package_validator={package['p010_validator']}",
        ])
    lines.extend([
        f"device_package_acceptance={report['hardware']['device_acceptance']}",
        f"release_authorization={report['hardware']['release_authorization']}",
        f"unattended_24_7={report['hardware']['unattended_24_7']}",
        f"scheduled_wake={report['hardware']['scheduled_wake']}",
    ])
    lines.extend(f"error={error}" for error in report["errors"])
    return "\n".join(lines)


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite JSON report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--package", type=Path, help="local published .deb; all release sidecars must be adjacent")
    source.add_argument("--download", action="store_true", help="retrieve the exact public v0.1.0 release assets through GitHub HTTPS")
    parser.add_argument("--asset-dir", type=Path, help="directory containing the package and all official release sidecars")
    parser.add_argument("--download-dir", type=Path, help="empty directory for assets downloaded by --download")
    parser.add_argument("--ldid", type=Path, help="host-compatible ldid matching the signer version and SHA-256 recorded by P010")
    parser.add_argument("--json", action="store_true", help="write the machine-readable report to stdout")
    parser.add_argument("--json-out", type=Path, help="also write a machine-readable JSON report without overwriting a file")
    args = parser.parse_args(argv)
    report = initial_report()
    try:
        if args.download:
            require(args.download_dir is not None, "--download requires --download-dir")
            report["checks"].update(download_release_assets(args.download_dir.absolute()))
            asset_dir = args.download_dir.absolute()
            package_path = asset_dir / PACKAGE_FILENAME
        else:
            require(args.package is not None, "--package is required for local verification")
            package_path = args.package
            asset_dir = args.asset_dir if args.asset_dir is not None else package_path.parent
            require(not package_path.is_symlink(), "package path must not be a symlink")
            package_path = package_path.absolute()
            asset_dir = asset_dir.absolute()
        verified = verify_local_assets(package_path, asset_dir, args.ldid.absolute() if args.ldid else None)
        report["verified_package"] = verified
        report["checks"].update({
            "stable_release_identity": "VERIFIED_BY_PINNED_TAG_AND_ASSETS",
            "expected_package_sha256": "MATCH",
            "debian_identity": "MATCH",
            "package_sidecars_and_manifests": "MATCH",
            "approved_signing_profile_identity": "MATCH",
            "p010_package_validation": verified["p010_validator"],
        })
        if verified["p010_validator"] == "PASS":
            report["status"] = "CLOUD_VERIFIED_DEVICE_ACCEPTANCE_PENDING"
        else:
            report["status"] = "CLOUD_ARTIFACT_VERIFIED_P010_VALIDATION_BLOCKED"
            report["errors"].append(verified["p010_blocker"] or "P010 package validation is blocked")
    except (PreflightError, OSError, subprocess.SubprocessError, tarfile.TarError, ValueError) as error:
        message = str(error).strip() or type(error).__name__
        report["errors"].append(message)
    if args.json_out:
        try:
            write_json_exclusive(args.json_out, report)
        except (PreflightError, OSError) as error:
            report["errors"].append(str(error))
            report["status"] = "BLOCKED"
    output = json.dumps(report, indent=2, sort_keys=True) if args.json else human_report(report)
    print(output)
    return 0 if report["status"] == "CLOUD_VERIFIED_DEVICE_ACCEPTANCE_PENDING" else 1


if __name__ == "__main__":
    sys.exit(main())
