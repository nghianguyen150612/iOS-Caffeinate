# P020 Integration Manifest

## Git baseline and integrated base

- Repository: `nghianguyen150612/iOS-Caffeinate`
- P020 branch: `release/p020-v02-integration`
- P020 starts from the exact P019 source commit: `7d5723fca2595b8928ed3e1717ca872906d48538`.
- During P020 work, GitHub merged P011–P019 to `main`. The integrated base is now `main` at `7dbd47e4500c0ddf3d65d282d8e6a8881d6c8703`.
- The Git DAG confirms the P019 source head is an ancestor of `origin/main`; a P020 branch based on that same P019 commit has merge-base `7d5723fca2595b8928ed3e1717ca872906d48538` with integrated `main`.
- P020 targets `main`; this preserves only P020 changes in the PR diff and does not rewrite earlier milestone commits.
- P020 final source/tree SHA, PR, and exact-head CI are recorded after integration commit in the PR and run artifact.

## P011–P019 merged chain

| Milestone | PR | Head SHA | Base SHA at merge | Merge commit SHA | Current state | Exact-head CI |
|---|---:|---|---|---|---|---|
| P011 | 10 | `1fed3d15f44099d4f862ac1ff422da287b78b0b3` | `0cfdc645dc1d67ddc4320a00bb114763b9669b66` | `16f3ea06e2c100bc1caa208f5d539bb9620222c0` | Merged to `main` | Green; P008 guard skipped |
| P012 | 11 | `f459e332deefb134b6725c1455c5721830d0bb3a` | `16f3ea06e2c100bc1caa208f5d539bb9620222c0` | `50f96891b8369583c7b86576bd198854283edc0c` | Merged to `main` | Green; P008 guard skipped |
| P013 | 12 | `3d7b5d4c700194ab71713c51577e7a7cf0acd48c` | `50f96891b8369583c7b86576bd198854283edc0c` | `077b62bcf167a7b54ddf6f56c8bd3895c4f2da19` | Merged to `main` | Green; P008 guard skipped |
| P014 | 13 | `5dbf08176f3219c082e5b8f48bac43461b3fdd96` | `077b62bcf167a7b54ddf6f56c8bd3895c4f2da19` | `4abecae5ce4baf69de159b648fb07a9e0ff8a446` | Merged to `main` | Green; P008 guard skipped |
| P015 | 14 | `ef46cdc467128bf658c81dc891915aa91a2ddbca` | `4abecae5ce4baf69de159b648fb07a9e0ff8a446` | `938c7c87f84090ecebbe2e2bbb9e8116f263e5be` | Merged to `main` | Green; P008 guard skipped |
| P016 | 15 | `1b0e258b136f6325c4720bf55c569449935418c3` | `938c7c87f84090ecebbe2e2bbb9e8116f263e5be` | `12228ac832f77243e4d87c5a0178208cf3f3eef6` | Merged to `main` | Green; P008 guard skipped |
| P017 | 16 | `15861c0f9b765731c7dee506fd147ca7e53cbf7e` | `12228ac832f77243e4d87c5a0178208cf3f3eef6` | `84277473bbbad2c2d2df977f559840f13db6c25b` | Merged to `main` | Green; P008 guard skipped |
| P018 | 17 | `e9d94c9abdfb63ccabd96e11ea2f667c33918e90` | `84277473bbbad2c2d2df977f559840f13db6c25b` | `9083f9265ddcb0cc9f6c75edce0e0c473d74897b` | Merged to `main` | Green; P008 guard skipped |
| P019 | 18 | `7d5723fca2595b8928ed3e1717ca872906d48538` | `9083f9265ddcb0cc9f6c75edce0e0c473d74897b` | `7dbd47e4500c0ddf3d65d282d8e6a8881d6c8703` | Merged to `main` | Green; P008 guard skipped |

PR mergeability is `UNKNOWN` after merge because GitHub no longer computes an open-PR merge state. GitHub reports no review decision or latest review record for these merged PRs. Each listed merge commit is on the `main` first-parent history. P020 CI rechecks PR API metadata, exact source heads/base/merge SHAs, review state, exact-head check conclusions, and Git ancestry. P019's exact-head successful CI run is `39696560499`. A P008 skip is explicitly not counted as a pass.

## Release state

- Stable release remains `v0.1.0` / package `0.1.0-1`.
- P020 CI candidate version is `0.2.0~rc1-1`, unsigned and device-unverified; the separate R05 workflow prepares a signed, device-unverified run-scoped artifact.
- H003 has verified the pinned signer; candidate-bound P010 evidence and independent review remain pending.
- P019 physical acceptance has no accepted trial evidence.
- No v0.2 stable tag, release, or public artifact is created.
- Current release decision: `RELEASE_BLOCKED` until physical gates, trusted reviewer verification, and separate human authorization close.
