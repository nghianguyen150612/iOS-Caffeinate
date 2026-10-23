"""Strict ancestry checks for an H004 PR stacked on the exact H003 head."""

from __future__ import annotations

from typing import Any, Callable

from h003_stack import (
    H002_BRANCH,
    H002_SHA,
    H003_BRANCH,
    P020_BRANCH,
    P020_SHA,
    StackValidationError,
    validate_h003_stack,
)


H003_SHA = "fb39559766144ab0cf4327273ff3188c58200b6b"
H004_BRANCH = "docs/h004-device-phase0-readiness"


class H004StackValidationError(ValueError):
    """The H004 branch does not preserve the verified H003 stack."""


def validate_h004_stack(
    *,
    current_pr: dict[str, Any],
    h003_pr: dict[str, Any],
    h002_pr: dict[str, Any],
    p020_pr: dict[str, Any],
    h003_branch_sha: str,
    h002_branch_sha: str,
    p020_branch_sha: str,
    main_sha: str,
    source_sha: str,
    is_ancestor: Callable[[str, str], bool],
    merge_base: Callable[[str, str], str],
) -> dict[str, str]:
    if current_pr.get("state") != "open" or current_pr.get("merged_at"):
        raise H004StackValidationError("H004 PR must remain open and unmerged")
    current_head = current_pr.get("head", {})
    current_base = current_pr.get("base", {})
    if current_head.get("ref") != H004_BRANCH or current_head.get("sha") != source_sha:
        raise H004StackValidationError("current PR is not the exact H004 source branch and head")
    if current_base.get("ref") != H003_BRANCH or current_base.get("sha") != H003_SHA:
        raise H004StackValidationError("H004 must target the exact H003 branch head")
    if h003_branch_sha != H003_SHA:
        raise H004StackValidationError("remote H003 branch tip differs from the pinned H003 SHA")

    try:
        integration_base = validate_h003_stack(
            current_pr=h003_pr,
            h002_pr=h002_pr,
            p020_pr=p020_pr,
            h002_branch_sha=h002_branch_sha,
            p020_branch_sha=p020_branch_sha,
            main_sha=main_sha,
            source_sha=H003_SHA,
            is_ancestor=is_ancestor,
            merge_base=merge_base,
        )
    except StackValidationError as exc:
        raise H004StackValidationError(f"H003 predecessor stack is invalid: {exc}") from exc

    if not is_ancestor(H003_SHA, source_sha):
        raise H004StackValidationError("H004 source is not descended from the exact H003 head")
    if merge_base(source_sha, H003_SHA) != H003_SHA:
        raise H004StackValidationError("H004/H003 merge-base differs from the pinned H003 head")
    return integration_base
