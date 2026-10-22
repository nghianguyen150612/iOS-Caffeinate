"""Strict ancestry checks for the H003 branch stacked on the exact H002 head."""

from __future__ import annotations

from typing import Any, Callable


H002_BRANCH = "fix/h002-p011-legacy-checksum"
H002_SHA = "341c6840fc9d6c64876fb3a0106fd318c4dfc7c0"
P020_BRANCH = "release/p020-v02-integration"
P020_SHA = "57b06c534d18f094ad59e4229e626fae51668de9"
H003_BRANCH = "fix/h003-p011-signer-preflight"


class StackValidationError(ValueError):
    """The H003 stack does not match the verified H002/P020 ancestry."""


def validate_h003_stack(
    *,
    current_pr: dict[str, Any],
    h002_pr: dict[str, Any],
    p020_pr: dict[str, Any],
    h002_branch_sha: str,
    p020_branch_sha: str,
    main_sha: str,
    source_sha: str,
    is_ancestor: Callable[[str, str], bool],
    merge_base: Callable[[str, str], str],
) -> dict[str, str]:
    if current_pr.get("state") != "open" or current_pr.get("merged_at"):
        raise StackValidationError("H003 PR must remain open and unmerged")
    current_head = current_pr.get("head", {})
    current_base = current_pr.get("base", {})
    if current_head.get("ref") != H003_BRANCH or current_head.get("sha") != source_sha:
        raise StackValidationError("current PR is not the exact H003 source branch and head")
    if current_base.get("ref") != H002_BRANCH or current_base.get("sha") != H002_SHA:
        raise StackValidationError("H003 must target the pinned H002 branch head")

    if h002_pr.get("state") != "open" or h002_pr.get("merged_at"):
        raise StackValidationError("H002 predecessor PR must remain open and unmerged")
    h002_head = h002_pr.get("head", {})
    h002_base = h002_pr.get("base", {})
    if h002_head.get("ref") != H002_BRANCH or h002_head.get("sha") != H002_SHA:
        raise StackValidationError("H002 predecessor head differs from its pinned SHA")
    if h002_base.get("ref") != P020_BRANCH or h002_base.get("sha") != P020_SHA:
        raise StackValidationError("H002 predecessor does not target the pinned P020 source head")

    if p020_pr.get("state") != "open" or p020_pr.get("merged_at"):
        raise StackValidationError("P020 predecessor PR must remain open and unmerged")
    p020_head = p020_pr.get("head", {})
    p020_base = p020_pr.get("base", {})
    if p020_head.get("ref") != P020_BRANCH or p020_head.get("sha") != P020_SHA:
        raise StackValidationError("P020 predecessor head differs from its pinned SHA")
    if p020_base.get("ref") != "main" or p020_base.get("sha") != main_sha:
        raise StackValidationError("P020 predecessor no longer targets the current main head")
    if h002_branch_sha != H002_SHA or p020_branch_sha != P020_SHA:
        raise StackValidationError("remote H002 or P020 branch tip differs from its pinned SHA")

    if not is_ancestor(P020_SHA, H002_SHA) or not is_ancestor(H002_SHA, source_sha):
        raise StackValidationError("H003 source does not preserve the P020-to-H002 ancestry chain")
    if merge_base(source_sha, H002_SHA) != H002_SHA:
        raise StackValidationError("H003/H002 merge-base is not the exact pinned H002 commit")
    if merge_base(source_sha, P020_SHA) != P020_SHA:
        raise StackValidationError("H003/P020 merge-base is not the exact pinned P020 commit")
    return {"branch": "main", "sha": main_sha}
