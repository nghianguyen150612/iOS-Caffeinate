"""Strict PR ancestry checks for R05A stacked on the open H004 PR #22."""

from __future__ import annotations

from typing import Any, Callable

from h004_stack import (
    H004_BRANCH,
    H004StackValidationError,
    H003_SHA,
    validate_h004_stack,
)


R05A_BRANCH = "fix/r05a-apple-signature-integrity"
R05A_BASE_SHA = "b2fdea8764ba08a8f60fe4d5acae2705dce7bd37"


class R05AStackValidationError(ValueError):
    """The R05A PR does not preserve the exact open H004 ancestry."""


def validate_r05a_stack(
    *,
    current_pr: dict[str, Any],
    h004_pr: dict[str, Any],
    h003_pr: dict[str, Any],
    h002_pr: dict[str, Any],
    p020_pr: dict[str, Any],
    h004_branch_sha: str,
    h003_branch_sha: str,
    h002_branch_sha: str,
    p020_branch_sha: str,
    main_sha: str,
    source_sha: str,
    is_ancestor: Callable[[str, str], bool],
    merge_base: Callable[[str, str], str],
) -> dict[str, str]:
    if current_pr.get("state") != "open" or current_pr.get("merged_at"):
        raise R05AStackValidationError("R05A PR must remain open and unmerged")
    head = current_pr.get("head", {})
    base = current_pr.get("base", {})
    if head.get("ref") != R05A_BRANCH or head.get("sha") != source_sha:
        raise R05AStackValidationError("current PR is not the exact R05A branch and source SHA")
    if base.get("ref") != H004_BRANCH or base.get("sha") != R05A_BASE_SHA:
        raise R05AStackValidationError("R05A must target H004 PR #22 at the exact b2fdea8 head")
    if h004_branch_sha != R05A_BASE_SHA:
        raise R05AStackValidationError("remote H004 branch tip differs from the pinned PR #22 head")
    try:
        integration = validate_h004_stack(
            current_pr=h004_pr,
            h003_pr=h003_pr,
            h002_pr=h002_pr,
            p020_pr=p020_pr,
            h003_branch_sha=h003_branch_sha,
            h002_branch_sha=h002_branch_sha,
            p020_branch_sha=p020_branch_sha,
            main_sha=main_sha,
            source_sha=R05A_BASE_SHA,
            is_ancestor=is_ancestor,
            merge_base=merge_base,
        )
    except H004StackValidationError as error:
        raise R05AStackValidationError(f"H004 predecessor PR #22 is invalid: {error}") from error
    if not is_ancestor(R05A_BASE_SHA, source_sha):
        raise R05AStackValidationError("R05A source is not descended from the exact H004 head")
    if merge_base(source_sha, R05A_BASE_SHA) != R05A_BASE_SHA:
        raise R05AStackValidationError("R05A/H004 merge-base differs from the exact PR #22 head")
    return integration
