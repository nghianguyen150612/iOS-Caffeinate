#!/usr/bin/env python3
"""Build the rootful iOS Debian package from inspected iOS build artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from macho_ios import validate_ios12_arm64, validate_signed_source_identity
from macho_code_signature import CodeSignatureError, audit_code_signature
from signing_profile import (
    ADHOC_REQUIREMENTS_PROFILE,
    ADHOC_REQUIREMENTS_PROFILE_SHA256,
    ADHOC_REQUIREMENTS_SUPERBLOB,
    PROFILE_ID,
    PROFILE_RELATIVE_PATH,
    SigningError,
    load_approved_profile,
    require_exact_embedded_entitlements,
    signer_identity,
    validate_signer,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ID = "com.ioscaffeinate.cli"
VERSION_FILE = ROOT / "packaging/rootful/VERSION"
PAYLOADS = {
    "ios-caffeinate": Path("usr/local/bin/ios-caffeinate"),
    "ios-caffeinated": Path("usr/local/bin/ios-caffeinated"),
}
EXPECTED_DEPENDENCIES = {
    "ios-caffeinate": {
        "/usr/lib/libSystem.B.dylib",
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    },
    "ios-caffeinated": {
        "/usr/lib/libSystem.B.dylib",
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    },
}
LAUNCHD_SOURCE = ROOT / "packaging/com.ioscaffeinate.daemon.plist"
MANAGER_SOURCE = ROOT / "packaging/rootful/manager"
PREINST_SOURCE = ROOT / "packaging/rootful/DEBIAN/preinst"
PRERM_SOURCE = ROOT / "packaging/rootful/DEBIAN/prerm"
TOOL_SOURCES = (
    "p009_evidence.py",
    "p018_evidence.py",
    "p018_validate_export.py",
    "p018_package_preflight.py",
)


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
            validate_ios12_arm64(path, allow_signature=False, expected_dependencies=EXPECTED_DEPENDENCIES[name])
        except ValueError as error:
            fail(f"{name}: {error}")
    return records


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
    parser.add_argument(
        "--package-version",
        help="explicit Debian version for an isolated prerelease candidate; defaults to packaging/rootful/VERSION",
    )
    parser.add_argument("--sign-with-ldid", type=Path, help="absolute path to an operator-supplied, host-compatible ldid executable")
    parser.add_argument("--entitlements", type=Path, help="explicit approved entitlement profile; required with --sign-with-ldid")
    return parser.parse_args()


def verify_with_codesign(paths: list[Path]) -> dict[str, object]:
    """Use Apple's host verifier when present; absence remains explicitly pending."""
    verifier_path = Path("/usr/bin/codesign")
    if platform.system() != "Darwin" or not verifier_path.is_file() or not os.access(verifier_path, os.X_OK):
        return {"status": "PENDING", "tool": None, "results": []}
    verifier = str(verifier_path)
    results: list[dict[str, object]] = []
    for path in paths:
        command = [verifier, "--verify", "--strict", "--verbose=2", str(path)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError as error:
            fail(f"codesign verifier could not be executed: {error}")
        results.append({
            "file": path.name,
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })
        if result.returncode != 0:
            fail(f"host signature-integrity verification failed for {path.name}: {result.stderr.strip()}")
    return {"status": "VERIFIED", "tool": verifier, "results": results}


def main() -> int:
    args = parse_args()
    input_dir = Path(os.path.abspath(args.input_dir))
    output_dir = Path(os.path.abspath(args.output_dir))
    if input_dir.is_symlink() or not input_dir.is_dir():
        fail(f"input directory does not exist: {input_dir}")
    if shutil.which("dpkg-deb") is None:
        fail("dpkg-deb is required; no package was built")
    version = args.package_version or VERSION_FILE.read_text().strip()
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+:~_-]*", version):
        fail(f"invalid Debian package version in {VERSION_FILE}")
    if bool(args.sign_with_ldid) != bool(args.entitlements):
        fail("--sign-with-ldid and --entitlements must be supplied together; signing is never implicit")
    source_hashes = validate_source_manifest(input_dir)
    signer = None
    profile_hash: str | None = None
    signer_version: str | None = None
    signer_hash: str | None = None
    if args.sign_with_ldid:
        try:
            signer = validate_signer(Path(os.path.abspath(args.sign_with_ldid)))
            _profile_data, profile_hash = load_approved_profile(Path(os.path.abspath(args.entitlements)))
            signer_version, signer_hash = signer_identity(signer)
        except SigningError as error:
            fail(str(error))
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
        requirements_path = Path(temporary) / "adhoc-requirements.superblob"
        requirements_path.write_bytes(ADHOC_REQUIREMENTS_SUPERBLOB)
        requirements_path.chmod(0o600)
        if sha256(requirements_path) != ADHOC_REQUIREMENTS_PROFILE_SHA256:
            fail("approved ad hoc requirements SuperBlob differs from its fixed profile digest")
        stage = Path(temporary) / "root"
        control = stage / "DEBIAN"
        control.mkdir(parents=True)
        payload_hash_paths: list[str] = []
        staged_binaries: dict[str, Path] = {}
        final_binary_hashes: dict[str, str] = {}

        for name, relative in PAYLOADS.items():
            source = input_dir / name
            destination = stage / relative
            copy_regular(source, destination, 0o755)
            if sha256(destination) != source_hashes[name]:
                fail(f"staged source identity changed while copying {name}")
            if signer:
                assert args.entitlements is not None and profile_hash is not None
                profile_path = Path(os.path.abspath(args.entitlements))
                try:
                    subprocess.run([
                        str(signer), "-Cadhoc", f"-Q{requirements_path}", f"-S{profile_path}", str(destination),
                    ], check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as error:
                    detail = error.stderr.strip() if error.stderr else f"exit {error.returncode}"
                    fail(f"ldid signing failed for {name}: {detail}")
                try:
                    validate_ios12_arm64(destination, allow_signature=True, expected_dependencies=EXPECTED_DEPENDENCIES[name])
                    validate_signed_source_identity(source, destination)
                    require_exact_embedded_entitlements(signer, destination)
                    signature_audit = audit_code_signature(destination.read_bytes(), expected_identifier=name)
                    if not signature_audit["independent_code_directory_verified"]:
                        raise CodeSignatureError("CodeDirectory hashes were not independently verified")
                    if not signature_audit["entitlements_exact_match"] or not signature_audit["adhoc_flag_present"]:
                        raise CodeSignatureError("signature must carry the exact profile and Apple ad hoc flag")
                    if signature_audit.get("requirements") != {"count": 0, "types": []}:
                        raise CodeSignatureError("ad hoc signature must use the approved empty designated-requirement set")
                except SigningError as error:
                    fail(f"{name}: {error}")
                except CodeSignatureError as error:
                    fail(f"{name}: {error}")
                except ValueError as error:
                    fail(f"ldid did not produce an inspectable signature for {name}: {error}")
            elif sha256(destination) != source_hashes[name]:
                fail(f"unsigned staging changed source executable {name}")
            final_binary_hashes[name] = sha256(destination)
            staged_binaries[name] = destination
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
        signature_integrity = verify_with_codesign(list(staged_binaries.values())) if signer else {
            "status": "NOT_APPLICABLE", "tool": None, "results": []
        }
        signing_lines = [
            "signature_state=SIGNATURE_PRESENT" if signer else "signature_state=UNSIGNED",
            f"profile_id={PROFILE_ID if signer else 'none'}",
            f"profile_sha256={profile_hash if signer else 'not-applicable'}",
            f"embedded_entitlements={'EXACT_MATCH' if signer else 'NOT_APPLICABLE'}",
            f"signature_verification={'SIGNATURE_VERIFIED' if signature_integrity['status'] == 'VERIFIED' else ('PENDING' if signer else 'NOT_APPLICABLE')}",
            "device_execution=NOT_VERIFIED",
            "device_package_acceptance=NOT_ACCEPTED",
        ]
        if signer:
            signing_lines.extend((
                f"signing_tool_version={signer_version}",
                f"signing_tool_sha256={signer_hash}",
                f"code_signature_requirement_profile={ADHOC_REQUIREMENTS_PROFILE}",
                f"code_signature_requirement_profile_sha256={ADHOC_REQUIREMENTS_PROFILE_SHA256}",
            ))
        signing_text = "\n".join(signing_lines) + "\n"
        signing_state.parent.mkdir(parents=True, exist_ok=True)
        signing_state.write_text(signing_text)
        signing_state.chmod(0o644)
        payload_hash_paths.append(signing_state.relative_to(stage).as_posix())

        if signer:
            assert args.entitlements is not None
            profile_target = stage / "usr/share/ioscaffeinate/signing" / PROFILE_RELATIVE_PATH.name
            copy_regular(Path(os.path.abspath(args.entitlements)), profile_target, 0o644)
            if sha256(profile_target) != profile_hash:
                fail("approved signing profile changed while copying into the package")
            payload_hash_paths.append(profile_target.relative_to(stage).as_posix())

        docs_root = stage / "usr/share/doc/ioscaffeinate"
        copy_regular(ROOT / "README.md", docs_root / "README.md", 0o644)
        copy_regular(ROOT / "LICENSE", docs_root / "LICENSE", 0o644)
        payload_hash_paths.extend((
            (docs_root / "README.md").relative_to(stage).as_posix(),
            (docs_root / "LICENSE").relative_to(stage).as_posix(),
        ))
        docs_source = ROOT / "docs"
        for source in sorted(docs_source.rglob("*")):
            if source.is_symlink():
                fail(f"symlink is not allowed in packaged documentation: {source}")
            if source.is_file():
                relative = source.relative_to(docs_source)
                target = docs_root / "docs" / relative
                copy_regular(source, target, 0o644)
                payload_hash_paths.append(target.relative_to(stage).as_posix())
        tools_root = docs_root / "tools"
        for name in TOOL_SOURCES:
            target = tools_root / name
            copy_regular(ROOT / "scripts" / name, target, 0o644)
            payload_hash_paths.append(target.relative_to(stage).as_posix())

        # These are package files, never default runtime configuration.
        if (stage / "var/lib/ioscaffeinate/schedules.json").exists() or (stage / "var/lib/ioscaffeinate/server-mode.json").exists():
            fail("refusing to package persistent schedule or server-mode state")

        try:
            source_commit = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                check=True, text=True, capture_output=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            fail("git source commit identity is unavailable; refusing a release package")
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            fail("git returned an invalid source commit SHA")
        status_result = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"],
            check=True, text=True, capture_output=True,
        )
        signing_record = {
            "schema_version": 1,
            "package_identifier": PACKAGE_ID,
            "package_version": version,
            "architecture": "iphoneos-arm",
            "source_commit_sha": source_commit,
            "source_tree_clean": not bool(status_result.stdout.strip()),
            "signing": {
                "state": "SIGNATURE_PRESENT" if signer else "UNSIGNED",
                "profile_id": PROFILE_ID if signer else None,
                "profile_sha256": profile_hash,
                "signing_tool_version": signer_version,
                "signing_tool_sha256": signer_hash,
                "code_signature_kind": "ADHOC" if signer else None,
                "code_signature_requirement_profile": ADHOC_REQUIREMENTS_PROFILE if signer else None,
                "code_signature_requirement_profile_sha256": ADHOC_REQUIREMENTS_PROFILE_SHA256 if signer else None,
                "source_binary_sha256": source_hashes,
                "final_binary_sha256": final_binary_hashes,
                "embedded_entitlements": "EXACT_MATCH" if signer else "NOT_APPLICABLE",
                "signature_verification": "SIGNATURE_VERIFIED" if signature_integrity["status"] == "VERIFIED" else ("PENDING" if signer else "NOT_APPLICABLE"),
                "signature_integrity": signature_integrity,
                "device_execution_verification": "NOT_VERIFIED",
                "device_package_acceptance": "NOT_ACCEPTED",
            },
        }
        package_build_path = stage / "usr/share/ioscaffeinate/package-build.json"
        package_build_path.write_text(json.dumps(signing_record, indent=2, sort_keys=True) + "\n")
        package_build_path.chmod(0o644)
        payload_hash_paths.append(package_build_path.relative_to(stage).as_posix())

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
            output_dir / f"{filename}.manifest.json",
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
        sidecar_record = dict(signing_record)
        sidecar_record["package"] = {"file": filename, "sha256": package_hash}
        (output_dir / f"{filename}.manifest.json").write_text(json.dumps(sidecar_record, indent=2, sort_keys=True) + "\n")
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
            f"source_commit_sha: {source_commit}",
            f"source_tree_clean: {str(not bool(status_result.stdout.strip())).lower()}",
            f"profile_id: {PROFILE_ID if signer else 'not-used'}",
            f"profile_sha256: {profile_hash if signer else 'not-used'}",
            f"code_signature_requirement_profile: {ADHOC_REQUIREMENTS_PROFILE if signer else 'not-used'}",
            f"code_signature_requirement_profile_sha256: {ADHOC_REQUIREMENTS_PROFILE_SHA256 if signer else 'not-used'}",
            f"signing_tool_version: {signer_version if signer else 'not-used'}",
            f"signing_tool_sha256: {signer_hash if signer else 'not-used'}",
            f"source_cli_sha256: {source_hashes['ios-caffeinate']}",
            f"source_daemon_sha256: {source_hashes['ios-caffeinated']}",
            f"final_signed_cli_sha256: {final_binary_hashes['ios-caffeinate'] if signer else 'not-signed'}",
            f"final_signed_daemon_sha256: {final_binary_hashes['ios-caffeinated'] if signer else 'not-signed'}",
            f"signature_verification: {'SIGNATURE_VERIFIED' if signature_integrity['status'] == 'VERIFIED' else ('PENDING' if signer else 'NOT_APPLICABLE')}",
            f"embedded_entitlements: {'EXACT_MATCH' if signer else 'NOT_APPLICABLE'}",
            "device_installation_and_execution: not-verified",
            "device_package_acceptance: not-accepted",
        ]
        (output_dir / f"{filename}.manifest.txt").write_text("\n".join(report) + "\n")
        validation_command = [
            sys.executable,
            str(ROOT / "scripts/validate_rootful_package.py"),
            str(output),
            "--expected-version",
            version,
        ]
        if signer:
            validation_command.extend(("--ldid", str(signer)))
        validation = subprocess.run(validation_command, capture_output=True, text=True, check=False)
        if validation.returncode != 0:
            for artifact in sidecars:
                try:
                    artifact.unlink()
                except FileNotFoundError:
                    pass
            fail("built Debian archive failed final package validation: " + (validation.stderr.strip() or validation.stdout.strip()))
        print(f"Built {output}")
        print(f"Package SHA-256: {package_hash}")
        print(f"Signing state: {state}")
        print(f"Build manifest: {output_dir / f'{filename}.manifest.json'}")
        print(validation.stdout.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
