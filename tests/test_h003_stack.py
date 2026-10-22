"""Stacked branch contract tests for H003 and the unchanged P020 release gate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import h003_stack as stack  # noqa: E402


class H003StackTests(unittest.TestCase):
    def records(self) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        main_sha = "7dbd47e4500c0ddf3d65d282d8e6a8881d6c8703"
        source_sha = "a" * 40
        current = {
            "state": "open", "merged_at": None,
            "head": {"ref": stack.H003_BRANCH, "sha": source_sha},
            "base": {"ref": stack.H002_BRANCH, "sha": stack.H002_SHA},
        }
        h002 = {
            "state": "open", "merged_at": None,
            "head": {"ref": stack.H002_BRANCH, "sha": stack.H002_SHA},
            "base": {"ref": stack.P020_BRANCH, "sha": stack.P020_SHA},
        }
        p020 = {
            "state": "open", "merged_at": None,
            "head": {"ref": stack.P020_BRANCH, "sha": stack.P020_SHA},
            "base": {"ref": "main", "sha": main_sha},
        }
        return current, h002, p020

    def valid_result(self) -> dict[str, str]:
        current, h002, p020 = self.records()
        source_sha = current["head"]["sha"]
        return stack.validate_h003_stack(
            current_pr=current,
            h002_pr=h002,
            p020_pr=p020,
            h002_branch_sha=stack.H002_SHA,
            p020_branch_sha=stack.P020_SHA,
            main_sha=p020["base"]["sha"],
            source_sha=source_sha,
            is_ancestor=lambda ancestor, commit: ancestor in {stack.P020_SHA, stack.H002_SHA} and commit in {stack.H002_SHA, source_sha} and ancestor != commit,
            merge_base=lambda left, right: right,
        )

    def test_exact_h003_over_h002_over_p020_stack_is_accepted(self) -> None:
        self.assertEqual(self.valid_result(), {"branch": "main", "sha": "7dbd47e4500c0ddf3d65d282d8e6a8881d6c8703"})

    def test_h003_wrong_base_sha_is_rejected(self) -> None:
        current, h002, p020 = self.records()
        current["base"]["sha"] = "0" * 40
        with self.assertRaisesRegex(stack.StackValidationError, "pinned H002"):
            self.validate(current, h002, p020)

    def test_h002_wrong_head_is_rejected(self) -> None:
        current, h002, p020 = self.records()
        h002["head"]["sha"] = "0" * 40
        with self.assertRaisesRegex(stack.StackValidationError, "H002 predecessor head"):
            self.validate(current, h002, p020)

    def test_unrelated_branch_is_rejected(self) -> None:
        current, h002, p020 = self.records()
        current["head"]["ref"] = "feature/unrelated"
        with self.assertRaisesRegex(stack.StackValidationError, "not the exact H003"):
            self.validate(current, h002, p020)

    def test_unrelated_ancestry_is_rejected(self) -> None:
        current, h002, p020 = self.records()
        with self.assertRaisesRegex(stack.StackValidationError, "preserve the P020-to-H002 ancestry"):
            self.validate(current, h002, p020, is_ancestor=lambda _ancestor, _commit: False)

    def validate(self, current: dict[str, object], h002: dict[str, object], p020: dict[str, object], *, is_ancestor=None) -> dict[str, str]:
        source_sha = current["head"]["sha"]
        return stack.validate_h003_stack(
            current_pr=current,
            h002_pr=h002,
            p020_pr=p020,
            h002_branch_sha=stack.H002_SHA,
            p020_branch_sha=stack.P020_SHA,
            main_sha=p020["base"]["sha"],
            source_sha=source_sha,
            is_ancestor=is_ancestor or (lambda ancestor, commit: ancestor in {stack.P020_SHA, stack.H002_SHA} and commit in {stack.H002_SHA, source_sha} and ancestor != commit),
            merge_base=lambda left, right: right,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
