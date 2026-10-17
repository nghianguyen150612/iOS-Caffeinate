# P008 — Integration and Git Review

## Source baseline

P008 starts from the verified P007 merge `c8512508a80be5fc09d0c62b2e26877717af23df`, which is also the current head of `feat/p004-timed-scheduling-381823536033500942`. Its exact merge base with that branch is the same SHA. The branch is based on the integrated P004–P007 tree, not on `main` or the legacy P003 branch.

The ref graph at preflight was:

```text
main 069ad94
└─ P001 baseline 1fa03ac
   ├─ historical P002 branch: 434f85a → 8534e88 → 82ac9af
   ├─ historical P003 branch / open PR #1: 5314df1 → d8d13fd → 0de48a6
   └─ P004 aggregate / open PR #2:
      four iterative P004 schedule commits → P005 merge 77f3f15
      → P006 merge dfe32d2 → P007 merge c851250
```

The repeated P004 commit subjects reflect iterative revisions to overlapping source files. The final tree contains one schedule implementation. P005, P006, and P007 are merge commits in the P004 aggregate ancestry; no milestone snapshots are cherry-picked again in P008.

## Integration tree audit

The aggregate PR #2 diff against `main` contains the P002 runtime diagnostics and canonical names; P003 daemon states, peer credential rejection, locking, lifecycle cleanup and tests; P004 schedule/STOP/restart behavior; P005 read-only wake feasibility; P006 disabled server policy and bounded trials; and P007 rootful packaging. The integrated tree includes the P003 fail-closed peer-authentication regression. Its package workflow inspects the current build outputs rather than checking in generated executable or `.deb` files. The only checked-in P002 inspection evidence is text.

The aggregate diff has no second CLI or daemon executable, no GUI, no active LaunchDaemon payload, and no seeded schedule/server configuration. The staged plist stays disabled. Existing P001–P007 docs and device procedures remain available and are linked from the P008 acceptance plan.

P008's focused diff is limited to the scheduler state/persistence hardening, targeted Linux regression coverage, CI artifact evidence generation, and P008 documentation. Its initial PR targets `feat/p004-timed-scheduling-381823536033500942`; this updates the head of PR #2 through the existing stacked-PR relationship. It must not be merged directly into `main`.

## Existing pull requests

PR #2 is the aggregate integration PR targeting `main`. Recommendation: accept the P008 stacked PR first, rerun or confirm all required checks on the updated aggregate head, review the exact diff from `main`, then merge PR #2 through the normal review process. Do not merge it automatically as part of P008.

PR #1 is the legacy P003 PR targeting `main`. Its daemon/security changes overlap functionality already present and tested in the P008 integration tree. No required P003 behavior was found only in PR #1. Recommendation: after P008 is accepted into the aggregate branch and PR #2 is confirmed to retain the fail-closed peer-authentication tests, close PR #1 as superseded. Do not cherry-pick the P003 snapshot onto the aggregate tree.

No shared history is rewritten, no branch is force-pushed, and P008 does not close either existing PR or merge into `main`.
