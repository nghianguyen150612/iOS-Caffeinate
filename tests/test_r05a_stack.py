from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import h003_stack  # noqa: E402
import h004_stack  # noqa: E402
import r05a_stack as stack  # noqa: E402


class R05AStackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = "a" * 40
        self.main = "b" * 40
        self.current = {
            "state": "open", "head": {"ref": stack.R05A_BRANCH, "sha": self.source},
            "base": {"ref": h004_stack.H004_BRANCH, "sha": stack.R05A_BASE_SHA},
        }
        self.h004 = {
            "state": "open", "head": {"ref": h004_stack.H004_BRANCH, "sha": stack.R05A_BASE_SHA},
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
        self.ancestry = [self.main, h003_stack.P020_SHA, h003_stack.H002_SHA,
                         h004_stack.H003_SHA, stack.R05A_BASE_SHA, self.source]

    def validate(self, *, current=None, h004=None, ancestor_override=None):
        def is_ancestor(ancestor: str, commit: str) -> bool:
            if ancestor_override is not None:
                return ancestor_override(ancestor, commit)
            return ancestor in self.ancestry and commit in self.ancestry and self.ancestry.index(ancestor) < self.ancestry.index(commit)

        def merge_base(left: str, right: str) -> str:
            common = [item for item in self.ancestry if is_ancestor(item, left) or item == left]
            common = [item for item in common if is_ancestor(item, right) or item == right]
            return common[-1] if common else ""

        return stack.validate_r05a_stack(
            current_pr=current or self.current, h004_pr=h004 or self.h004,
            h003_pr=self.h003, h002_pr=self.h002, p020_pr=self.p020,
            h004_branch_sha=stack.R05A_BASE_SHA, h003_branch_sha=h004_stack.H003_SHA,
            h002_branch_sha=h003_stack.H002_SHA, p020_branch_sha=h003_stack.P020_SHA,
            main_sha=self.main, source_sha=self.source,
            is_ancestor=is_ancestor, merge_base=merge_base,
        )

    def test_exact_open_r05a_pr_over_open_h004_pr_is_accepted(self) -> None:
        self.assertEqual(self.validate(), {"branch": "main", "sha": self.main})

    def test_r05a_must_target_the_exact_pinned_h004_head(self) -> None:
        current = {**self.current, "base": {"ref": h004_stack.H004_BRANCH, "sha": "c" * 40}}
        with self.assertRaisesRegex(stack.R05AStackValidationError, "exact b2fdea8"):
            self.validate(current=current)

    def test_h004_predecessor_must_remain_open(self) -> None:
        with self.assertRaisesRegex(stack.R05AStackValidationError, "predecessor PR #22"):
            self.validate(h004={**self.h004, "state": "closed"})

    def test_r05a_source_must_preserve_exact_h004_ancestry(self) -> None:
        def missing_r05a_ancestry(ancestor: str, commit: str) -> bool:
            return not (ancestor == stack.R05A_BASE_SHA and commit == self.source) and \
                ancestor in self.ancestry and commit in self.ancestry and \
                self.ancestry.index(ancestor) < self.ancestry.index(commit)

        with self.assertRaisesRegex(stack.R05AStackValidationError, "not descended"):
            self.validate(ancestor_override=missing_r05a_ancestry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
