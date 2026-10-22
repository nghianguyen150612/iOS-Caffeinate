#!/usr/bin/env python3
"""Provision and verify the pinned H003 Procursus ldid signer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "scripts/h003-build-inputs.lock"
PACKAGE_LOCK_KEYS = {
    "gcc-13": "H003_GCC13_PACKAGE_VERSION",
    "g++-13": "H003_GPP13_PACKAGE_VERSION",
    "binutils": "H003_BINUTILS_PACKAGE_VERSION",
    "make": "H003_MAKE_PACKAGE_VERSION",
    "libplist-dev": "H003_LIBPLIST_PACKAGE_VERSION",
    "libssl-dev": "H003_OPENSSL_PACKAGE_VERSION",
    "pkg-config": "H003_PKG_CONFIG_PACKAGE_VERSION",
    "git": "H003_GIT_PACKAGE_VERSION",
    "python3": "H003_PYTHON3_PACKAGE_VERSION",
    "ca-certificates": "H003_CA_CERTIFICATES_PACKAGE_VERSION",
}
TOOL_LOCK_KEYS = {
    "gcc_version": "H003_GCC_VERSION",
    "gxx_version": "H003_GCC_VERSION",
    "binutils_version": "H003_BINUTILS_VERSION",
    "make_version": "H003_MAKE_VERSION",
    "libplist_version": "H003_LIBPLIST_VERSION",
    "openssl_version": "H003_OPENSSL_VERSION",
}


class H003Error(ValueError):
    """A build input or signer failed its pinned identity check."""


def load_lock(path: Path = LOCK_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_symlink() or not path.is_file():
        raise H003Error("H003 build input lock is missing or unsafe")
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([^\s]+)", stripped)
        if match is None:
            raise H003Error(f"invalid H003 lock entry on line {line_number}")
        key, value = match.groups()
        if key in values:
            raise H003Error(f"duplicate H003 lock entry: {key}")
        values[key] = value
    required = {
        "H003_SOURCE_URL", "H003_SOURCE_COMMIT", "H003_SOURCE_TREE", "H003_SIGNER_VERSION",
        "H003_SIGNER_SHA256", "H003_CONTAINER_IMAGE", "H003_PLATFORM", "H003_APT_SNAPSHOT",
        "H003_APT_SUITES", *PACKAGE_LOCK_KEYS.values(), *TOOL_LOCK_KEYS.values(),
    }
    missing = required - set(values)
    if missing:
        raise H003Error("H003 build input lock is missing: " + ", ".join(sorted(missing)))
    if not re.fullmatch(r"[0-9a-f]{64}", values["H003_SIGNER_SHA256"]):
        raise H003Error("H003 signer SHA-256 pin is malformed")
    if not re.fullmatch(r"[0-9a-f]{40}", values["H003_SOURCE_COMMIT"]):
        raise H003Error("H003 source commit pin is malformed")
    if not re.fullmatch(r"[0-9a-f]{40}", values["H003_SOURCE_TREE"]):
        raise H003Error("H003 source tree pin is malformed")
    return values


def require_host_architecture(machine: str) -> None:
    if machine not in {"x86_64", "amd64"}:
        raise H003Error(f"WRONG_HOST_ARCHITECTURE: expected x86_64 Linux, got {machine}")


def validate_source_identity(actual_commit: str, actual_tree: str, lock: dict[str, str]) -> None:
    if actual_commit != lock["H003_SOURCE_COMMIT"]:
        raise H003Error("wrong source commit: upstream ldid checkout identity mismatch")
    if actual_tree != lock["H003_SOURCE_TREE"]:
        raise H003Error("corrupt build input: upstream ldid source tree mismatch")


def require_source_fetch_success(returncode: int) -> None:
    if returncode != 0:
        raise H003Error("SOURCE_ARCHIVE_UNAVAILABLE: exact upstream ldid commit could not be fetched")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_elf(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise H003Error("verified signer executable is missing or unsafe")
    if not os.access(path, os.X_OK):
        raise H003Error("verified signer executable is not executable")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWGRP | stat.S_IWOTH):
        raise H003Error("verified signer executable has unsafe filesystem permissions")
    raw = path.read_bytes()
    if len(raw) < 64 or raw[:4] != b"\x7fELF":
        raise H003Error("verified signer output is not an ELF executable")
    if raw[4] != 2 or raw[5] != 1:
        raise H003Error("verified signer output is not little-endian ELF64")
    e_type, e_machine = struct.unpack_from("<HH", raw, 16)
    if e_type != 3 or e_machine != 62:
        raise H003Error("verified signer output is not an x86_64 PIE executable")
    e_phoff = struct.unpack_from("<Q", raw, 32)[0]
    e_phentsize, e_phnum = struct.unpack_from("<HH", raw, 54)
    if e_phentsize < 56 or e_phoff + e_phentsize * e_phnum > len(raw):
        raise H003Error("verified signer ELF program-header table is malformed")
    interpreter = None
    for index in range(e_phnum):
        offset = e_phoff + index * e_phentsize
        p_type = struct.unpack_from("<I", raw, offset)[0]
        if p_type == 3:  # PT_INTERP
            p_offset = struct.unpack_from("<Q", raw, offset + 8)[0]
            p_filesz = struct.unpack_from("<Q", raw, offset + 32)[0]
            if p_offset + p_filesz > len(raw) or p_filesz == 0:
                raise H003Error("verified signer ELF interpreter segment is malformed")
            interpreter = raw[p_offset:p_offset + p_filesz].rstrip(b"\0").decode("ascii", "replace")
            break
    if interpreter != "/lib64/ld-linux-x86-64.so.2":
        raise H003Error("verified signer output is not a dynamically linked x86_64 PIE executable")
    return {"elf_class": "ELF64", "architecture": "x86_64", "type": "ELF64-PIE", "interpreter": interpreter}


def read_version_banner(path: Path) -> str:
    try:
        result = subprocess.run([str(path)], capture_output=True, text=True, check=False)
    except OSError as error:
        raise H003Error(f"could not read verified signer version: {type(error).__name__}") from None
    ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    for stream in (result.stdout, result.stderr):
        normalized = ansi.sub("", stream)
        match = re.search(r"Link Identity Editor\s+([^\s]+)", normalized)
        if match is not None:
            return f"Link Identity Editor {match.group(1)}"
    diagnostic = (result.stdout + "\n" + result.stderr)[:256]
    raise H003Error(
        "verified signer did not return the expected Link Identity Editor version banner; "
        f"output={diagnostic!r}"
    )


def verify_binary_identity(
    path: Path,
    expected_sha256: str,
    expected_version: str,
    version_reader: Callable[[Path], str] = read_version_banner,
) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise H003Error("verified signer executable is missing or unsafe")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise H003Error("SIGNER_REPRODUCTION_MISMATCH: signer executable SHA-256 differs from the exact pin")
    # The binary is executed only after its bytes match the exact pinned hash.
    elf = inspect_elf(path)
    banner = version_reader(path)
    expected_banner = f"Link Identity Editor {expected_version}"
    if banner != expected_banner:
        raise H003Error("wrong signer version: pinned executable returned an unexpected version banner")
    return {"sha256": actual_sha256, "version": expected_version, **elf}


def _parse_fields(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise H003Error("H003 container build receipt is missing or unsafe")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            raise H003Error("H003 container build receipt has a malformed line")
        key, value = line.split("=", 1)
        if not key or key in values:
            raise H003Error("H003 container build receipt has a duplicate or empty key")
        values[key] = value
    return values


def validate_build_fields(fields: dict[str, str], lock: dict[str, str]) -> None:
    validate_source_identity(fields.get("source_commit_1", ""), fields.get("source_tree_1", ""), lock)
    validate_source_identity(fields.get("source_commit_2", ""), fields.get("source_tree_2", ""), lock)
    required_equal = {
        "source_url": lock["H003_SOURCE_URL"],
        "container_image": lock["H003_CONTAINER_IMAGE"],
        "container_platform": lock["H003_PLATFORM"],
        "apt_snapshot": lock["H003_APT_SNAPSHOT"],
        "apt_signature_verification": "VERIFIED_BY_APT",
        "apt_source_origin": lock["H003_APT_SNAPSHOT"],
    }
    for key, expected in required_equal.items():
        if fields.get(key) != expected:
            raise H003Error(f"H003 build provenance mismatch: {key}")
    for package, lock_key in PACKAGE_LOCK_KEYS.items():
        if fields.get(f"package.{package}") != lock[lock_key]:
            raise H003Error(f"dependency version mismatch: {package}")
    for field, lock_key in TOOL_LOCK_KEYS.items():
        if fields.get(field) != lock[lock_key]:
            raise H003Error(f"toolchain version mismatch: {field}")
    expected_hash = lock["H003_SIGNER_SHA256"]
    for field in ("build_1_sha256", "build_2_sha256", "executable_sha256"):
        if fields.get(field) != expected_hash:
            raise H003Error("SIGNER_REPRODUCTION_MISMATCH: independent builds do not match the exact signer SHA-256")
    if fields.get("version_banner") != f"Link Identity Editor {lock['H003_SIGNER_VERSION']}":
        raise H003Error("wrong signer version in H003 build provenance")
    if fields.get("binary_architecture") != "x86_64" or fields.get("binary_elf_class") != "ELF64" or fields.get("binary_type") != "ELF64-PIE":
        raise H003Error("wrong host architecture or executable type in H003 build provenance")
    if fields.get("result") != "VERIFIED":
        raise H003Error("H003 signer build receipt does not report verified provenance")


def make_provenance(fields: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "result": "VERIFIED",
        "source": {
            "repository": fields["source_url"],
            "commit": fields["source_commit_1"],
            "tree": fields["source_tree_1"],
            "independent_build_commit": fields["source_commit_2"],
            "independent_build_tree": fields["source_tree_2"],
            "fetch_method": "git-fetch-exact-commit",
        },
        "build_environment": {
            "container_image": fields["container_image"],
            "platform": fields["container_platform"],
            "operating_system": {"id": fields["ubuntu_id"], "version": fields["ubuntu_version"]},
            "apt_snapshot": fields["apt_snapshot"],
            "apt_signature_verification": fields["apt_signature_verification"],
            "apt_source_origin": fields["apt_source_origin"],
        },
        "dependencies": {package: fields[f"package.{package}"] for package in PACKAGE_LOCK_KEYS},
        "toolchain": {
            "gcc": fields["gcc_version"],
            "g++": fields["gxx_version"],
            "binutils": fields["binutils_version"],
            "make": fields["make_version"],
            "libplist": fields["libplist_version"],
            "openssl": fields["openssl_version"],
        },
        "executable": {
            "sha256": fields["executable_sha256"],
            "version": fields["version_banner"].removeprefix("Link Identity Editor "),
            "elf_class": fields["binary_elf_class"],
            "architecture": fields["binary_architecture"],
            "type": fields["binary_type"],
            "interpreter": fields["binary_interpreter"],
        },
        "reproducibility": {
            "build_1_sha256": fields["build_1_sha256"],
            "build_2_sha256": fields["build_2_sha256"],
            "outcome": "EXACT_MATCH",
        },
    }


def _load_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value.strip().strip('"')
    return result


def _build_once(root: Path, label: str, lock: dict[str, str]) -> tuple[Path, str, str]:
    source = root / f"{label}-source"
    source.mkdir(mode=0o700)
    subprocess.run(["git", "init", "--quiet", str(source)], check=True, env={**os.environ, "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
    subprocess.run(["git", "-C", str(source), "remote", "add", "origin", lock["H003_SOURCE_URL"]], check=True)
    fetch = subprocess.run(
        ["git", "-C", str(source), "fetch", "--depth=1", "origin", lock["H003_SOURCE_COMMIT"]],
        check=False,
        capture_output=True,
        text=True,
    )
    require_source_fetch_success(fetch.returncode)
    subprocess.run(["git", "-C", str(source), "checkout", "--quiet", "--detach", "FETCH_HEAD"], check=True)
    commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    tree = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"], check=True, capture_output=True, text=True).stdout.strip()
    validate_source_identity(commit, tree, lock)
    clean_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(root),
        "LC_ALL": "C",
        "TZ": "UTC",
    }
    subprocess.run(
        [
            "make", "-C", str(source), f"VERSION={lock['H003_SIGNER_VERSION']}",
            "CXX=g++-13", "CXXFLAGS=-O2 -pipe", "LDFLAGS=",
        ],
        check=True,
        env=clean_env,
    )
    binary = source / "ldid"
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise H003Error("corrupt build input: make did not produce a regular executable signer")
    digest = sha256_file(binary)
    return binary, commit, tree


def _build_in_container(output_dir: Path) -> int:
    lock = load_lock()
    os_release = _load_os_release()
    if os_release.get("ID") != "ubuntu" or os_release.get("VERSION_ID") != "24.04":
        raise H003Error("pinned build container operating system identity mismatch")
    require_host_architecture(platform.machine())
    if os.environ.get("H003_IN_PINNED_CONTAINER") != "1":
        raise H003Error("internal H003 container build mode is missing its invocation guard")
    if output_dir.is_symlink() or not output_dir.is_dir() or not os.access(output_dir, os.W_OK):
        raise H003Error("H003 signer output directory is missing or unsafe")
    if any(output_dir.iterdir()):
        raise H003Error("H003 signer output directory must be empty")
    expected_packages = {package: lock[lock_key] for package, lock_key in PACKAGE_LOCK_KEYS.items()}
    for package, expected_version in expected_packages.items():
        actual = subprocess.run(["dpkg-query", "-W", "-f=${Version}", package], check=True, capture_output=True, text=True).stdout.strip()
        if actual != expected_version:
            raise H003Error(f"dependency version mismatch: {package}")
        policy = subprocess.run(["apt-cache", "policy", package], check=True, capture_output=True, text=True).stdout
        if lock["H003_APT_SNAPSHOT"] not in policy:
            raise H003Error(f"dependency origin mismatch: {package}")
    tools = {
        "gcc_version": subprocess.run(["gcc-13", "-dumpfullversion"], check=True, capture_output=True, text=True).stdout.strip(),
        "gxx_version": subprocess.run(["g++-13", "-dumpfullversion"], check=True, capture_output=True, text=True).stdout.strip(),
        "binutils_version": subprocess.run(["ld", "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[0].split()[-1],
        "make_version": subprocess.run(["make", "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[0].removeprefix("GNU Make "),
        "libplist_version": subprocess.run(["pkg-config", "--modversion", "libplist-2.0"], check=True, capture_output=True, text=True).stdout.strip(),
        "openssl_version": subprocess.run(["pkg-config", "--modversion", "openssl"], check=True, capture_output=True, text=True).stdout.strip(),
    }
    for field, lock_key in TOOL_LOCK_KEYS.items():
        if tools[field] != lock[lock_key]:
            raise H003Error(f"toolchain version mismatch: {field}")

    with tempfile.TemporaryDirectory(prefix="ioscaffeinate-h003-build-") as temporary:
        work = Path(temporary)
        os.chmod(work, 0o700)
        first_binary, first_commit, first_tree = _build_once(work, "build-1", lock)
        second_binary, second_commit, second_tree = _build_once(work, "build-2", lock)
        first_digest = sha256_file(first_binary)
        second_digest = sha256_file(second_binary)
        expected = lock["H003_SIGNER_SHA256"]
        if first_digest != expected or second_digest != expected or first_digest != second_digest:
            raise H003Error("SIGNER_REPRODUCTION_MISMATCH: independent signer builds do not match the exact SHA-256 pin")
        validate_source_identity(first_commit, first_tree, lock)
        validate_source_identity(second_commit, second_tree, lock)
        output = output_dir / "ldid"
        if output.exists() or output.is_symlink():
            raise H003Error("refusing to overwrite existing H003 signer output")
        shutil.copyfile(first_binary, output, follow_symlinks=False)
        output.chmod(0o700)
        identity = verify_binary_identity(output, expected, lock["H003_SIGNER_VERSION"])

    apt_snapshot = lock["H003_APT_SNAPSHOT"]
    fields = {
        "source_url": lock["H003_SOURCE_URL"],
        "source_commit_1": first_commit,
        "source_tree_1": first_tree,
        "source_commit_2": second_commit,
        "source_tree_2": second_tree,
        "container_image": os.environ.get("H003_CONTAINER_IMAGE", ""),
        "container_platform": os.environ.get("H003_PLATFORM", ""),
        "ubuntu_id": os_release["ID"],
        "ubuntu_version": os_release["VERSION_ID"],
        "apt_snapshot": apt_snapshot,
        "apt_signature_verification": "VERIFIED_BY_APT",
        "apt_source_origin": apt_snapshot,
        **{f"package.{package}": version for package, version in expected_packages.items()},
        **tools,
        "build_1_sha256": first_digest,
        "build_2_sha256": second_digest,
        "executable_sha256": identity["sha256"],
        "version_banner": f"Link Identity Editor {identity['version']}",
        "binary_architecture": identity["architecture"],
        "binary_elf_class": identity["elf_class"],
        "binary_type": identity["type"],
        "binary_interpreter": identity["interpreter"],
        "result": "VERIFIED",
    }
    validate_build_fields(fields, lock)
    receipt = output_dir / "build-env.txt"
    with receipt.open("x", encoding="utf-8") as stream:
        for key, value in fields.items():
            if "\n" in value or "\r" in value:
                raise H003Error("invalid line break in H003 build receipt")
            stream.write(f"{key}={value}\n")
    receipt.chmod(0o600)
    provenance = make_provenance(fields)
    provenance_path = output_dir / "signer-provenance.json"
    with provenance_path.open("x", encoding="utf-8") as stream:
        json.dump(provenance, stream, indent=2, sort_keys=True)
        stream.write("\n")
    provenance_path.chmod(0o600)
    host_uid = int(os.environ.get("H003_HOST_UID", str(os.getuid())))
    host_gid = int(os.environ.get("H003_HOST_GID", str(os.getgid())))
    os.chown(output, host_uid, host_gid)
    os.chown(receipt, host_uid, host_gid)
    os.chown(provenance_path, host_uid, host_gid)
    print(f"signer_sha256={identity['sha256']}")
    print(f"independent_builds={first_digest},{second_digest}")
    print("signer_provenance=VERIFIED")
    return 0


def _make_ca_bundle(directory: Path) -> Path:
    candidates: list[Path] = []
    configured_bundle = os.environ.get("SSL_CERT_FILE")
    if configured_bundle:
        candidates.append(Path(configured_bundle))
    candidates.append(Path("/etc/ssl/certs/ca-certificates.crt"))
    bundle_parts: list[bytes] = []
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            bundle_parts.append(candidate.read_bytes())
            break
    proxy_certificate = os.environ.get("CODEX_PROXY_CERT")
    if proxy_certificate:
        path = Path(proxy_certificate)
        if not path.is_file() or path.is_symlink():
            raise H003Error("configured HTTPS proxy certificate is unavailable")
        bundle_parts.append(path.read_bytes())
    if not bundle_parts:
        raise H003Error("host CA bundle is unavailable for the pinned build container")
    destination = directory / "ca-bundle.pem"
    destination.write_bytes(b"\n".join(bundle_parts))
    destination.chmod(0o644)
    return destination


def _prepare_output_dir(path: Path) -> Path:
    if path.is_symlink():
        raise H003Error("H003 signer output directory must not be a symlink")
    if path.exists() and not path.is_dir():
        raise H003Error("H003 signer output path is not a directory")
    if path.exists() and any(path.iterdir()):
        raise H003Error("H003 signer output directory must be empty")
    old_umask = os.umask(0o077)
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    finally:
        os.umask(old_umask)
    path.chmod(0o700)
    return path.resolve()


def _run_build(output_arg: Path) -> int:
    lock = load_lock()
    require_host_architecture(platform.machine())
    docker = shutil.which("docker")
    if docker is None:
        raise H003Error("pinned Docker build environment is unavailable")
    output_dir = _prepare_output_dir(output_arg.absolute())
    pulled = subprocess.run([docker, "pull", lock["H003_CONTAINER_IMAGE"]], check=False, capture_output=True, text=True)
    if pulled.returncode != 0:
        raise H003Error("pinned Ubuntu build image is unavailable")
    inspected = subprocess.run(
        [docker, "image", "inspect", "--format", "{{json .RepoDigests}}", lock["H003_CONTAINER_IMAGE"]],
        check=False,
        capture_output=True,
        text=True,
    )
    if inspected.returncode != 0:
        raise H003Error("pinned Ubuntu build image identity could not be inspected")
    try:
        repo_digests = json.loads(inspected.stdout.strip())
    except json.JSONDecodeError:
        raise H003Error("pinned Ubuntu build image digest response is malformed") from None
    if lock["H003_CONTAINER_IMAGE"] not in repo_digests:
        raise H003Error("pinned Ubuntu build image digest does not match the H003 lock")

    with tempfile.TemporaryDirectory(prefix="ioscaffeinate-h003-") as temporary:
        scratch = Path(temporary)
        os.chmod(scratch, 0o700)
        ca_bundle = _make_ca_bundle(scratch)
        sources = scratch / "ubuntu.sources"
        suites = lock["H003_APT_SUITES"].replace(",", " ")
        sources.write_text(
            "Types: deb\n"
            f"URIs: {lock['H003_APT_SNAPSHOT']}/\n"
            f"Suites: {suites}\n"
            "Components: main universe restricted multiverse\n"
            "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n",
            encoding="utf-8",
        )
        sources.chmod(0o600)
        for path in (ROOT, output_dir, ca_bundle, sources):
            if "," in str(path):
                raise H003Error("H003 bind mount paths must not contain commas")
        command = [
            docker, "run", "--rm", f"--platform={lock['H003_PLATFORM']}", "--user=0:0",
            "--env", "H003_IN_PINNED_CONTAINER=1",
            "--env", f"H003_CONTAINER_IMAGE={lock['H003_CONTAINER_IMAGE']}",
            "--env", f"H003_PLATFORM={lock['H003_PLATFORM']}",
            "--env", "H003_OUTPUT_DIR=/output",
            "--env", f"H003_HOST_UID={os.getuid()}",
            "--env", f"H003_HOST_GID={os.getgid()}",
            "--mount", f"type=bind,src={ROOT},dst=/workspace,readonly",
            "--mount", f"type=bind,src={output_dir},dst=/output",
            "--mount", f"type=bind,src={sources},dst=/run/h003.sources,readonly",
            "--mount", f"type=bind,src={ca_bundle},dst=/run/h003-ca.pem,readonly",
            lock["H003_CONTAINER_IMAGE"],
            "bash", "/workspace/scripts/h003_build_signer_container.sh",
        ]
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise H003Error(f"pinned H003 signer build failed with exit status {result.returncode}")

    fields = _parse_fields(output_dir / "build-env.txt")
    validate_build_fields(fields, lock)
    identity = verify_binary_identity(output_dir / "ldid", lock["H003_SIGNER_SHA256"], lock["H003_SIGNER_VERSION"])
    if identity["architecture"] != "x86_64":
        raise H003Error("WRONG_HOST_ARCHITECTURE: signer executable is not x86_64")
    provenance = make_provenance(fields)
    provenance_path = output_dir / "signer-provenance.json"
    if provenance_path.exists() or provenance_path.is_symlink():
        try:
            recorded_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise H003Error("H003 signer provenance JSON is malformed") from None
        if recorded_provenance != provenance:
            raise H003Error("H003 signer provenance JSON differs from the validated build receipt")
    else:
        with provenance_path.open("x", encoding="utf-8") as stream:
            json.dump(provenance, stream, indent=2, sort_keys=True)
            stream.write("\n")
        provenance_path.chmod(0o600)
    print(f"signer_source={fields['source_commit_1']} tree={fields['source_tree_1']}")
    print(f"signer_version={identity['version']}")
    print(f"signer_sha256={identity['sha256']}")
    print("signer_provenance=VERIFIED")
    print(f"signer_receipt={provenance_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build the pinned signer in an isolated digest-pinned container")
    build.add_argument("--output-dir", required=True, type=Path, help="empty private directory for the verified executable and receipt")
    internal = subparsers.add_parser("build-in-container", help=argparse.SUPPRESS)
    internal.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            return _run_build(args.output_dir)
        return _build_in_container(args.output_dir)
    except (H003Error, OSError, subprocess.SubprocessError) as error:
        print(str(error) or type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
