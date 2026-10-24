#!/usr/bin/env python3
"""Inspect a rootful Debian artifact without installing it."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from macho_ios import validate_ios12_arm64
from macho_code_signature import CodeSignatureError, audit_code_signature
from signing_profile import (
    PROFILE_ID,
    SigningError,
    load_approved_profile,
    require_exact_embedded_entitlements,
    signer_identity,
    validate_signer,
)


PACKAGE = "com.ioscaffeinate.cli"
VERSION = (Path(__file__).resolve().parents[1] / "packaging/rootful/VERSION").read_text().strip()
REQUIRED_HASHES = {
    "usr/local/bin/ios-caffeinate",
    "usr/local/bin/ios-caffeinated",
    "usr/local/libexec/ioscaffeinate-manager",
    "usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist",
    "usr/share/ioscaffeinate/SIGNING-STATE",
    "usr/share/ioscaffeinate/package-build.json",
    "usr/share/doc/ioscaffeinate/tools/p009_evidence.py",
    "usr/share/doc/ioscaffeinate/tools/p018_evidence.py",
    "usr/share/doc/ioscaffeinate/tools/p018_validate_export.py",
    "usr/share/doc/ioscaffeinate/tools/p018_package_preflight.py",
}
SIGNING_PROFILE_PATH = "usr/share/ioscaffeinate/signing/amethyst-ios12-rootful.plist"
EXPECTED_DEPENDENCIES = {
    "usr/local/bin/ios-caffeinate": {
        "/usr/lib/libSystem.B.dylib",
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    },
    "usr/local/bin/ios-caffeinated": {
        "/usr/lib/libSystem.B.dylib",
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    },
}
FORBIDDEN_SCRIPT_PATTERNS = (
    re.compile(r"\blaunchctl\s+(?:load|bootstrap|enable|kickstart)\b", re.I),
    re.compile(r"\b(?:reboot|respring)\b", re.I),
    re.compile(r"\b(?:curl|wget)\b", re.I),
    re.compile(r"\brm\s+-rf\b", re.I),
    re.compile(r"\b(?:killall|pkill)\b", re.I),
    re.compile(r"\b(?:chown|chmod)\s+-R\b", re.I),
    re.compile(r"\b(?:launchctl|systemctl)\s+(?:start|restart|enable)\b", re.I),
    re.compile(r"\b(?:exec|nohup)\s+(?:/usr/local/bin/)?ios-caffeinated\b", re.I),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key in package manifest: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_pairs)
    require(isinstance(value, dict), f"package manifest must be a JSON object: {path.name}")
    return value


def normalized_member_path(name: str) -> str:
    require(not name.startswith("/"), f"absolute archive path: {name}")
    parts = PurePosixPath(name).parts
    require(".." not in parts, f"traversal archive path: {name}")
    normalized = "/".join(part for part in parts if part not in (".", ""))
    if not normalized:
        return "."
    require(normalized != "DEBIAN", f"invalid installed path: {name}")
    require(not normalized.startswith("DEBIAN/"), f"control file leaked into data archive: {name}")
    return normalized.rstrip("/")


def validate_archive_members(members: list[tarfile.TarInfo]) -> dict[str, tarfile.TarInfo]:
    entries: dict[str, tarfile.TarInfo] = {}
    for member in members:
        path = normalized_member_path(member.name)
        require(path not in entries, f"duplicate installed path: {path}")
        require(member.uid == 0 and member.gid == 0, f"package path is not root-owned: {path}")
        require(member.isfile() or member.isdir() or member.issym(), f"unsupported package entry type: {path}")
        if member.issym():
            require(path == "usr/local/bin/ic" and member.linkname == "ios-caffeinate", f"unexpected package symlink: {path} -> {member.linkname}")
            require(not member.linkname.startswith("/"), f"absolute symlink target: {path} -> {member.linkname}")
            resolved = PurePosixPath(path).parent.joinpath(member.linkname)
            stack: list[str] = []
            for part in resolved.parts:
                if part in ("", "."):
                    continue
                if part == "..":
                    require(bool(stack), f"symlink escapes package root: {path} -> {member.linkname}")
                    stack.pop()
                else:
                    stack.append(part)
        entries[path] = member
    return entries


def expected_package_paths(source_commit_sha: str | None = None, source_tree_clean: bool | None = None) -> set[str]:
    root = Path(__file__).resolve().parents[1]
    files = {
        "usr/local/bin/ios-caffeinate",
        "usr/local/bin/ios-caffeinated",
        "usr/local/bin/ic",
        "usr/local/libexec/ioscaffeinate-manager",
        "usr/share/ioscaffeinate/SHA256SUMS",
        "usr/share/ioscaffeinate/SIGNING-STATE",
        "usr/share/ioscaffeinate/package-build.json",
        "usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist",
        "usr/share/doc/ioscaffeinate/README.md",
        "usr/share/doc/ioscaffeinate/LICENSE",
        "usr/share/doc/ioscaffeinate/tools/p009_evidence.py",
        "usr/share/doc/ioscaffeinate/tools/p018_evidence.py",
        "usr/share/doc/ioscaffeinate/tools/p018_validate_export.py",
        "usr/share/doc/ioscaffeinate/tools/p018_package_preflight.py",
    }
    document_paths: set[str] = set()
    if source_commit_sha is not None and source_tree_clean is True:
        require(re.fullmatch(r"[0-9a-f]{40}", source_commit_sha) is not None, "package source SHA is invalid")
        try:
            tree = subprocess.run(
                ["git", "ls-tree", "-r", "-z", "--full-tree", source_commit_sha, "--", "docs"],
                cwd=root,
                check=False,
                capture_output=True,
            )
        except OSError as error:
            raise ValueError(f"BLOCKED: git is required to inspect the clean package source tree: {error}") from None
        require(tree.returncode == 0, "BLOCKED: package source commit is unavailable for exact documentation validation")
        for record in tree.stdout.split(b"\0"):
            if not record:
                continue
            metadata, separator, raw_path = record.partition(b"\t")
            require(bool(separator), "invalid git tree entry while checking packaged documentation")
            mode = metadata.split(b" ", 1)[0]
            if mode not in (b"100644", b"100755"):
                continue
            try:
                relative = raw_path.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("package documentation path is not valid UTF-8") from None
            require(relative.startswith("docs/") and ".." not in PurePosixPath(relative).parts, "unsafe documentation path in package source tree")
            document_paths.add(relative)
    else:
        for source in (root / "docs").rglob("*"):
            if source.is_file() and not source.is_symlink():
                document_paths.add(source.relative_to(root).as_posix())
    for relative in document_paths:
        files.add("usr/share/doc/ioscaffeinate/" + relative)
    directories = {"var", "var/lib", "var/lib/ioscaffeinate", "var/log", "var/log/ioscaffeinate"}
    for file_path in files:
        parent = PurePosixPath(file_path).parent
        while parent.parts:
            directories.add(parent.as_posix())
            parent = parent.parent
    return files | directories | {"."}


def validate_package_path_set(actual_paths: set[str], expected_paths: set[str]) -> None:
    require(actual_paths == expected_paths, "package file manifest differs from the approved payload layout")


def validate_installed_modes(entries: dict[str, tarfile.TarInfo]) -> None:
    for path, member in entries.items():
        if member.isdir():
            if path == ".":
                continue
            expected = 0o750 if path in ("var/lib/ioscaffeinate", "var/log/ioscaffeinate") else 0o755
            require(member.mode & 0o777 == expected, f"wrong directory mode for {path}")
        elif member.isfile():
            expected = 0o755 if path in (
                "usr/local/bin/ios-caffeinate",
                "usr/local/bin/ios-caffeinated",
                "usr/local/libexec/ioscaffeinate-manager",
            ) else 0o644
            require(member.mode & 0o777 == expected, f"wrong file mode for {path}")


def check_script_safety(script: Path) -> None:
    text = script.read_text()
    for pattern in FORBIDDEN_SCRIPT_PATTERNS:
        require(not pattern.search(text), f"unsafe maintainer script command in {script.name}: {pattern.pattern}")
    result = subprocess.run(["sh", "-n", str(script)], text=True, capture_output=True)
    require(result.returncode == 0, f"maintainer script syntax error in {script.name}: {result.stderr.strip()}")


def check_sha_manifest(root: Path) -> set[str]:
    manifest = root / "usr/share/ioscaffeinate/SHA256SUMS"
    require(manifest.is_file(), "packaged SHA256SUMS is missing")
    records: dict[str, str] = {}
    for line_number, line in enumerate(manifest.read_text().splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)", line)
        require(match is not None, f"invalid packaged SHA256SUMS line {line_number}")
        assert match is not None
        digest, relative = match.groups()
        require(relative not in records, f"duplicate checksum entry: {relative}")
        records[relative] = digest
        path = root / relative
        require(path.is_file() and not path.is_symlink(), f"checksum target missing or not regular: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        require(actual == digest, f"packaged SHA-256 mismatch: {relative}")
    expected = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path != manifest
    }
    require(set(records) == expected, "packaged SHA256SUMS must cover the approved payload and signing metadata")
    return set(records)


def read_key_values(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        require("=" in line, f"invalid signing-state line {line_number}")
        key, value = line.split("=", 1)
        require(key and key not in fields, f"duplicate or empty signing-state key at line {line_number}")
        fields[key] = value
    return fields


def inspect_package(deb: Path, ldid: Path | None = None, expected_version: str | None = None) -> str:
    expected_version = VERSION if expected_version is None else expected_version
    require(deb.is_file() and not deb.is_symlink(), f"package artifact missing or not regular: {deb}")
    require(shutil.which("dpkg-deb") is not None, "dpkg-deb is required for package inspection")
    fields = {}
    for key in ("Package", "Version", "Architecture", "Section", "Priority", "Maintainer", "Description", "Depends"):
        result = subprocess.run(["dpkg-deb", "--field", str(deb), key], text=True, capture_output=True)
        if result.returncode == 0:
            fields[key] = result.stdout.strip()
    require(fields.get("Package") == PACKAGE, f"wrong package identifier: {fields.get('Package')}")
    require(fields.get("Version") == expected_version, f"wrong package version: {fields.get('Version')}")
    require(fields.get("Architecture") == "iphoneos-arm", f"wrong Debian architecture: {fields.get('Architecture')}")
    require(fields.get("Section") == "utils" and fields.get("Priority") == "optional", "unexpected package section or priority")
    require(fields.get("Maintainer", "").startswith("iOS-Caffeinate contributors <"), "unexpected maintainer metadata")
    require("rootful" in fields.get("Description", "").lower(), "package description does not identify rootful use")
    require(not fields.get("Depends"), "unexpected runtime package dependency")

    tar_bytes = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(deb)], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as archive:
        entries = validate_archive_members(archive.getmembers())
        signed_profile_present = SIGNING_PROFILE_PATH in entries
        for path, expected_mode in (
            ("usr/local/bin/ios-caffeinate", 0o755),
            ("usr/local/bin/ios-caffeinated", 0o755),
            ("usr/local/libexec/ioscaffeinate-manager", 0o755),
        ):
            require(path in entries and entries[path].isfile(), f"required executable missing: {path}")
            require(entries[path].mode & 0o777 == expected_mode, f"wrong executable mode for {path}")
        require("usr/local/bin/ic" in entries and entries["usr/local/bin/ic"].issym(), "ic is not packaged as a symlink")
        require(entries["usr/local/bin/ic"].linkname == "ios-caffeinate", "ic symlink does not point to the packaged CLI")
        require("usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist" in entries, "staged launchd template missing")
        require("usr/share/ioscaffeinate/package-build.json" in entries, "package signing/build manifest missing")
        require(not any(path.startswith("Library/LaunchDaemons/") for path in entries), "active LaunchDaemons path is forbidden in package")
        require(not any(path.endswith("/schedules.json") or path.endswith("/server-mode.json") for path in entries), "persistent state was seeded into package")
        require(not any(path.startswith("var/lib/ioscaffeinate/") and not entries[path].isdir() for path in entries), "package contains persistent state under /var/lib")
        for path in entries:
            require(not re.search(r"(?:^|/)(?:mock|linux-mock)(?:[-.]|$)", path, re.I), f"mock binary path in package: {path}")

    with tempfile.TemporaryDirectory(prefix="ioscaffeinate-deb-check-") as temporary:
        root = Path(temporary) / "root"
        control = Path(temporary) / "control"
        root.mkdir()
        control.mkdir()
        subprocess.run(["dpkg-deb", "--extract", str(deb), str(root)], check=True)
        subprocess.run(["dpkg-deb", "--control", str(deb), str(control)], check=True)
        check_sha_manifest(root)
        (root / "usr/local/bin/ios-caffeinate").chmod(0o755)
        (root / "usr/local/bin/ios-caffeinated").chmod(0o755)
        package_build = read_json(root / "usr/share/ioscaffeinate/package-build.json")
        require(package_build.get("schema_version") == 1, "unsupported package build manifest version")
        require(package_build.get("package_identifier") == PACKAGE, "package build manifest identity mismatch")
        require(package_build.get("package_version") == fields["Version"], "package build manifest version mismatch")
        require(package_build.get("architecture") == "iphoneos-arm", "package build manifest architecture mismatch")
        require(re.fullmatch(r"[0-9a-f]{40}", package_build.get("source_commit_sha", "")) is not None, "package build manifest source SHA is missing or invalid")
        expected_paths = expected_package_paths(package_build["source_commit_sha"], package_build.get("source_tree_clean"))
        if signed_profile_present:
            expected_paths.add(SIGNING_PROFILE_PATH)
            expected_paths.add("usr/share/ioscaffeinate/signing")
        validate_package_path_set(set(entries), expected_paths)
        validate_installed_modes(entries)
        signing = package_build.get("signing")
        require(isinstance(signing, dict), "package build manifest signing record is invalid")
        require(type(package_build.get("source_tree_clean")) is bool, "package build manifest tree state is invalid")
        signed_artifact = signing.get("state") == "SIGNATURE_PRESENT"
        require(signing.get("state") in ("SIGNATURE_PRESENT", "UNSIGNED"), "unknown package signature state")
        require(signed_artifact == signed_profile_present, "signed payload and bundled signing profile disagree")
        require(("_SIGNED-DEVICE-UNVERIFIED" in deb.name) == signed_artifact, "artifact filename and signing record disagree")
        cli_info = validate_ios12_arm64(
            root / "usr/local/bin/ios-caffeinate",
            allow_signature=signed_artifact,
            expected_dependencies=EXPECTED_DEPENDENCIES["usr/local/bin/ios-caffeinate"],
        )
        daemon_info = validate_ios12_arm64(
            root / "usr/local/bin/ios-caffeinated",
            allow_signature=signed_artifact,
            expected_dependencies=EXPECTED_DEPENDENCIES["usr/local/bin/ios-caffeinated"],
        )
        require(cli_info.architecture == daemon_info.architecture == "arm64", "binary architecture mismatch")
        state_fields = read_key_values(root / "usr/share/ioscaffeinate/SIGNING-STATE")
        expected_state_keys = {
            "signature_state", "profile_id", "profile_sha256", "embedded_entitlements",
            "signature_verification", "device_execution", "device_package_acceptance",
        }
        if signed_artifact:
            expected_state_keys.update(("signing_tool_version", "signing_tool_sha256"))
        require(set(state_fields) == expected_state_keys, "unexpected or missing signing-state fields")
        require(state_fields.get("signature_state") == ("SIGNATURE_PRESENT" if signed_artifact else "UNSIGNED"), "package signature state is inconsistent")
        require(state_fields.get("signature_verification") in ("SIGNATURE_VERIFIED", "PENDING") if signed_artifact else state_fields.get("signature_verification") == "NOT_APPLICABLE", "package signature-verification state is invalid")
        require(state_fields.get("device_execution") == "NOT_VERIFIED", "package overstates device execution")
        require(state_fields.get("device_package_acceptance") == "NOT_ACCEPTED", "package overstates device package acceptance")
        source_hashes = signing.get("source_binary_sha256")
        final_hashes = signing.get("final_binary_sha256")
        require(isinstance(source_hashes, dict) and set(source_hashes) == {"ios-caffeinate", "ios-caffeinated"}, "source executable hash records are incomplete")
        require(isinstance(final_hashes, dict) and set(final_hashes) == {"ios-caffeinate", "ios-caffeinated"}, "final executable hash records are incomplete")
        for name, relative in (("ios-caffeinate", "usr/local/bin/ios-caffeinate"), ("ios-caffeinated", "usr/local/bin/ios-caffeinated")):
            actual_hash = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            require(isinstance(source_hashes[name], str) and re.fullmatch(r"[0-9a-f]{64}", source_hashes[name]) is not None, f"source executable SHA-256 is invalid: {name}")
            require(isinstance(final_hashes[name], str) and re.fullmatch(r"[0-9a-f]{64}", final_hashes[name]) is not None, f"final executable SHA-256 is invalid: {name}")
            require(final_hashes[name] == actual_hash, f"final executable hash mismatch: {name}")
            require(source_hashes[name] == actual_hash if not signed_artifact else True, f"unsigned payload does not match exact source: {name}")
        if signed_artifact:
            require(signing.get("profile_id") == PROFILE_ID, "unknown signing profile identifier")
            profile, profile_hash = load_approved_profile(root / SIGNING_PROFILE_PATH)
            require(profile == {"com.apple.private.security.no-container": True}, "bundled profile differs from the approved entitlement set")
            require(signing.get("profile_sha256") == profile_hash, "profile SHA-256 differs from package build record")
            require(state_fields.get("profile_id") == PROFILE_ID and state_fields.get("profile_sha256") == profile_hash, "signing-state profile identity mismatch")
            require(signing.get("embedded_entitlements") == "EXACT_MATCH" and state_fields.get("embedded_entitlements") == "EXACT_MATCH", "package build did not record exact embedded entitlement validation")
            for name, relative in (("ios-caffeinate", "usr/local/bin/ios-caffeinate"),
                                   ("ios-caffeinated", "usr/local/bin/ios-caffeinated")):
                try:
                    audit = audit_code_signature((root / relative).read_bytes(), expected_identifier=name)
                except CodeSignatureError as error:
                    raise ValueError(f"BLOCKED: independent Mach-O signature audit failed for {name}: {error}") from None
                require(audit["independent_code_directory_verified"], f"CodeDirectory hashes were not verified: {name}")
                require(audit["entitlements_exact_match"], f"independent entitlement set is not exact: {name}")
                if expected_version == "0.2.0~rc1-1":
                    require(audit["adhoc_flag_present"], f"CodeDirectory lacks Apple's ad hoc flag: {name}")
                    require(signing.get("code_signature_kind") == "ADHOC", "v0.2 RC metadata does not identify an Apple ad hoc signature")
            integrity_record = signing.get("signature_integrity")
            require(isinstance(integrity_record, dict), "signature integrity result is malformed")
            require(signing.get("device_execution_verification") == "NOT_VERIFIED", "package build overstates device execution")
            require(signing.get("device_package_acceptance") == "NOT_ACCEPTED", "package build overstates device acceptance")
            require(integrity_record.get("status") in ("VERIFIED", "PENDING"), "signature integrity status is invalid")
            expected_signature_verification = "SIGNATURE_VERIFIED" if integrity_record.get("status") == "VERIFIED" else "PENDING"
            require(signing.get("signature_verification") == expected_signature_verification, "signature verification state is inconsistent")
            require(state_fields.get("signature_verification") == expected_signature_verification, "package signing-state verification field is inconsistent")
            require(signing.get("signing_tool_version") and signing.get("signing_tool_sha256"), "signer version or hash is missing")
            require(isinstance(signing["signing_tool_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", signing["signing_tool_sha256"]) is not None, "signer SHA-256 is invalid")
            if ldid is None:
                raise ValueError("BLOCKED: signed package needs explicit host-compatible ldid for embedded entitlement verification")
            try:
                signer = validate_signer(ldid)
                extracted_version, extracted_hash = signer_identity(signer)
                require(extracted_hash == signing["signing_tool_sha256"], "validator ldid SHA-256 differs from signing tool recorded by builder")
                require(extracted_version == signing["signing_tool_version"], "validator ldid version differs from signing tool recorded by builder")
                require_exact_embedded_entitlements(signer, root / "usr/local/bin/ios-caffeinate")
                require_exact_embedded_entitlements(signer, root / "usr/local/bin/ios-caffeinated")
            except SigningError as error:
                raise ValueError(f"BLOCKED: signed package entitlement verification failed: {error}") from None
        else:
            require(signing.get("profile_id") is None and signing.get("profile_sha256") is None, "unsigned payload contains signing-profile claims")
            require(signing.get("embedded_entitlements") == "NOT_APPLICABLE", "unsigned package has an invalid entitlement state")
            require(signing.get("signature_verification") == "NOT_APPLICABLE", "unsigned package has a signature-verification claim")
            require(state_fields.get("signature_verification") == "NOT_APPLICABLE", "unsigned package has a signature-verification state")
        launchd_data = plistlib.loads((root / "usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist").read_bytes())
        require(launchd_data.get("Disabled") is True and launchd_data.get("RunAtLoad") is False, "launchd template is not inactive")
        scripts = sorted(path for path in control.iterdir() if path.name in ("preinst", "prerm", "postinst", "postrm", "config"))
        require({path.name for path in scripts} == {"preinst", "prerm"}, "package must contain only the necessary preinst and prerm scripts")
        for script in scripts:
            require(script.stat().st_mode & 0o777 == 0o755, f"maintainer script is not executable: {script.name}")
            check_script_safety(script)
        preinst_text = (control / "preinst").read_text()
        checked_paths = set(re.findall(r"check_owned_or_absent '([^']+)'", preinst_text))
        incoming_files = {"/" + path for path, member in entries.items() if member.isfile() or member.issym()}
        require(incoming_files <= checked_paths, "preinst does not guard every incoming package file against collision")
        require("launchctl" not in preinst_text.lower() and "launchctl" not in (control / "prerm").read_text().lower(), "maintainer scripts must not control launchd")
        require("schedules.json" not in preinst_text and "server-mode.json" not in preinst_text, "maintainer scripts must not modify persistent state")

    package_hash = hashlib.sha256(deb.read_bytes()).hexdigest()
    sidecar = Path(str(deb) + ".sha256")
    require(sidecar.is_file() and not sidecar.is_symlink(), "package SHA-256 sidecar is missing or not regular")
    match = re.fullmatch(r"([0-9a-f]{64})  ([^\n]+)\n?", sidecar.read_text())
    require(match is not None and match.group(1) == package_hash, "package SHA-256 sidecar mismatch")
    require(match.group(2) == deb.name, "package SHA-256 sidecar names another artifact")
    build_manifest_path = Path(str(deb) + ".manifest.json")
    require(build_manifest_path.is_file() and not build_manifest_path.is_symlink(), "package build manifest sidecar is missing or not regular")
    build_manifest = read_json(build_manifest_path)
    sidecar_package = build_manifest.get("package")
    require(isinstance(sidecar_package, dict), "package build manifest sidecar package field is invalid")
    require(sidecar_package.get("file") == deb.name and sidecar_package.get("sha256") == package_hash, "package build manifest sidecar hash mismatch")
    require(build_manifest.get("source_commit_sha") == package_build.get("source_commit_sha"), "external and embedded source commit records disagree")
    require(build_manifest.get("signing") == package_build.get("signing"), "external and embedded signing records disagree")
    for key in ("package_identifier", "package_version", "architecture", "source_tree_clean"):
        require(build_manifest.get(key) == package_build.get(key), f"external and embedded package metadata disagree: {key}")
    files_sidecar = Path(str(deb) + ".files.sha256")
    require(files_sidecar.is_file() and not files_sidecar.is_symlink(), "package payload checksum sidecar is missing or not regular")
    with tempfile.TemporaryDirectory(prefix="ioscaffeinate-sidecar-check-") as temporary:
        extracted = Path(temporary) / "root"
        extracted.mkdir()
        subprocess.run(["dpkg-deb", "--extract", str(deb), str(extracted)], check=True)
        require(files_sidecar.read_text() == (extracted / "usr/share/ioscaffeinate/SHA256SUMS").read_text(), "package payload checksum sidecar differs from package")
    report_sidecar = Path(str(deb) + ".manifest.txt")
    require(report_sidecar.is_file() and not report_sidecar.is_symlink(), "human-readable package manifest sidecar is missing or not regular")
    require(f"artifact_sha256: {package_hash}" in report_sidecar.read_text(), "human-readable package manifest hash mismatch")
    return "\n".join(
        [
            f"package={fields['Package']}",
            f"version={fields['Version']}",
            f"architecture={fields['Architecture']}",
            f"artifact_sha256={hashlib.sha256(deb.read_bytes()).hexdigest()}",
            f"cli_macho=arm64 {cli_info.platform} min={cli_info.minimum_os_text} signed={cli_info.has_code_signature}",
            f"daemon_macho=arm64 {daemon_info.platform} min={daemon_info.minimum_os_text} signed={daemon_info.has_code_signature}",
            f"signing_state={'SIGNATURE_PRESENT' if signed_artifact else 'UNSIGNED'}",
            f"embedded_entitlements={'EXACT_MATCH' if signed_artifact else 'NOT_APPLICABLE'}",
            f"signature_verification={signing.get('signature_verification', 'NOT_APPLICABLE')}",
            "device_execution=NOT_VERIFIED",
            "device_package_acceptance=NOT_ACCEPTED",
            f"package_paths={len(entries)}",
            "package_installation=NOT-PERFORMED",
            "device_validation=UNVERIFIED",
            "result=PASS",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--ldid", type=Path, help="explicit host-compatible ldid path required to inspect embedded signed entitlements")
    parser.add_argument("--expected-version", default=VERSION, help="expected Debian package version (defaults to repository VERSION)")
    parser.add_argument("--report", type=Path, help="write the validation report to a file")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[0-9][A-Za-z0-9.+:~_-]*", args.expected_version):
            raise ValueError("invalid expected Debian package version")
        report = inspect_package(args.package.resolve(), args.ldid.resolve() if args.ldid else None, args.expected_version)
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
