# P016 — Manifest

| Item | Value |
|---|---|
| Milestone | P016 — Health, Battery & Thermal Monitoring |
| Branch | `ios/p016-health-telemetry` |
| Integration base | `ios/p015-server-mode-v2` |
| Expected base SHA | `ef46cdc467128bf658c81dc891915aa91a2ddbca` |
| Validation workflow | `p016-health-telemetry-validation` |
| Device telemetry status | `P016_CLOUD_COMPLETE_DEVICE_TELEMETRY_PENDING` |
| Battery percentage / charging | `UNAVAILABLE` pending a strictly read-only source |
| Thermal category | `UNAVAILABLE`; `NSProcessInfo` unknown-state fallback is ambiguous |
| Device uptime | `mach_continuous_time`, runtime unverified |
| Daemon health | Existing read-only `SERVER STATUS` IPC |
| P009 schema | Version 1 unchanged |
| P012 protocol | Unchanged; no sampling in quiet intervals |
| P012 association | Optional explicit trial/condition labels; operator must assert sampling is outside quiet interval; no trial record write |
| P014 recovery | Existing blockers preserved |
| Persistent telemetry | None |
| Background polling | None |
| Automatic server mode | Not implemented or enabled |
| Hardware measurements | None claimed |

The CI workflow generates the exact source SHA and deterministic run report. This manifest describes scope; it is not hardware evidence or P009 acceptance.
