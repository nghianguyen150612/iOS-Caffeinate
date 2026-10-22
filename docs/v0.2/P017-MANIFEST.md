# P017 — Submission manifest

| Field | Value |
|---|---|
| Milestone | P017 — Timed & Recurring Schedule Improvements |
| Branch | `ios/p017-scheduling-v2` |
| Starting source | `1b0e258b136f6325c4720bf55c569449935418c3` (P016 exact head) |
| PR base while P016 is open | `ios/p016-health-telemetry` |
| P016 exact-head CI | Run `39520608897`, success at the time of preflight |
| Validation class | Simulated and mock only |
| Device access | Not performed |
| Hardware acceptance | Pending |
| Scheduled wake | Unverified |
| P015 scheduled execution | Not authorized |
| Release/tag | No v0.2.0 tag or release created |

The final source SHA, merge-base, PR URL, PR base, local test counts and exact-head CI URL are recorded in the submission report after push. CI artifacts describe source validation only and are not P009 hardware evidence. The P017 completion label is `P017_CLOUD_COMPLETE_DEVICE_SCHEDULING_PENDING` after exact-head CI passes.

P018 is expected to improve CLI help/errors, use P017 schedule diagnostics alongside safe service and recovery reporting, and add package-manager guidance/evidence export. It must retain explicit read-only defaults and must not enable unattended scheduling.
