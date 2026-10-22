# P019 Prerequisites and Dependency Matrix

The matrix records what cloud work can establish and what remains a hardware or human-review gate. `PASS` in CI is never a P009 hardware PASS.

| Dependency | Cloud state | Physical or review gate | Downstream effect |
|---|---|---|---|
| P009 evidence v1 | Validator, replay, schemas, and synthetic cases are available and regression-tested. | Genuine per-session observations, raw package hashes, provenance checks, and independent review. | Authority for all hardware acceptance decisions. |
| P010 signing/package verification | H003 rebuilt the exact host-compatible `ldid` twice from the pinned Procursus source and verified its version and SHA-256 against P010. | Physical package acceptance, signature-integrity assessment, target execution, and P009 review remain separate. | Exact host signer availability no longer blocks P011; physical P011 acceptance remains a prerequisite to power-trial acceptance. |
| P011 stable package | Release identity and pinned digest are documented. | Supervised acceptance of `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb`, SHA-256 `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c`, including installed paths, runtime, removal/rollback scope, and P009 review. | Required before P012 or P019 power trials. |
| Development candidate | Cloud source and build workflows can identify the exact source. No candidate is built, signed, or installed by P019. | Signed, hash-verified candidate containing the tested P018/P019 source; exact package, CLI, daemon, profile, signer, entitlement, and installed-path identity; known accepted rollback artifact. | Required to attribute P018/P019-only behavior to tested source. |
| P012 research | Protocol v1 and the existing one-shot probe, controller, analyzer, and tests are reused. | Fixed 24-trial A/B/C/D matrix with 3 repetitions per condition and route, quiet interval and timebase rules, actual acquire/release, screen-lock observation, and route-specific results. | Missing or confounded trials remain incomplete or inconclusive. |
| P013 lifecycle | Fail-closed lifecycle code and disabled package template are tested in CI. | iOS 12.5.7 launchd mutation semantics remain unverified; no activation or restart test is authorized by P019. | Foreground behavior may be assessed separately; launchd operation remains outside accepted scope. |
| P014 recovery | Bounded policy, journal validation, and fault-injection paths are tested in cloud. Automatic restart executor is not implemented. | Physical assertion ownership, clean journal, process exit, socket cleanup, and recovery state must be independently observed. | Any unknown or corrupt cleanup state blocks further trials. |
| P015 Server Mode | Policy denies unattended execution unless separately authorized by future work. | No P019 operation may convert a policy preview into execution permission. | Unattended server mode remains denied. |
| P016 telemetry | Read-only schema and adapters are tested. | Uptime adapter runtime is unverified on target. Battery/charging and thermal readings may be `UNAVAILABLE`; operator observation is separate and cannot become calibrated health data. | Defer if safe resource assessment is not available. |
| P017 schedules | Recurrence and storage behavior are tested. | Schedule executor remains unauthorized and scheduled wake is unverified. | No schedule-triggered test or assertion is run. |
| P018 evidence export | Inventory, privacy filter, and offline validator are tested with MOCK fixtures. | Preserve original raw P009 records. Review the sanitized derivative and its internal hashes separately. | A privacy rejection is recorded as `EXPORT_BLOCKED_BY_PRIVACY`; never weaken the filter. |
| P019 | Protocol, session layer, analyzer, faults, and CI are cloud-achievable. | Attended observations and independent evidence review remain unperformed. | Stage A can finish; hardware acceptance remains pending. |

## Current blockers

- H003 verified the exact P010 `ldid` executable and completed the P011 host preflight. The historical H001 pinned image and signed package-snapshot receipt were unavailable; H003 records a new pinned build environment and does not claim it reconstructs H001.
- P011 physical stable-package acceptance is pending. The public release label does not certify installation or runtime behavior.
- No P012 physical controlled comparison is accepted. Historical operator-reported SSH observations are not P012 records and do not establish causality.
- P013 target launchd semantics and P014 physical cleanup/recovery remain unverified. P014 has no production automatic restart executor.
- P016 target uptime is unverified; battery and thermal APIs may remain unavailable.
- P015 unattended mode and P017 schedule execution remain unauthorized.
- No physical P018 export or P019 evidence review exists.

The exact order and stop consequences are in the [operator runbook](P019-OPERATOR-RUNBOOK.md) and [release gates](P019-RELEASE-GATES.md).
