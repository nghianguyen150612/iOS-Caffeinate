# P020 Validation Record

## Validation layers

The dedicated `p020-release-readiness-validation` job depends on the exact-source P009–P019 workflows, Linux protocol build, iOS cross-build and inspection, rootful packaging, and two isolated unsigned P020 candidate builds. It verifies its checked-out SHA, checks PR #10–#18 head/base/merge commits/review state/exact-head CI against the recorded merged chain, confirms the P008 branch-guard attestation is `SKIPPED` rather than PASS, verifies the P019 source/base merge-base on integrated `main`, inspects artifacts, validates schemas and provenance, and checks that publication/device-side-effect commands are absent.

It then runs P020 release/provenance negative tests, a mocked package-status → recovery → policy → schedule → telemetry → evidence → release-decision integration, the Python suite, packaging suite, C11 Linux mock build, native protocol integration, shell syntax checks, and existing release-gate tests. The mocked integration records `MOCK`, marks device actions `NOT_PERFORMED`, and must end `RELEASE_BLOCKED`. CI passes only when the expected missing physical gates and signer provenance remain blockers.

## Required negative cases

- A hardware `PASS` field supplied by a user is rejected by strict schema validation.
- Synthetic P019 input cannot satisfy a physical gate.
- A reviewer receipt without an external trusted keyring remains `UNVERIFIED`.
- Missing P010 provenance and P011 acceptance remain blocked.
- A source mismatch, evidence hash mismatch, absent CI proof, or non-green dependency chain blocks the assessment.
- P015/P017 execution restrictions and no-publication guardrails remain present.
- The assessment is offline and does not modify the manifest or evidence.

## Evidence produced by CI

The run-scoped validation artifact contains source commit/tree SHAs, milestone PR chain, candidate build inputs, two binaries and packages with hashes, Mach-O/package inspection, provenance/reproducibility result, test logs, generated release manifest, and JSON/Markdown assessment. Artifacts are not public release assets. The exact-head CI run URL and artifact hashes must be recorded in the final integration PR review.

P008 release attestation is branch-guarded and skipped for this stacked feature branch. Its skip remains explicitly reported; P020 does not reinterpret it as a passed attestation.

## Cloud versus hardware

These checks can verify code paths, mock regressions, package structure, schema compatibility, and workflow provenance. They cannot verify signer authenticity, installation, iOS acceptance, assertion lifecycle on the iPad, physical recovery, launchd behavior, sensor availability, continuous awake state, or endurance. P020 cloud completion must remain `P020_CLOUD_COMPLETE_RELEASE_BLOCKED` until physical evidence is independently reviewed.
