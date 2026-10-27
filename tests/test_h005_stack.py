from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import h003_stack  # noqa: E402
import h004_stack  # noqa: E402
import h005_stack as stack  # noqa: E402
import r05a_stack  # noqa: E402


class H005StackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = "a" * 40
        self.main = "b" * 40
        self.current = {
            "state": "open", "merged_at": None,
            "head": {"ref": stack.H005_BRANCH, "sha": self.source},
            "base": {"ref": stack.R05A_BRANCH, "sha": stack.H005_BASE_SHA},
        }
        self.r05a = {
            "state": "open", "merged_at": None,
            "head": {"ref": r05a_stack.R05A_BRANCH, "sha": stack.H005_BASE_SHA},
            "base": {"ref": h004_stack.H004_BRANCH, "sha": r05a_stack.R05A_BASE_SHA},
        }
        self.h004 = {
            "state": "open", "merged_at": None,
            "head": {"ref": h004_stack.H004_BRANCH, "sha": r05a_stack.R05A_BASE_SHA},
            "base": {"ref": h003_stack.H003_BRANCH, "sha": h004_stack.H003_SHA},
        }
        self.h003 = {
            "state": "open", "merged_at": None,
            "head": {"ref": h003_stack.H003_BRANCH, "sha": h004_stack.H003_SHA},
            "base": {"ref": h003_stack.H002_BRANCH, "sha": h003_stack.H002_SHA},
        }
        self.h002 = {
            "state": "open", "merged_at": None,
            "head": {"ref": h003_stack.H002_BRANCH, "sha": h003_stack.H002_SHA},
            "base": {"ref": h003_stack.P020_BRANCH, "sha": h003_stack.P020_SHA},
        }
        self.p020 = {
            "state": "open", "merged_at": None,
            "head": {"ref": h003_stack.P020_BRANCH, "sha": h003_stack.P020_SHA},
            "base": {"ref": "main", "sha": self.main},
        }
        self.ancestry = [
            self.main, h003_stack.P020_SHA, h003_stack.H002_SHA,
            h004_stack.H003_SHA, r05a_stack.R05A_BASE_SHA,
            stack.H005_BASE_SHA, self.source,
        ]

    def validate(self, *, current=None, r05a=None, ancestor_override=None):
        def is_ancestor(ancestor: str, commit: str) -> bool:
            if ancestor_override is not None:
                return ancestor_override(ancestor, commit)
            return (ancestor in self.ancestry and commit in self.ancestry and
                    self.ancestry.index(ancestor) < self.ancestry.index(commit))

        def merge_base(left: str, right: str) -> str:
            common = [item for item in self.ancestry if is_ancestor(item, left) or item == left]
            common = [item for item in common if is_ancestor(item, right) or item == right]
            return common[-1] if common else ""

        return stack.validate_h005_stack(
            current_pr=current or self.current,
            r05a_pr=r05a or self.r05a,
            h004_pr=self.h004,
            h003_pr=self.h003,
            h002_pr=self.h002,
            p020_pr=self.p020,
            r05a_branch_sha=stack.H005_BASE_SHA,
            h004_branch_sha=r05a_stack.R05A_BASE_SHA,
            h003_branch_sha=h004_stack.H003_SHA,
            h002_branch_sha=h003_stack.H002_SHA,
            p020_branch_sha=h003_stack.P020_SHA,
            main_sha=self.main,
            source_sha=self.source,
            is_ancestor=is_ancestor,
            merge_base=merge_base,
        )

    def test_exact_h005_pr_stacked_on_open_r05a_head_is_accepted(self) -> None:
        self.assertEqual(self.validate(), {"branch": "main", "sha": self.main})

    def test_h005_must_target_exact_r05a_pr_head(self) -> None:
        current = {**self.current, "base": {"ref": stack.R05A_BRANCH, "sha": "c" * 40}}
        with self.assertRaisesRegex(stack.H005StackValidationError, "exact reviewed R05A"):
            self.validate(current=current)

    def test_h005_head_must_match_branch_and_checked_out_source(self) -> None:
        current = {**self.current, "head": {"ref": "other", "sha": self.source}}
        with self.assertRaisesRegex(stack.H005StackValidationError, "exact H005 branch"):
            self.validate(current=current)

    def test_r05a_predecessor_must_remain_open_and_exact(self) -> None:
        with self.assertRaisesRegex(stack.H005StackValidationError, "predecessor PR #23"):
            self.validate(r05a={**self.r05a, "state": "closed"})

    def test_h005_source_must_preserve_exact_r05a_ancestry(self) -> None:
        def missing_h005_edge(ancestor: str, commit: str) -> bool:
            if ancestor == stack.H005_BASE_SHA and commit == self.source:
                return False
            return (ancestor in self.ancestry and commit in self.ancestry and
                    self.ancestry.index(ancestor) < self.ancestry.index(commit))

        with self.assertRaisesRegex(stack.H005StackValidationError, "not descended"):
            self.validate(ancestor_override=missing_h005_edge)


if __name__ == "__main__":
    unittest.main(verbosity=2)
