from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import h003_stack  # noqa: E402
import h004_stack  # noqa: E402
import h005_stack  # noqa: E402
import h005b_stack as stack  # noqa: E402
import r05a_stack  # noqa: E402


class H005BStackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = "a" * 40
        self.main = "b" * 40
        self.current = {
            "state": "open", "merged_at": None,
            "head": {"ref": stack.H005B_BRANCH, "sha": self.source},
            "base": {"ref": h005_stack.H005_BRANCH, "sha": stack.H005B_BASE_SHA},
        }
        self.h005 = {
            "state": "open", "merged_at": None,
            "head": {"ref": h005_stack.H005_BRANCH, "sha": stack.H005B_BASE_SHA},
            "base": {"ref": r05a_stack.R05A_BRANCH, "sha": h005_stack.H005_BASE_SHA},
        }
        self.r05a = {
            "state": "open", "merged_at": None,
            "head": {"ref": r05a_stack.R05A_BRANCH, "sha": h005_stack.H005_BASE_SHA},
            "base": {"ref": h004_stack.H004_BRANCH, "sha": r05a_stack.R05A_BASE_SHA},
        }
        self.h004 = {
            "state": "open", "merged_at": None,
            "head": {"ref": h004_stack.H004_BRANCH, "sha": r05a_stack.R05A_BASE_SHA},
            "base": {"ref": h003_stack.H003_BRANCH, "sha": h004_stack.H003_SHA},
        }
        self.h003 = {
            "state": "open", "head": {"ref": h003_stack.H003_BRANCH, "sha": h004_stack.H003_SHA},
            "base": {"ref": h003_stack.H002_BRANCH, "sha": h003_stack.H002_SHA},
        }
        self.h002 = {
            "state": "open", "head": {"ref": h003_stack.H002_BRANCH, "sha": h003_stack.H002_SHA},
            "base": {"ref": h003_stack.P020_BRANCH, "sha": h003_stack.P020_SHA},
        }
        self.p020 = {
            "state": "open", "head": {"ref": h003_stack.P020_BRANCH, "sha": h003_stack.P020_SHA},
            "base": {"ref": "main", "sha": self.main},
        }
        self.chain = [
            self.main, h003_stack.P020_SHA, h003_stack.H002_SHA,
            h004_stack.H003_SHA, r05a_stack.R05A_BASE_SHA,
            h005_stack.H005_BASE_SHA, stack.H005B_BASE_SHA, self.source,
        ]

    def validate(self, *, current=None, h005=None, h005_branch_sha=None, ancestor_override=None):
        def is_ancestor(ancestor: str, commit: str) -> bool:
            if ancestor_override is not None:
                return ancestor_override(ancestor, commit)
            return (ancestor in self.chain and commit in self.chain and
                    self.chain.index(ancestor) < self.chain.index(commit))

        def merge_base(left: str, right: str) -> str:
            common = [item for item in self.chain if is_ancestor(item, left) or item == left]
            common = [item for item in common if is_ancestor(item, right) or item == right]
            return common[-1] if common else ""

        return stack.validate_h005b_stack(
            current_pr=current or self.current,
            h005_pr=h005 or self.h005,
            r05a_pr=self.r05a, h004_pr=self.h004, h003_pr=self.h003,
            h002_pr=self.h002, p020_pr=self.p020,
            h005_branch_sha=h005_branch_sha or stack.H005B_BASE_SHA,
            r05a_branch_sha=h005_stack.H005_BASE_SHA,
            h004_branch_sha=r05a_stack.R05A_BASE_SHA,
            h003_branch_sha=h004_stack.H003_SHA,
            h002_branch_sha=h003_stack.H002_SHA,
            p020_branch_sha=h003_stack.P020_SHA,
            main_sha=self.main, source_sha=self.source,
            is_ancestor=is_ancestor, merge_base=merge_base,
        )

    def test_exact_h005b_pr_is_stacked_on_reviewed_h005_head(self) -> None:
        self.assertEqual(self.validate(), {"branch": "main", "sha": self.main})

    def test_wrong_base_head_is_rejected(self) -> None:
        current = {**self.current, "base": {"ref": h005_stack.H005_BRANCH, "sha": "c" * 40}}
        with self.assertRaisesRegex(stack.H005BStackValidationError, "exact H005 PR #24"):
            self.validate(current=current)

    def test_moved_h005_branch_is_rejected(self) -> None:
        with self.assertRaisesRegex(stack.H005BStackValidationError, "remote H005 branch tip"):
            self.validate(h005_branch_sha="c" * 40)

    def test_h005b_source_must_descend_from_the_exact_h005_head(self) -> None:
        def missing_h005b_edge(ancestor: str, commit: str) -> bool:
            if ancestor == stack.H005B_BASE_SHA and commit == self.source:
                return False
            return (ancestor in self.chain and commit in self.chain and
                    self.chain.index(ancestor) < self.chain.index(commit))

        with self.assertRaisesRegex(stack.H005BStackValidationError, "not descended"):
            self.validate(ancestor_override=missing_h005b_edge)


if __name__ == "__main__":
    unittest.main(verbosity=2)
