#!/usr/bin/env python3
"""Build the rootful iOS Debian package from inspected iOS build artifacts."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from macho_ios import validate_ios12_arm64


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ID = "com.ioscaffeinate.cli"
VERSION_FILE = ROOT / "packaging/rootful/VERSION"
PAYLOADS = {
    "ios-caffeinate": Path("usr/local/bin/ios-caffeinate"),
    "ios-caffeinated": Path("usr/local/bin/ios-caffeinated"),
}
LAUNCHD_SOURCE = ROOT / "packaging/com.ioscaffeinate.daemon.plist"
MANAGER_SOURCE = ROOT / "packaging/rootful/manager"
PREINST_SOURCE = ROOT / "packaging/rootful/DEBIAN/preinst"
PRERM_SOURCE = ROOT / "packaging/rootful/DEBIAN/prerm"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"ERROR: {message}")


def validate_source_manifest(input_dir: Path) -> dict[str, str]:
    manifest = input_dir / "SHA256SUMS"
    if not manifest.is_file() or manifest.is_symlink():
        fail(f"missing regular input SHA256SUMS: {manifest}")
    expected_names = set(PAYLOADS)
    records: dict[str, str] = {}
    for line_number, line in enumerate(manifest.read_text().splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if not match:
            fail(f"invalid SHA256SUMS line {line_number}")
        digest, name = match.groups()
        if name in records:
            fail(f"duplicate source checksum entry: {name}")
        records[name] = digest
    if set(records) != expected_names:
        fail(f"input SHA256SUMS must list exactly {', '.join(sorted(expected_names))}")
    for name in sorted(expected_names):
        path = input_dir / name
        if not path.is_file() or path.is_symlink():
            fail(f"missing regular iOS input artifact: {path}")
        actual = sha256(path)
        if actual != records[name]:
            fail(f"source SHA-256 mismatch for {name}")
        try:
            validate_ios12_arm64(path, allow_signature=False)
        except ValueError as error:
            fail(f"{name}: {error}")
    return records


def validate_signer(path: Path) -> Path:
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        fail("--sign-with-ldid must name an absolute, executable ldid path supplied by the operator")
    metadata = path.stat()
    if metadata.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWGRP | stat.S_IWOTH):
        fail("refusing an ldid executable with set-id or group/world-writable permissions")
    return path.resolve()


def copy_regular(source: Path, destination: Path, mode: int) -> None:
    if not source.is_file() or source.is_symlink():
        fail(f"expected regular project input: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def package_paths(stage: Path) -> list[str]:
    result: list[str] = []
    for path in sorted(stage.rglob("*")):
        if path.is_file() or path.is_symlink():
            package_path = "/" + path.relative_to(stage).as_posix()
            if not re.fullmatch(r"/[A-Za-z0-9._+/-]+", package_path):
                fail(f"unsupported character in package path: {package_path!r}")
            result.append(package_path)
    return result


def generate_preinst(paths: list[str]) -> str:
    template = PREINST_SOURCE.read_text()
    marker = "# P007_COLLISION_CHECKS_INSERTION_POINT"
    if template.count(marker) != 1:
        fail("preinst collision-check insertion marker is missing or duplicated")
    directories = set()
    for path in paths:
        parent = Path(path).parent
        while parent != Path("/"):
            parent_text = "/" + parent.as_posix().lstrip("/")
            if parent_text.startswith("/usr/share/doc/ioscaffeinate/") or parent_text in (
                "/usr/share/doc/ioscaffeinate",
                "/usr/share/ioscaffeinate",
                "/usr/share/ioscaffeinate/launchd",
            ):
                directories.add(parent_text)
            parent = parent.parent
    dir_checks = "\n".join(f"check_real_directory '{path}'" for path in sorted(directories))
    checks = "\n".join(f"check_owned_or_absent '{path}'" for path in paths)
    insertion = "# Validate package-private parents and every incoming file before extraction.\n" + dir_checks + "\n" + checks
    return template.replace(marker, insertion)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True, help="directory containing iOS executables and SHA256SUMS")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sign-with-ldid", type=Path, help="explicit trusted ldid path; signs with ldid -S and no entitlements")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = Path(os.path.abspath(args.input_dir))
    output_dir = Path(os.path.abspath(args.output_dir))
    if input_dir.is_symlink() or not input_dir.is_dir():
        fail(f"input directory does not exist: {input_dir}")
    if shutil.which("dpkg-deb") is None:
        fail("dpkg-deb is required; no package was built")
    version = VERSION_FILE.read_text().strip()
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+:~_-]*", version):
        fail(f"invalid Debian package version in {VERSION_FILE}")
    source_hashes = validate_source_manifest(input_dir)
    signer = validate_signer(args.sign_with_ldid) if args.sign_with_ldid else None
    if output_dir.is_symlink() or not output_dir.is_dir():
        if output_dir.exists() or output_dir.is_symlink():
            fail("output directory must be a real directory")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is None:
        try:
            source_date_epoch = subprocess.run(
                ["git", "-C", str(ROOT), "log", "-1", "--format=%ct", "HEAD"],
                check=True, text=True, capture_output=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            source_date_epoch = "0"
    try:
        epoch = int(source_date_epoch)
        if epoch < 0:
            raise ValueError
    except ValueError:
        fail("SOURCE_DATE_EPOCH must be a non-negative integer")

    with tempfile.TemporaryDirectory(prefix="ioscaffeinate-rootful-") as temporary:
        stage = Path(temporary) / "root"
        control = stage / "DEBIAN"
        control.mkdir(parents=True)
        payload_hash_paths: list[str] = []

        for name, relative in PAYLOADS.items():
            source = input_dir / name
            destination = stage / relative
            copy_regular(source, destination, 0o755)
            if signer:
                subprocess.run([str(signer), "-S", str(destination)], check=True)
                try:
                    validate_ios12_arm64(destination, allow_signature=True)
                except ValueError as error:
                    fail(f"ldid did not produce an inspectable signature for {name}: {error}")
            payload_hash_paths.append(relative.as_posix())

        (stage / "usr/local/bin").mkdir(parents=True, exist_ok=True)
        (stage / "usr/local/bin/ic").symlink_to("ios-caffeinate")

        manager_target = stage / "usr/local/libexec/ioscaffeinate-manager"
        copy_regular(MANAGER_SOURCE, manager_target, 0o755)
        payload_hash_paths.append(manager_target.relative_to(stage).as_posix())
        data_dir = stage / "var/lib/ioscaffeinate"
        log_dir = stage / "var/log/ioscaffeinate"
        data_dir.mkdir(parents=True)
        log_dir.mkdir(parents=True)
        data_dir.chmod(0o750)
        log_dir.chmod(0o750)

        launchd_target = stage / "usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist"
        copy_regular(LAUNCHD_SOURCE, launchd_target, 0o644)
        payload_hash_paths.append(launchd_target.relative_to(stage).as_posix())

        signing_state = stage / "usr/share/ioscaffeinate/SIGNING-STATE"
        if signer:
            signing_text = "SIGNED / DEVICE-UNVERIFIED\nsignature_presence=present\nsignature_verification=not-performed\ndevice_acceptance=not-verified\n"
        else:
            signing_text = "UNSIGNED / DEVICE-UNVERIFIED\nsignature_presence=absent\nsignature_verification=not-performed\ndevice_acceptance=not-verified\n"
        signing_state.parent.mkdir(parents=True, exist_ok=True)
        signing_state.write_text(signing_text)
        signing_state.chmod(0o644)
        payload_hash_paths.append(signing_state.relative_to(stage).as_posix())

        docs_root = stage / "usr/share/doc/ioscaffeinate"
        copy_regular(ROOT / "README.md", docs_root / "README.md", 0o644)
        copy_regular(ROOT / "LICENSE", docs_root / "LICENSE", 0o644)
        docs_source = ROOT / "docs"
        for source in sorted(docs_source.rglob("*")):
            if source.is_symlink():
                fail(f"symlink is not allowed in packaged documentation: {source}")
            if source.is_file():
                relative = source.relative_to(docs_source)
                copy_regular(source, docs_root / "docs" / relative, 0o644)

        # These are package files, never default runtime configuration.
        if (stage / "var/lib/ioscaffeinate/schedules.json").exists() or (stage / "var/lib/ioscaffeinate/server-mode.json").exists():
            fail("refusing to package persistent schedule or server-mode state")

        manifest_path = stage / "usr/share/ioscaffeinate/SHA256SUMS"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_lines = []
        for relative in payload_hash_paths:
            path = stage / relative
            manifest_lines.append(f"{sha256(path)}  {relative}")
        manifest_path.write_text("\n".join(manifest_lines) + "\n")
        manifest_path.chmod(0o644)

        control_template = (ROOT / "packaging/rootful/DEBIAN/control.in").read_text()
        if control_template.count("@VERSION@") != 1:
            fail("control.in must contain one @VERSION@ placeholder")
        (control / "control").write_text(control_template.replace("@VERSION@", version))
        preinst = generate_preinst(package_paths(stage))
        (control / "preinst").write_text(preinst)
        (control / "preinst").chmod(0o755)
        copy_regular(PRERM_SOURCE, control / "prerm", 0o755)

        for path in sorted(stage.rglob("*"), reverse=True):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o755 if path not in (data_dir, log_dir) else 0o750)
        for path in stage.rglob("*"):
            if path.is_file() and not path.is_symlink() and path != control / "preinst" and path != control / "prerm":
                if path in (stage / "usr/local/bin/ios-caffeinate", stage / "usr/local/bin/ios-caffeinated", stage / "usr/local/libexec/ioscaffeinate-manager"):
                    path.chmod(0o755)
                else:
                    path.chmod(0o644)

        # dpkg-deb honors SOURCE_DATE_EPOCH; normalize all staged timestamps as well.
        for path in stage.rglob("*"):
            try:
                os.utime(path, (epoch, epoch), follow_symlinks=False)
            except (NotImplementedError, OSError):
                if not path.is_symlink():
                    raise
        os.utime(stage, (epoch, epoch))

        state = "SIGNED-DEVICE-UNVERIFIED" if signer else "UNSIGNED-DEVICE-UNVERIFIED"
        filename = f"ioscaffeinate_{version}_iphoneos-arm_{state}.deb"
        output = output_dir / filename
        sidecars = (
            output,
            output_dir / f"{filename}.sha256",
            output_dir / f"{filename}.files.sha256",
            output_dir / f"{filename}.manifest.txt",
        )
        existing = [str(path) for path in sidecars if path.exists() or path.is_symlink()]
        if existing:
            fail("refusing to overwrite existing package artifact or sidecar: " + ", ".join(existing))
        env = os.environ.copy()
        env["SOURCE_DATE_EPOCH"] = str(epoch)
        subprocess.run(
            ["dpkg-deb", "--build", "--root-owner-group", "-Zxz", "-z9", "--uniform-compression", str(stage), str(output)],
            check=True, env=env,
        )

        package_hash = sha256(output)
        (output_dir / f"{filename}.sha256").write_text(f"{package_hash}  {filename}\n")
        (output_dir / f"{filename}.files.sha256").write_text(manifest_path.read_text())
        report = [
            f"package: {PACKAGE_ID}",
            f"version: {version}",
            "architecture: iphoneos-arm",
            f"signing: {state}",
            f"artifact: {filename}",
            f"artifact_sha256: {package_hash}",
            f"source_date_epoch: {epoch}",
            f"source_ios_caffeinate_sha256: {source_hashes['ios-caffeinate']}",
            f"source_ios_caffeinated_sha256: {source_hashes['ios-caffeinated']}",
            f"packaged_ldid_sha256: {sha256(signer) if signer else 'not-used'}",
            "signature_verification: not-performed",
            "device_installation_and_execution: not-verified",
        ]
        (output_dir / f"{filename}.manifest.txt").write_text("\n".join(report) + "\n")
        print(f"Built {output}")
        print(f"Package SHA-256: {package_hash}")
        print(f"Signing state: {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
