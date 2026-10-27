"""Strict ancestry checks for H005 stacked on the exact reviewed R05A head."""

from __future__ import annotations

from typing import Any, Callable

from r05a_stack import (
    R05A_BASE_SHA,
    R05A_BRANCH,
    R05AStackValidationError,
    validate_r05a_stack,
)


H005_BRANCH = "feat/h005-physical-preflight-inspector"
H005_BASE_SHA = "6c3b04324eadaea6e34a0c81817efe7441a0f97d"


class H005StackValidationError(ValueError):
    """The H005 PR does not preserve the reviewed R05A ancestry."""


def validate_h005_stack(
    *,
    current_pr: dict[str, Any],
    r05a_pr: dict[str, Any],
    h004_pr: dict[str, Any],
    h003_pr: dict[str, Any],
    h002_pr: dict[str, Any],
    p020_pr: dict[str, Any],
    r05a_branch_sha: str,
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
        raise H005StackValidationError("H005 PR must remain open and unmerged")
    head = current_pr.get("head", {})
    base = current_pr.get("base", {})
    if head.get("ref") != H005_BRANCH or head.get("sha") != source_sha:
        raise H005StackValidationError("current PR is not the exact H005 branch and source SHA")
    if base.get("ref") != R05A_BRANCH or base.get("sha") != H005_BASE_SHA:
        raise H005StackValidationError("H005 must target the exact reviewed R05A PR #23 head")
    if r05a_branch_sha != H005_BASE_SHA:
        raise H005StackValidationError("remote R05A branch tip differs from the pinned PR #23 head")

    try:
        integration = validate_r05a_stack(
            current_pr=r05a_pr,
            h004_pr=h004_pr,
            h003_pr=h003_pr,
            h002_pr=h002_pr,
            p020_pr=p020_pr,
            h004_branch_sha=h004_branch_sha,
            h003_branch_sha=h003_branch_sha,
            h002_branch_sha=h002_branch_sha,
            p020_branch_sha=p020_branch_sha,
            main_sha=main_sha,
            source_sha=H005_BASE_SHA,
            is_ancestor=is_ancestor,
            merge_base=merge_base,
        )
    except R05AStackValidationError as error:
        raise H005StackValidationError(f"R05A predecessor PR #23 is invalid: {error}") from error

    if not is_ancestor(H005_BASE_SHA, source_sha):
        raise H005StackValidationError("H005 source is not descended from the exact PR #23 head")
    if merge_base(source_sha, H005_BASE_SHA) != H005_BASE_SHA:
        raise H005StackValidationError("H005/R05A merge-base differs from the exact PR #23 head")
    return integration
