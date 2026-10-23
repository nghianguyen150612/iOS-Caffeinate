# P020 Release Gates

## Decision values

The offline evaluator returns one of:

- `RELEASE_BLOCKED`: a required cloud or hardware gate is missing, invalid, failed, or the verified source chain is wrong.
- `REVIEW_REQUIRED`: required evidence gates pass but one or more release authorization reviews remain pending.
- `READY_FOR_RELEASE_AUTHORIZATION`: applicable cloud and hardware gates and human review gates pass. Publication remains a separate action.

A failed or blocked release authorization review, including an open Critical/High finding, yields `RELEASE_BLOCKED`; a missing/unverified authorization record yields `REVIEW_REQUIRED` only after required evidence gates pass.

It always reports `publication_authorized=false`. It has no API or command that creates a tag, GitHub Release, stable package, or public asset.

## Status values

Every cloud gate reports `PASS`, `PENDING`, `BLOCKED`, `FAILED`, `NOT_APPLICABLE`, or `UNVERIFIED`. Hardware gates have no manifest status field: the evaluator derives their state from exact evidence types, content, hashes, signatures, and review receipts. Out-of-scope features belong only in the separate `scope` field. `NOT_APPLICABLE` cannot waive a required gate.

## Required cloud gates

Source integration; native build; iOS cross-build; Mach-O inspection; rootful packaging; signing metadata; security analysis; regression CI; evidence-schema compatibility; and build provenance. Build provenance is checked against the exact Git tree and commit timestamp, approved entitlement profile, unsigned candidate identity, and the measured hashes of both binaries and packages. Other cloud `PASS` entries require exact-source CI evidence whose SHA-256 and gate result match the manifest source SHA.

## Required hardware gates

1. P010 exact signer provenance.
2. P011 stable package acceptance.
3. Exact installed v0.2 candidate identity.
4. P012 physical 24-trial observations and analysis.
5. P013 lifecycle acceptance.
6. P014 physical recovery and cleanup acceptance.
7. P016 resource availability review.
8. P018 privacy review of the sanitized derivative.
9. P019 session and accepted result: 24 valid P012 trials plus 12 attended 180-second acquire/release cycles across three distinct dates, clean releases and no unexpected exits/restarts.
10. Independent review of unchanged P009 raw evidence.

Evidence records are typed and SHA-256-bound. Synthetic, mock, or CI records cannot satisfy hardware gates. Review receipts must bind evidence hashes and carry a detached GPG signature. `scripts/p020_release_gate.py` verifies those signatures only against an absolute keyring supplied with `--trusted-review-keyring`; the keyring must be provisioned through a separate trusted reviewer-management process and kept outside the evidence bundle. Without it, review stays `UNVERIFIED`. Evidence files are opened with no-follow checks and bounded by file count, file size, and aggregate size. Bundle code is never executed.

The P010 provenance record must bind the pinned Procursus source URL/commit, exact signer executable hash/version, approved profile, source and final CLI/daemon hashes, package hash, signing command/result, and signed-binary inspection. The installed candidate record and P019 session must match the same source, package, profile, signer, build ID, and final binary hashes. A mismatch fails all affected hardware gates.

The tool checks evidence structure and consistency. Human reviewers still inspect device provenance and original P009 material; a hash proves file consistency, not that an event occurred. P009 raw files remain private and unchanged. P018 export remains a separately identifiable derivative.

## Authorization gates

A signed, independently reviewed security closeout must enumerate findings and show zero unresolved release-blocking issues. Separate signed review records are required for operator acceptance, limitations, rollback, and final human release approval. The evaluator does not accept user-entered `PASS` booleans. Even a fully passing assessment is not publication authorization.

## Current decision

The current evidence inventory contains no accepted physical P019 trial. H003 has verified the pinned signer, but R05's exact-source package failed Apple host signature-integrity verification for both ARM64 binaries, so no finalized signed RC is available for candidate-bound P010 evidence admission or device acceptance. Independent review, P011, and the remaining physical gates are also pending. The outcome remains `RELEASE_BLOCKED` and publication false. The exact blockers are emitted by the evaluator and retained with the CI report; no readiness status is hardcoded into the decision logic.

```sh
python3 scripts/p020_release_gate.py assess \
  --manifest /absolute/path/to/release-manifest.json \
  --expected-source-sha <exact-source-sha> \
  --trusted-review-keyring /absolute/path/to/organization-reviewers.gpg

python3 scripts/p020_release_gate.py report \
  --manifest /absolute/path/to/release-manifest.json \
  --expected-source-sha <exact-source-sha> \
  --trusted-review-keyring /absolute/path/to/organization-reviewers.gpg
```

Both commands are offline and read-only. Omit the keyring only when assessing cloud state or intentionally producing an `UNVERIFIED` review result.
