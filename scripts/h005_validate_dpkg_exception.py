#!/usr/bin/env python3
"""Check a private H005 dpkg audit capture's expected metadata-package shape.

This tool never accepts the exception. A successful structural check always
requires independent human review of the preserved raw captures.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


AUDIT_HEADER = (
    "The following packages are missing the md5sums control file in the",
    "database, they need to be reinstalled:",
)
EXPECTED_COUNTS = {
    "gsc.": 166,
    "cy+cpu.": 2,
    "cy+kernel.": 1,
    "cy+lib.": 1,
    "cy+model.": 1,
    "cy+os.": 1,
    "firmware": 1,
}


class ValidationFailure(Exception):
    pass


@dataclass(frozen=True)
class PackageRecord:
    package: str
    status: str
    version: str
    architecture: str
    essential: str
    installed_size: str
    description: str


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValidationFailure(f"cannot read capture {path}: {exc}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationFailure(message)


def expected_description(package: str) -> str:
    if package == "firmware":
        return "almost impressive Apple frameworks"
    if package.startswith("gsc."):
        return ("this device has a very large screen"
                if package in {"gsc.ipad", "gsc.wildcat"}
                else "virtual GraphicsServices dependency")
    if package.startswith("cy+cpu."):
        return "virtual CPU dependency"
    if package.startswith("cy+kernel."):
        return "virtual kernel dependency"
    if package.startswith("cy+lib."):
        return "virtual corefoundation dependency"
    if package.startswith("cy+model."):
        return "virtual model dependency"
    if package.startswith("cy+os."):
        return "virtual operating system dependency"
    raise ValidationFailure(f"unrecognized pseudo-package name: {package}")


def parse_audit(stdout: str, stderr: str, exit_code: int) -> list[str]:
    require(exit_code == 0, "dpkg --audit did not exit 0")
    require(stderr == "", "dpkg --audit wrote to stderr; review required")
    lines = stdout.splitlines()
    require(tuple(lines[:2]) == AUDIT_HEADER,
            "audit output does not contain the exact missing-md5sums warning")
    packages: list[str] = []
    for line in lines[2:]:
        if line == "":
            continue
        parts = line.strip().split(None, 1)
        require(line.startswith(" ") and parts,
                "audit output contains another warning or extra text")
        package = parts[0]
        require(all(character.islower() or character.isdigit() or character in ".+-"
                    for character in package), f"unsafe package token in audit output: {package!r}")
        if len(parts) > 1:
            require(parts[1] == expected_description(package),
                    f"audit description does not match pseudo-package {package}")
        packages.append(package)

    require(len(packages) == 173, f"expected 173 warning entries, found {len(packages)}")
    require(len(set(packages)) == len(packages), "audit output contains duplicate package names")
    for prefix, expected in EXPECTED_COUNTS.items():
        actual = sum(1 for package in packages if package.startswith(prefix))
        require(actual == expected,
                f"expected {expected} entries for {prefix!r}, found {actual}")
    recognized = set()
    for package in packages:
        if package.startswith("gsc."):
            recognized.add(package)
        elif package.startswith("cy+cpu."):
            recognized.add(package)
        elif package.startswith("cy+kernel."):
            recognized.add(package)
        elif package.startswith("cy+lib."):
            recognized.add(package)
        elif package.startswith("cy+model."):
            recognized.add(package)
        elif package.startswith("cy+os."):
            recognized.add(package)
        elif package == "firmware":
            recognized.add(package)
    require(recognized == set(packages), "audit contains an unrecognized package category")
    canonical = {
        "firmware", "cy+os.ios", "cy+cpu.arm64", "cy+kernel.darwin",
        "cy+lib.corefoundation", "cy+model.ipad",
    }
    require(canonical <= set(packages),
            "audit set is missing one or more target-specific pseudo-package identities")
    return packages


def parse_records(text: str, stderr: str, exit_code: int) -> dict[str, PackageRecord]:
    require(exit_code == 0, "dpkg-query package-record command did not exit 0")
    require(stderr == "", "dpkg-query package-record command wrote to stderr")
    records: dict[str, PackageRecord] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        fields = line.split("\t")
        require(len(fields) == 7, f"package record line {line_number} does not have seven fields")
        record = PackageRecord(*fields)
        require(record.package not in records, f"duplicate package database record: {record.package}")
        require(record.status == "install ok installed",
                f"package {record.package} has status {record.status!r}")
        require(record.version != "", f"package {record.package} has an empty version")
        require(record.architecture == "iphoneos-arm",
                f"package {record.package} has unexpected architecture {record.architecture!r}")
        require(record.essential == "yes", f"package {record.package} is not marked Essential: yes")
        require(record.installed_size == "0",
                f"package {record.package} has Installed-Size {record.installed_size!r}")
        if record.package == "firmware":
            require(record.version == "12.5.7",
                    "firmware pseudo-package version does not match the reported iOS target")
        elif record.package.startswith("gsc."):
            pass
        elif record.package.startswith("cy+cpu."):
            if record.package == "cy+cpu.arm64":
                require(record.version == "0", "cy+cpu.arm64 version is not the generator value 0")
        elif record.package.startswith("cy+kernel."):
            pass
        elif record.package.startswith("cy+lib."):
            pass
        elif record.package.startswith("cy+model."):
            if record.package == "cy+model.ipad":
                require(record.version == "4.4",
                        "cy+model.ipad version does not match iPad4,4 normalization")
        elif record.package.startswith("cy+os."):
            if record.package == "cy+os.ios":
                require(record.version == "12.5.7",
                        "cy+os.ios version does not match the reported iOS target")
        else:
            raise ValidationFailure(f"unrecognized pseudo-package name: {record.package}")
        require(record.description == expected_description(record.package),
                f"package {record.package} description does not match the metadata-package hypothesis")
        records[record.package] = record
    return records


def parse_file_lists(text: str, stderr: str, wrapper_exit_code: int) -> dict[str, list[str]]:
    require(wrapper_exit_code == 0, "dpkg-query -L wrapper did not exit 0")
    require(stderr == "", "one or more dpkg-query -L calls wrote to stderr")
    results: dict[str, list[str]] = {}
    active_package: str | None = None
    active_paths: list[str] = []
    saw_exit = False

    for line_number, line in enumerate(text.splitlines(), start=1):
        fields = line.split("\t")
        if len(fields) == 2 and fields[0] == "PACKAGE":
            require(active_package is None,
                    f"file-list capture starts a package before closing line {line_number}")
            active_package = fields[1]
            require(active_package not in results, f"duplicate file-list capture: {active_package}")
            active_paths = []
            saw_exit = False
        elif len(fields) == 3 and fields[0] == "EXIT":
            package, code = fields[1], fields[2]
            require(active_package == package, f"file-list exit marker mismatch at line {line_number}")
            require(code == "0", f"dpkg-query -L {package} exited {code}")
            results[package] = active_paths
            active_package = None
            active_paths = []
            saw_exit = True
        else:
            require(active_package is not None,
                    f"unframed output in file-list capture at line {line_number}")
            active_paths.append(line)
            saw_exit = False

    require(active_package is None and saw_exit or not text,
            "file-list capture ended without a per-package exit marker")
    return results


def parse_info_files(text: str, stderr: str, exit_code: int) -> dict[str, tuple[str, str]]:
    require(exit_code == 0, "dpkg info-file metadata wrapper did not exit 0")
    require(stderr == "", "dpkg info-file metadata wrapper wrote to stderr")
    results: dict[str, tuple[str, str]] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        fields = line.split("\t")
        require(len(fields) == 3, f"info-file record line {line_number} does not have three fields")
        package, list_state, md5sums_state = fields
        require(package not in results, f"duplicate info-file record: {package}")
        require(list_state == "REGULAR", f"package {package} list file is {list_state!r}")
        require(md5sums_state == "ABSENT",
                f"package {package} md5sums file is {md5sums_state!r}")
        results[package] = (list_state, md5sums_state)
    return results


def validate(arguments: argparse.Namespace) -> list[str]:
    packages = parse_audit(read_text(arguments.audit_stdout),
                           read_text(arguments.audit_stderr), arguments.audit_exit_code)
    package_set = set(packages)

    records = parse_records(read_text(arguments.records),
                            read_text(arguments.records_stderr), arguments.records_exit_code)
    require(set(records) == package_set,
            "package database records do not exactly cover the complete audit package set")

    file_lists = parse_file_lists(read_text(arguments.file_lists),
                                  read_text(arguments.file_lists_stderr),
                                  arguments.file_lists_exit_code)
    require(set(file_lists) == package_set,
            "dpkg-query -L captures do not exactly cover the complete audit package set")
    for package, paths in file_lists.items():
        require(paths == ["/."] ,
                f"package {package} has file-list entries other than the lone /. marker")

    info_files = parse_info_files(read_text(arguments.info_files),
                                  read_text(arguments.info_files_stderr),
                                  arguments.info_files_exit_code)
    require(set(info_files) == package_set,
            "dpkg info-file records do not exactly cover the complete audit package set")

    return packages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("audit-stdout", "audit-stderr", "records", "records-stderr",
                 "file-lists", "file-lists-stderr", "info-files", "info-files-stderr"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("audit-exit-code", "records-exit-code", "file-lists-exit-code",
                 "info-files-exit-code"):
        parser.add_argument(f"--{name}", required=True, type=int)
    arguments = parser.parse_args()

    try:
        packages = validate(arguments)
    except ValidationFailure as exc:
        print(f"H005_DPKG_AUDIT_NOT_VALIDATED: {exc}", file=sys.stderr)
        return 2

    print("H005_DPKG_AUDIT_TECHNICAL_SHAPE_MATCH_REVIEW_REQUIRED")
    print(f"audit_entries={len(packages)}")
    print("human_review=REQUIRED")
    print("exception_accepted=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
