"""Strict ancestry contract tests for H004 stacked on H003."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import h004_stack as stack  # noqa: E402


class H004StackTests(unittest.TestCase):
    def records(self) -> tuple[dict[str, object], ...]:
        main_sha = "7dbd47e4500c0ddf3d65d282d8e6a8881d6c8703"
        source_sha = "a" * 40
        current = {
            "state": "open", "merged_at": None,
            "head": {"ref": stack.H004_BRANCH, "sha": source_sha},
            "base": {"ref": stack.H003_BRANCH, "sha": stack.H003_SHA},
        }
        h003 = {
            "state": "open", "merged_at": None,
            "head": {"ref": stack.H003_BRANCH, "sha": stack.H003_SHA},
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
        return current, h003, h002, p020

    def validate(self, current, h003, h002, p020, *, is_ancestor=None, merge_base=None,
                 source_sha=None):
        source_sha = source_sha or current["head"]["sha"]
        h004_head_sha = current["head"]["sha"]
        return stack.validate_h004_stack(
            current_pr=current,
            h003_pr=h003,
            h002_pr=h002,
            p020_pr=p020,
            h003_branch_sha=stack.H003_SHA,
            h002_branch_sha=stack.H002_SHA,
            p020_branch_sha=stack.P020_SHA,
            main_sha=p020["base"]["sha"],
            source_sha=source_sha,
            is_ancestor=is_ancestor or (
                lambda ancestor, commit: ancestor in {
                    stack.P020_SHA, stack.H002_SHA, stack.H003_SHA,
                } and commit in {
                    stack.H002_SHA, stack.H003_SHA, source_sha, h004_head_sha,
                } and ancestor != commit
            ),
            merge_base=merge_base or (lambda _left, right: right),
        )

    def test_exact_h004_over_h003_over_h002_over_p020_is_accepted(self) -> None:
        current, h003, h002, p020 = self.records()
        self.assertEqual(self.validate(current, h003, h002, p020), {
            "branch": "main", "sha": p020["base"]["sha"],
        })

    def test_h004_wrong_base_sha_is_rejected(self) -> None:
        current, h003, h002, p020 = self.records()
        current["base"]["sha"] = "0" * 40
        with self.assertRaisesRegex(stack.H004StackValidationError, "exact H003"):
            self.validate(current, h003, h002, p020)

    def test_h003_predecessor_must_be_exact_and_open(self) -> None:
        current, h003, h002, p020 = self.records()
        h003["head"]["sha"] = "0" * 40
        with self.assertRaisesRegex(stack.H004StackValidationError, "H003 predecessor stack"):
            self.validate(current, h003, h002, p020)

    def test_unrelated_h004_ancestry_is_rejected(self) -> None:
        current, h003, h002, p020 = self.records()
        def reject_h004_edge(ancestor, commit):
            if ancestor == stack.H003_SHA and commit == current["head"]["sha"]:
                return False
            return ancestor in {stack.P020_SHA, stack.H002_SHA, stack.H003_SHA} and commit in {
                stack.H002_SHA, stack.H003_SHA,
            } and ancestor != commit
        with self.assertRaisesRegex(stack.H004StackValidationError, "not descended"):
            self.validate(current, h003, h002, p020, is_ancestor=reject_h004_edge)

    def test_h004_head_must_be_exact_source(self) -> None:
        current, h003, h002, p020 = self.records()
        with self.assertRaisesRegex(stack.H004StackValidationError, "exact H004"):
            self.validate(current, h003, h002, p020, source_sha="b" * 40)


if __name__ == "__main__":
    unittest.main(verbosity=2)
