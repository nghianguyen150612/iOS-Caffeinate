#!/usr/bin/env python3
"""Inspect a rootful Debian artifact without installing it."""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from macho_ios import validate_ios12_arm64


PACKAGE = "com.ioscaffeinate.cli"
VERSION = (Path(__file__).resolve().parents[1] / "packaging/rootful/VERSION").read_text().strip()
REQUIRED_HASHES = {
    "usr/local/bin/ios-caffeinate",
    "usr/local/bin/ios-caffeinated",
    "usr/local/libexec/ioscaffeinate-manager",
    "usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist",
    "usr/share/ioscaffeinate/SIGNING-STATE",
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


def expected_package_paths() -> set[str]:
    root = Path(__file__).resolve().parents[1]
    files = {
        "usr/local/bin/ios-caffeinate",
        "usr/local/bin/ios-caffeinated",
        "usr/local/bin/ic",
        "usr/local/libexec/ioscaffeinate-manager",
        "usr/share/ioscaffeinate/SHA256SUMS",
        "usr/share/ioscaffeinate/SIGNING-STATE",
        "usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist",
        "usr/share/doc/ioscaffeinate/README.md",
        "usr/share/doc/ioscaffeinate/LICENSE",
    }
    for source in (root / "docs").rglob("*"):
        if source.is_file() and not source.is_symlink():
            relative = source.relative_to(root)
            files.add("usr/share/doc/ioscaffeinate/" + relative.as_posix())
    directories = {"var", "var/lib", "var/lib/ioscaffeinate", "var/log", "var/log/ioscaffeinate"}
    for file_path in files:
        parent = PurePosixPath(file_path).parent
        while parent.parts:
            directories.add(parent.as_posix())
            parent = parent.parent
    return files | directories | {"."}


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


def check_sha_manifest(root: Path) -> None:
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
    require(set(records) == REQUIRED_HASHES, "packaged SHA256SUMS must cover both binaries, the manager, and launchd template")


def inspect_package(deb: Path) -> str:
    require(deb.is_file() and not deb.is_symlink(), f"package artifact missing or not regular: {deb}")
    require(shutil.which("dpkg-deb") is not None, "dpkg-deb is required for package inspection")
    fields = {}
    for key in ("Package", "Version", "Architecture", "Section", "Priority", "Maintainer", "Description", "Depends"):
        result = subprocess.run(["dpkg-deb", "--field", str(deb), key], text=True, capture_output=True)
        if result.returncode == 0:
            fields[key] = result.stdout.strip()
    require(fields.get("Package") == PACKAGE, f"wrong package identifier: {fields.get('Package')}")
    require(fields.get("Version") == VERSION, f"wrong package version: {fields.get('Version')}")
    require(fields.get("Architecture") == "iphoneos-arm", f"wrong Debian architecture: {fields.get('Architecture')}")
    require(fields.get("Section") == "utils" and fields.get("Priority") == "optional", "unexpected package section or priority")
    require(fields.get("Maintainer", "").startswith("iOS-Caffeinate contributors <"), "unexpected maintainer metadata")
    require("rootful" in fields.get("Description", "").lower(), "package description does not identify rootful use")
    require(not fields.get("Depends"), "unexpected runtime package dependency")

    tar_bytes = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(deb)], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as archive:
        entries = validate_archive_members(archive.getmembers())
        require(set(entries) == expected_package_paths(), "package file manifest differs from the approved payload layout")
        validate_installed_modes(entries)
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
        signed_artifact = "_SIGNED-DEVICE-UNVERIFIED" in deb.name
        cli_info = validate_ios12_arm64(root / "usr/local/bin/ios-caffeinate", allow_signature=signed_artifact)
        daemon_info = validate_ios12_arm64(root / "usr/local/bin/ios-caffeinated", allow_signature=signed_artifact)
        require(cli_info.architecture == daemon_info.architecture == "arm64", "binary architecture mismatch")
        signing_state = (root / "usr/share/ioscaffeinate/SIGNING-STATE").read_text()
        expected_state = "SIGNED / DEVICE-UNVERIFIED" if signed_artifact else "UNSIGNED / DEVICE-UNVERIFIED"
        require(signing_state.splitlines()[0] == expected_state, "artifact filename and packaged signing state disagree")
        require("signature_verification=not-performed" in signing_state, "package overstates signature verification")
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

    sidecar = Path(str(deb) + ".sha256")
    if sidecar.exists() or sidecar.is_symlink():
        require(sidecar.is_file() and not sidecar.is_symlink(), "package SHA-256 sidecar must be a regular file")
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\n]+)\n?", sidecar.read_text())
        require(match is not None and match.group(1) == hashlib.sha256(deb.read_bytes()).hexdigest(), "package SHA-256 sidecar mismatch")
        require(match.group(2) == deb.name, "package SHA-256 sidecar names another artifact")
    return "\n".join(
        [
            f"package={fields['Package']}",
            f"version={fields['Version']}",
            f"architecture={fields['Architecture']}",
            f"artifact_sha256={hashlib.sha256(deb.read_bytes()).hexdigest()}",
            f"cli_macho=arm64 {cli_info.platform} min={cli_info.minimum_os_text} signed={cli_info.has_code_signature}",
            f"daemon_macho=arm64 {daemon_info.platform} min={daemon_info.minimum_os_text} signed={daemon_info.has_code_signature}",
            f"signing_state={signing_state.splitlines()[0]}",
            f"package_paths={len(entries)}",
            "package_installation=NOT-PERFORMED",
            "device_validation=UNVERIFIED",
            "result=PASS",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--report", type=Path, help="write the validation report to a file")
    args = parser.parse_args()
    try:
        report = inspect_package(args.package.resolve())
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
