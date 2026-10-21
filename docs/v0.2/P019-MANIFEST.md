# P019 Manifest

**Milestone:** P019 — Supervised Reliability & Endurance Validation
**Branch:** `ios/p019-supervised-reliability`
**Starting source:** `e9d94c9abdfb63ccabd96e11ea2f667c33918e90` (P018 exact head)
**Stacked base:** `ios/p018-cli-package-ux` at `e9d94c9abdfb63ccabd96e11ea2f667c33918e90`
**P018 base:** `ios/p017-scheduling-v2` at `15861c0f9b765731c7dee506fd147ca7e53cbf7e`
**P018 PR:** #17, open and unmerged at preflight.
**Hardware status:** `P019_CLOUD_COMPLETE_HARDWARE_ACCEPTANCE_PENDING` only after exact-head cloud gates pass.

## Dependency matrix

| Milestone | Cloud evidence | Physical acceptance state | P019 use |
|---|---|---|---|
| P009 | v1 schema, offline validator/replay/report, fixture suites | Raw, provenance-reviewed reference packages remain required | Acceptance authority; schema unchanged |
| P010 | Signing profile/package validation rules | Exact ldid executable provenance is not available in this task | Hard blocker to P011 |
| P011 | v0.1.0 release/package identity and preflight tests | Stable package install/runtime/rollback pending | Must pass before power trials |
| P012 | Fixed protocol and existing probe/controller/analyzer | Controlled 24-trial target study not accepted | P019 reuses its matrix and comparisons |
| P013 | Disabled lifecycle template and fail-closed cloud checks | Target launchd semantics unverified; no mutation | Unsupported operation remains pending |
| P014 | Recovery policy and fault-injection suites | Live journal/cleanup unverified; no restart executor | Unknown cleanup stops testing |
| P015 | Unattended policy denies execution | No unattended authorization | Restriction is preserved |
| P016 | On-demand adapters and schema | Uptime unverified; battery/thermal may be unavailable | Missing readings stay unavailable |
| P017 | Calendar recurrence and safety validation | Schedule execution unauthorized | No schedule-run trials |
| P018 | Package UX, evidence inventory, sanitized export validator | No target export collected or reviewed | Derivative cannot replace raw P009 |
| P019 | Protocol, schemas, offline session/analyzer, tests and CI | No P019 target measurement collected or reviewed | Stage A only |
| P020 | Cloud release checks remain assessable | Hardware release gates remain blocked | No v0.2 publication |

## Artifacts

- `experiments/p019/protocol-v1.json`: preregistration, exact target, sequential phases, 24-trial P012 reference, 12-cycle supervised sample plan, safety, provenance, analysis, and acceptance rules.
- `experiments/p019/protocol-v1.schema.json`, `session-v1.schema.json`, `acceptance-result-v1.schema.json`: strict versioned contracts.
- `scripts/p019_session.py`: offline plan, host-side session template, operator-confirmation copy, validation, analysis, and report.
- `docs/v0.2/P019-*.md`: architecture, prerequisites, protocol, matrix, runbook, stops, format, analysis, evidence review, incidents, release gates, validation, and this manifest.
- `.github/workflows/ci.yml`: exact-source P019 workflow job with synthetic artifact upload.

## Current readiness

The exact P010 ldid executable has not been verified. P011 physical package acceptance, P012 controlled target measurements, P013 launchd compatibility, P014 physical recovery, P016 runtime telemetry, P018 export review, and P019 independent evidence review remain pending. P015 unattended execution and P017 schedule execution remain unauthorized. No development candidate was built or installed. No tag or release was created.
