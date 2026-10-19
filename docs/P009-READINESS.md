# P009 — Project Readiness Snapshot

This was the P009 status before the operator-reported test on October 18, 2026. P009 supplied the offline acceptance harness. Later observations and their review dispositions are recorded in [P010 hardware findings](P010-HARDWARE-FINDINGS.md) and [P010 release readiness](P010-RELEASE-READINESS.md).

| Readiness item | Current status |
|---|---|
| Evidence schema, offline validator, replay, and report | IMPLEMENTED; synthetic P009 CI remains test evidence only |
| Device identity and iOS runtime | Operator-reported; `REVIEW_REQUIRED` |
| Package integrity, signature acceptance, installation, and rollback | `INSUFFICIENT_EVIDENCE` |
| IOKit acquisition and release | Operator-reported; `REVIEW_REQUIRED` |
| Bounded hold, STOP, natural expiry, SIGTERM cleanup | Operator-reported; `REVIEW_REQUIRED` |
| Screen-locked LAN SSH | Operator-reported 24/24; `REVIEW_REQUIRED` |
| Screen-locked Tailscale SSH | Operator-reported 24/24; `REVIEW_REQUIRED` |
| No-assertion comparison | PENDING |
| Battery and thermal observations | PENDING |
| Physical recovery and launchd-disabled verification | PENDING |
| Scheduled wake | UNVERIFIED |
| Unattended 24/7 operation | NOT VALIDATED |

```text
operator_reported_observations=2026-10-18
p009_hardware_gates=REVIEW_REQUIRED_OR_INSUFFICIENT_EVIDENCE
package_acceptance=PENDING
unattended_24_7=NOT_VALIDATED
scheduled_wake=UNVERIFIED
release_authorization=BLOCKED
```

P009's own `review_status` field cannot approve a gate. The operator-supplied summary has no raw logs or provenance attachments, so it does not satisfy individual review. Passing P009 CI means the offline tools and synthetic safety cases passed; it does not change hardware gates, authorize installation, or authorize unattended operation.
