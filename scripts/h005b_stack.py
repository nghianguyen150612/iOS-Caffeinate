"""Strict ancestry checks for H005B stacked on the reviewed H005 head."""

from __future__ import annotations

from typing import Any, Callable

from h005_stack import (
    H005_BASE_SHA,
    H005_BRANCH,
    H005StackValidationError,
    validate_h005_stack,
)


H005B_BRANCH = "fix/h005b-supervised-assertion-diagnostics"
H005B_BASE_SHA = "cf82f8b03acabc0e362f05119137c2381b93d1a9"


class H005BStackValidationError(ValueError):
    """The H005B PR does not preserve the exact reviewed H005/R05A ancestry."""


def validate_h005b_stack(
    *,
    current_pr: dict[str, Any],
    h005_pr: dict[str, Any],
    r05a_pr: dict[str, Any],
    h004_pr: dict[str, Any],
    h003_pr: dict[str, Any],
    h002_pr: dict[str, Any],
    p020_pr: dict[str, Any],
    h005_branch_sha: str,
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
        raise H005BStackValidationError("H005B PR must remain open and unmerged")
    head = current_pr.get("head", {})
    base = current_pr.get("base", {})
    if head.get("ref") != H005B_BRANCH or head.get("sha") != source_sha:
        raise H005BStackValidationError("current PR is not the exact H005B branch and source SHA")
    if base.get("ref") != H005_BRANCH or base.get("sha") != H005B_BASE_SHA:
        raise H005BStackValidationError("H005B must target the exact H005 PR #24 head")
    if h005_branch_sha != H005B_BASE_SHA:
        raise H005BStackValidationError("remote H005 branch tip differs from the pinned PR #24 head")

    try:
        integration = validate_h005_stack(
            current_pr=h005_pr,
            r05a_pr=r05a_pr,
            h004_pr=h004_pr,
            h003_pr=h003_pr,
            h002_pr=h002_pr,
            p020_pr=p020_pr,
            r05a_branch_sha=r05a_branch_sha,
            h004_branch_sha=h004_branch_sha,
            h003_branch_sha=h003_branch_sha,
            h002_branch_sha=h002_branch_sha,
            p020_branch_sha=p020_branch_sha,
            main_sha=main_sha,
            source_sha=H005B_BASE_SHA,
            is_ancestor=is_ancestor,
            merge_base=merge_base,
        )
    except H005StackValidationError as error:
        raise H005BStackValidationError(f"H005 predecessor PR #24 is invalid: {error}") from error

    if not is_ancestor(H005B_BASE_SHA, source_sha):
        raise H005BStackValidationError("H005B source is not descended from the exact PR #24 head")
    if merge_base(source_sha, H005B_BASE_SHA) != H005B_BASE_SHA:
        raise H005BStackValidationError("H005B/H005 merge-base differs from the exact PR #24 head")
    if not is_ancestor(H005_BASE_SHA, source_sha):
        raise H005BStackValidationError("H005B source does not preserve the reviewed R05A base")
    return integration
