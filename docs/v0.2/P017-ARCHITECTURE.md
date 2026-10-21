# P017 — Scheduling architecture

P017 separates stored intent, calendar analysis, operational blockers and assertion authority. `src/schedule.c` contains deterministic recurrence, occurrence identity, conflict analysis and safe persistence. It does not call IOKit, launchd or the network. The CLI reads definitions directly for diagnostics and does not start the daemon.

```text
schema-v1 definitions -> strict storage checks -> calendar/timezone analysis
       -> bounded conflict analysis -> P014/P015/P016 diagnostics
       -> explicit executor authorization (currently denied)
```

The daemon no longer evaluates a due schedule to create an assertion. This is a deliberate compatibility change: P015 rejects unattended scheduled execution, so retaining P004's automatic executor would bypass the current policy boundary. Definitions and `last_fired_time` remain intact. Schedule diagnostics report temporal status separately from runtime status and from authorization.

P014 remains authoritative for recovery state and manual assertion ownership. `schedule doctor` reports the existing daemon gate if available and reads the recovery journal without changing it. P015 is evaluated for the `SCHEDULED_UNATTENDED` operation, which always reports `SCHEDULE_EXECUTOR_NOT_AUTHORIZED`. P016 is diagnostic only: no sampling loop is introduced, and unobserved or stale battery, charging and thermal values remain unknown.

The iOS timezone backend uses CoreFoundation `CFTimeZone` objects and Gregorian `CFCalendar` instances, keeping each conversion bound to a timezone object instead of changing process-wide `TZ`. Those APIs are declared by the iPhoneOS 12.4 SDK. Both CLI and daemon link the system CoreFoundation framework for this backend; the exact dependency allowlist and package checks include it. Runtime behavior on iOS 12.5.7 has not been verified. An unresolved or unsupported backend produces `TIMEZONE_UNVERIFIED` and no fabricated occurrence. Linux tests use injected deterministic calendar fixtures; they do not establish Darwin compatibility.

The persisted schema remains version 1. No package-install migration runs. Mutations use authenticated root-only daemon IPC with a store-generation precondition, atomic replacement, read-back verification and rollback attempts. Editing a definition does not acquire an assertion. See [storage and migration](P017-STORAGE-MIGRATION.md), [recovery policy](P017-RECOVERY-POLICY.md) and [safety boundary](P017-SAFETY.md).

P017 validates planning and diagnostics only. It does not establish that the daemon will be running at a future time. **Scheduling an assertion does not guarantee waking the device from deep sleep.** `scheduled_wake=UNVERIFIED` remains the reported capability.
