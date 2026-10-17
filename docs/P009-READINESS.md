# P009 — Project Readiness

P009 cloud engineering builds an offline acceptance harness. The iPad is unavailable, so this report contains no physical-device observations. Synthetic test cases are isolated under tests and are not acceptance evidence.

| Readiness item | Status |
|---|---|
| Evidence schema, offline validator, replay, and report | IMPLEMENTED; exact-commit cloud results are recorded by the P009 workflow artifact |
| Device identity and iOS runtime | PENDING |
| Package integrity, signature acceptance, installation, and rollback | PENDING |
| IOKit acquisition and release | PENDING |
| Bounded hold, STOP, natural expiry, SIGTERM cleanup | PENDING |
| Screen-locked LAN SSH | PENDING |
| Screen-locked Tailscale SSH | PENDING |
| Battery and thermal observations | PENDING |
| Physical recovery and launchd-disabled verification | PENDING |
| Scheduled wake | UNVERIFIED |
| Unattended 24/7 operation | NOT VALIDATED |

```text
hardware_acceptance=PENDING
unattended_24_7=NOT_VALIDATED
scheduled_wake=UNVERIFIED
```

Passing P009 CI means the offline tools and synthetic safety cases passed. It does not change any hardware row, authorize installation, or authorize unattended operation.
