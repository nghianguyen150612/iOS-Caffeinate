from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from scripts import h005_validate_dpkg_exception as audit


def expected_packages() -> list[str]:
    names = ["gsc.ipad", "gsc.wildcat"]
    names.extend(f"gsc.mock{i:03d}" for i in range(164))
    names.extend(("cy+cpu.arm", "cy+cpu.arm64", "cy+kernel.darwin", "cy+lib.corefoundation",
                  "cy+model.ipad", "cy+os.ios", "firmware"))
    return names


def audit_output(names: list[str]) -> str:
    return "\n".join(audit.AUDIT_HEADER) + "\n" + "".join(f"  {name}\n" for name in names) + "\n"


def record_rows(names: list[str]) -> str:
    lines = []
    for package in names:
        if package == "firmware" or package == "cy+os.ios":
            version = "12.5.7"
        elif package == "cy+cpu.arm64":
            version = "0"
        elif package == "cy+model.ipad":
            version = "4.4"
        else:
            version = "18.7.0"
        if package == "firmware":
            description = "almost impressive Apple frameworks"
        elif package.startswith("gsc."):
            description = ("this device has a very large screen"
                           if package in {"gsc.ipad", "gsc.wildcat"}
                           else "virtual GraphicsServices dependency")
        elif package.startswith("cy+cpu."):
            description = "virtual CPU dependency"
        elif package.startswith("cy+kernel."):
            description = "virtual kernel dependency"
        elif package.startswith("cy+lib."):
            description = "virtual corefoundation dependency"
        elif package.startswith("cy+model."):
            description = "virtual model dependency"
        else:
            description = "virtual operating system dependency"
        lines.append(f"{package}\tinstall ok installed\t{version}\tiphoneos-arm\tyes\t0\t{description}")
    return "\n".join(lines) + "\n"


class DpkgAuditExceptionTests(unittest.TestCase):
    def test_exact_missing_md5sums_warning_and_all_173_records(self) -> None:
        names = expected_packages()
        parsed = audit.parse_audit(audit_output(names), "", 0)
        self.assertEqual(set(parsed), set(names))

    def test_dpkg_package_rows_with_descriptions_are_checked(self) -> None:
        names = expected_packages()
        output = "\n".join(audit.AUDIT_HEADER) + "\n"
        output += "".join(f" {name}  {audit.expected_description(name)}\n" for name in names)
        output += "\n"
        self.assertEqual(set(audit.parse_audit(output, "", 0)), set(names))
        malformed = output.replace("virtual CPU dependency", "not a virtual package", 1)
        with self.assertRaisesRegex(audit.ValidationFailure, "description does not match"):
            audit.parse_audit(malformed, "", 0)

    def test_empty_output_does_not_clear_the_gate(self) -> None:
        with self.assertRaisesRegex(audit.ValidationFailure, "exact missing-md5sums warning"):
            audit.parse_audit("", "", 0)

    def test_other_warning_categories_or_extra_text_fail(self) -> None:
        names = expected_packages()
        output = audit_output(names) + "The following packages are unpacked but not configured:\n"
        with self.assertRaisesRegex(audit.ValidationFailure, "another warning or extra text"):
            audit.parse_audit(output, "", 0)

    def test_wrong_category_counts_and_duplicates_fail(self) -> None:
        names = expected_packages()
        names[-1] = "other.package"
        with self.assertRaisesRegex(audit.ValidationFailure, "expected 1 entries for 'firmware'"):
            audit.parse_audit(audit_output(names), "", 0)
        names = expected_packages()
        names[-1] = "gsc.mock000"
        with self.assertRaisesRegex(audit.ValidationFailure, "duplicate package names"):
            audit.parse_audit(audit_output(names), "", 0)

    def test_incomplete_or_inconsistent_query_records_fail(self) -> None:
        names = expected_packages()
        lines = record_rows(names)
        parsed = audit.parse_records(lines, "", 0)
        self.assertEqual(set(parsed), set(names))
        bad = lines.replace("install ok installed", "deinstall ok config-files", 1)
        with self.assertRaisesRegex(audit.ValidationFailure, "has status"):
            audit.parse_records(bad, "", 0)

    def test_complete_private_capture_shape_requires_matching_sets(self) -> None:
        names = expected_packages()
        with tempfile.TemporaryDirectory(prefix="h005-dpkg-shape-") as temp_dir:
            root = Path(temp_dir)
            capture = {
                "audit_stdout": audit_output(names),
                "audit_stderr": "",
                "records": record_rows(names),
                "records_stderr": "",
                "file_lists": "".join(
                    f"PACKAGE\t{name}\n/.\nEXIT\t{name}\t0\n" for name in names
                ),
                "file_lists_stderr": "",
                "info_files": "".join(
                    f"{name}\tREGULAR\tABSENT\n" for name in names
                ),
                "info_files_stderr": "",
            }
            paths = {}
            for key, value in capture.items():
                path = root / f"{key}.txt"
                path.write_text(value, encoding="utf-8")
                paths[key] = path
            arguments = argparse.Namespace(
                audit_stdout=paths["audit_stdout"], audit_stderr=paths["audit_stderr"],
                audit_exit_code=0, records=paths["records"], records_stderr=paths["records_stderr"],
                records_exit_code=0, file_lists=paths["file_lists"],
                file_lists_stderr=paths["file_lists_stderr"], file_lists_exit_code=0,
                info_files=paths["info_files"], info_files_stderr=paths["info_files_stderr"],
                info_files_exit_code=0,
            )
            self.assertEqual(set(audit.validate(arguments)), set(names))
            paths["records"].write_text(record_rows(names[:-1]), encoding="utf-8")
            with self.assertRaisesRegex(audit.ValidationFailure, "exactly cover"):
                audit.validate(arguments)

    def test_full_file_list_set_requires_only_root_marker(self) -> None:
        names = expected_packages()
        raw = "".join(f"PACKAGE\t{name}\n/.\nEXIT\t{name}\t0\n" for name in names)
        parsed = audit.parse_file_lists(raw, "", 0)
        self.assertEqual(set(parsed), set(names))
        bad = raw.replace("/.\n", "/.\n/usr/bin/unexpected\n", 1)
        parsed_bad = audit.parse_file_lists(bad, "", 0)
        self.assertNotEqual(parsed_bad[names[0]], ["/."])

    def test_human_review_is_never_auto_accepted(self) -> None:
        source = (audit.__doc__ or "")
        self.assertIn("This tool never accepts the exception.", source)
        self.assertIn("human review", source)

    def test_present_md5sums_or_non_regular_list_blocks_exception(self) -> None:
        with self.assertRaisesRegex(audit.ValidationFailure, "md5sums file"):
            audit.parse_info_files("pkg\tREGULAR\tPRESENT\n", "", 0)
        with self.assertRaisesRegex(audit.ValidationFailure, "list file"):
            audit.parse_info_files("pkg\tSYMLINK\tABSENT\n", "", 0)


if __name__ == "__main__":
    unittest.main()
