#!/usr/bin/env python3
"""Capture and verify exact unsigned v0.2 candidate build provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/v0.2/P020-BUILD-PROVENANCE.schema.json"
sys.path.insert(0, str(ROOT / "scripts"))
import p012_common  # noqa: E402
from validate_rootful_package import inspect_package  # noqa: E402
from signing_profile import PROFILE_RELATIVE_PATH, sha256 as file_sha256  # noqa: E402


class ProvenanceError(ValueError):
    pass


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ProvenanceError(f"expected regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 4 * 1024 * 1024:
        raise ProvenanceError(f"unsafe JSON input: {path}")
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ProvenanceError(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read strict JSON {path}: {exc}") from None
    if not isinstance(value, dict):
        raise ProvenanceError(f"JSON root must be an object: {path}")
    return value


def git_value(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def relative_record(path: Path, output_dir: Path) -> dict[str, str]:
    absolute = path.resolve(strict=True)
    base = output_dir.resolve(strict=True)
    try:
        relative = absolute.relative_to(base)
    except ValueError:
        raise ProvenanceError(f"artifact must be under provenance output directory: {path}") from None
    return {"path": relative.as_posix(), "sha256": sha256(absolute)}


def _package_version(package: Path) -> str:
    result = subprocess.run(["dpkg-deb", "--field", str(package), "Version"], capture_output=True, text=True)
    if result.returncode:
        raise ProvenanceError("dpkg-deb could not inspect candidate package version")
    return result.stdout.strip()


def _package_tool_version() -> str:
    result = subprocess.run(["dpkg-deb", "--version"], capture_output=True, text=True)
    if result.returncode:
        raise ProvenanceError("dpkg-deb version could not be recorded")
    first_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    if not first_line:
        raise ProvenanceError("dpkg-deb returned an empty version string")
    return first_line


def _compare_inputs(first: dict[str, Any], second: dict[str, Any]) -> bool:
    keys = ("source_commit_sha", "package_version", "target_triple", "minimum_ios_version", "build_kind", "release_channel", "xcode", "clang", "sdk")
    return all(first.get(key) == second.get(key) for key in keys)


def _hashes_match(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return all(first[key]["sha256"] == second[key]["sha256"] for key in ("cli", "daemon", "package"))


def _content_comparison(first: Path, second: Path) -> str:
    left, right = first.read_bytes(), second.read_bytes()
    if left == right:
        return "byte-for-byte identical"
    limit = min(len(left), len(right))
    differing = sum(a != b for a, b in zip(left[:limit], right[:limit]))
    first_offset = next((index for index, (a, b) in enumerate(zip(left, right)) if a != b), limit)
    return f"different: first differing offset {first_offset}, {differing} differing bytes in shared length, lengths {len(left)} and {len(right)}"


def capture(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    outdir = output.parent
    first_info = strict_json(args.first_build_info)
    second_info = strict_json(args.second_build_info)
    source_sha = git_value("rev-parse", "HEAD")
    tree_sha = git_value("rev-parse", "HEAD^{tree}")
    source_date_epoch_text = git_value("show", "-s", "--format=%ct", source_sha)
    if not source_date_epoch_text.isdigit():
        raise ProvenanceError("source commit timestamp is not a valid SOURCE_DATE_EPOCH")
    dirty = bool(git_value("status", "--porcelain", "--untracked-files=no"))
    if first_info.get("source_commit_sha") != source_sha or second_info.get("source_commit_sha") != source_sha:
        raise ProvenanceError("build-info source SHA does not match the checked-out commit")
    if first_info.get("package_version") != "0.2.0~rc1-1" or second_info.get("package_version") != "0.2.0~rc1-1":
        raise ProvenanceError("both candidate builds must use package version 0.2.0~rc1-1")
    if first_info.get("signing_status") != "UNSIGNED" or second_info.get("signing_status") != "UNSIGNED":
        raise ProvenanceError("cloud candidate inputs must be unsigned")
    if _package_version(args.first_package) != "0.2.0~rc1-1" or _package_version(args.second_package) != "0.2.0~rc1-1":
        raise ProvenanceError("candidate Debian package identity has the wrong version")
    for package in (args.first_package, args.second_package):
        inspect_package(package, expected_version="0.2.0~rc1-1")
    first = {
        "cli": relative_record(args.first_binary_dir / "ios-caffeinate", outdir),
        "daemon": relative_record(args.first_binary_dir / "ios-caffeinated", outdir),
        "package": relative_record(args.first_package, outdir),
    }
    second = {
        "cli": relative_record(args.second_binary_dir / "ios-caffeinate", outdir),
        "daemon": relative_record(args.second_binary_dir / "ios-caffeinated", outdir),
        "package": relative_record(args.second_package, outdir),
    }
    inputs_match = _compare_inputs(first_info, second_info)
    hashes_match = _hashes_match(first, second)
    if inputs_match and hashes_match:
        repro_status = "REPRODUCIBLE"
        analysis = "Two independent clean-checkout builds used matching recorded source, SDK, compiler, and package inputs; CLI, daemon, and package bytes matched exactly."
    elif inputs_match:
        repro_status = "NON_REPRODUCIBLE"
        analysis = "Two independent builds had matching recorded inputs but one or more artifact hashes differed. Binary byte comparisons and package payload checks are retained as CI diagnostics; timestamp, archive ordering, metadata, and linker UUID differences require review before a reproducibility claim."
    else:
        repro_status = "INCONCLUSIVE"
        analysis = "The two builds did not record identical source, SDK, compiler, or build settings; byte equality is not a controlled reproducibility result."
    profile_path = ROOT / PROFILE_RELATIVE_PATH
    manifest = {
        "schema_version": 1,
        "candidate_state": "UNSIGNED_DEVELOPMENT",
        "source": {
            "repository": "nghianguyen150612/iOS-Caffeinate",
            "branch": args.branch,
            "commit_sha": source_sha,
            "tree_sha": tree_sha,
            "worktree_clean": not dirty and first_info.get("source_tree_clean") is True and second_info.get("source_tree_clean") is True,
        },
        "build_configuration": {
            "compiler_flags": ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-target arm64-apple-ios12.0", "-Wl,-no_adhoc_codesign"],
            "target_triple": first_info["target_triple"],
            "deployment_target": first_info["minimum_ios_version"],
            "build_kind": first_info["build_kind"],
            "release_channel": first_info["release_channel"],
            "source_date_epoch": int(source_date_epoch_text),
        },
        "toolchain": {
            "compiler": "Apple Clang",
            "compiler_version": first_info["clang"],
            "sdk_name": first_info["sdk"]["name"],
            "sdk_version": first_info["sdk"]["version"],
            "xcode_version": first_info["xcode"],
            "package_tool": "dpkg-deb",
            "package_tool_version": _package_tool_version(),
        },
        "target": {
            "device": "iPad mini 2 A1489 (iPad4,4)",
            "cpu": "Apple A7 ARM64",
            "ios": "12.5.7",
            "bootstrap": "Amethyst/Procursus rootful",
            "debian_architecture": "iphoneos-arm",
            "binary_architecture": "arm64 Mach-O",
            "minimum_ios_version": "12.0",
        },
        "dependencies": ["/usr/lib/libSystem.B.dylib", "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"],
        "package": {"identifier": "com.ioscaffeinate.cli", "version": "0.2.0~rc1-1", "architecture": "iphoneos-arm"},
        "artifacts": {
            "cli": first["cli"], "daemon": first["daemon"], "package": first["package"],
            "second_build_cli": second["cli"], "second_build_daemon": second["daemon"], "second_build_package": second["package"],
        },
        "signing": {
            "state": "UNSIGNED", "profile_id": "amethyst-ios12-rootful", "profile_sha256": file_sha256(profile_path),
            "signing_tool_version": None, "signing_tool_sha256": None, "provenance_status": "SIGNER_PROVENANCE_BLOCKED",
        },
        "reproducibility": {
            "status": repro_status, "independent_builds": 2, "inputs_match": inputs_match,
            "artifact_hashes_match": hashes_match,
            "analysis": analysis + " CLI: " + _content_comparison(args.first_binary_dir / "ios-caffeinate", args.second_binary_dir / "ios-caffeinate") + "; daemon: " + _content_comparison(args.first_binary_dir / "ios-caffeinated", args.second_binary_dir / "ios-caffeinated") + "; package: " + _content_comparison(args.first_package, args.second_package),
        },
        "ci": {
            "workflow": "iOS-Caffeinate CI / p020-release-readiness-validation",
            "run_id": args.run_id,
            "run_url": args.run_url,
            "event": args.event,
            "source_sha_verified": True,
        },
        "validation": {
            "macho_inspection": "PASS", "package_inspection": "PASS", "payload_hashes": "PASS",
            "maintainer_scripts": "PASS", "persistent_state_seeded": False,
            "device_installation": "NOT_PERFORMED", "release_authorization": "BLOCKED",
        },
    }
    schema = strict_json(SCHEMA_PATH)
    issues = p012_common.validate_json_schema(manifest, schema)
    if issues:
        raise ProvenanceError("generated provenance does not match its schema: " + "; ".join(issues))
    if output.exists() or output.is_symlink():
        raise ProvenanceError("provenance output already exists; refusing overwrite")
    output.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate(args: argparse.Namespace) -> dict[str, Any]:
    manifest = strict_json(args.manifest)
    schema = strict_json(SCHEMA_PATH)
    issues = p012_common.validate_json_schema(manifest, schema)
    if issues:
        raise ProvenanceError("provenance schema validation failed: " + "; ".join(issues))
    root = args.manifest.parent.resolve(strict=True)
    for item in manifest["artifacts"].values():
        path = Path(item["path"])
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ProvenanceError("artifact path must be relative and traversal-free")
        target = root / path
        if sha256(target) != item["sha256"]:
            raise ProvenanceError(f"artifact SHA-256 mismatch: {item['path']}")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    cmd = subs.add_parser("capture")
    cmd.add_argument("--first-build-info", type=Path, required=True)
    cmd.add_argument("--first-binary-dir", type=Path, required=True)
    cmd.add_argument("--first-package", type=Path, required=True)
    cmd.add_argument("--second-build-info", type=Path, required=True)
    cmd.add_argument("--second-binary-dir", type=Path, required=True)
    cmd.add_argument("--second-package", type=Path, required=True)
    cmd.add_argument("--branch", required=True)
    cmd.add_argument("--run-id", required=True)
    cmd.add_argument("--run-url", required=True)
    cmd.add_argument("--event", choices=("pull_request", "push", "workflow_dispatch"), required=True)
    cmd.add_argument("--output", type=Path, required=True)
    check = subs.add_parser("validate")
    check.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = capture(args) if args.command == "capture" else validate(args)
    except (ProvenanceError, OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
