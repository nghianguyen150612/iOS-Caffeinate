# P004 — Timed Awake Scheduling

## P004 v1 behavior recorded during the P017 audit

The v1 store is `/var/lib/ioscaffeinate/schedules.json`, schema version 1, with up to 64 definitions:

- One-time UTC timestamp schedules.
- Daily local wall-clock schedules.
- Weekly schedules with Sunday-based weekday mask bits.
- Optional timezone text.
- Durations from 1 through 86,400 seconds.
- `last_fired_time` records the end boundary of the last consumed window.

Before P017, recurrence evaluation temporarily changed process-wide `TZ`, called `localtime_r()` and `mktime()`, and inspected nearby dates using 86,400-second offsets. The daemon evaluated definitions at startup and during its event loop. When recovery allowed acquisition, an active window could acquire a new assertion. It marked `last_fired_time` before acquisition and attempted a persistence rollback if acquisition failed. Storage was already bounded and used private temporary files, sync, and atomic rename.

These are the recorded legacy semantics. They explain existing data and compatibility behavior; they are not the P017 runtime contract.

## P017 runtime contract

P017 preserves schema-v1 definitions and their `last_fired_time` values. It replaces recurrence previews with calendar-date enumeration and removes process-wide timezone mutation.

The daemon no longer evaluates a due schedule to acquire an assertion. P015 rejects unattended scheduled execution, so a P004 schedule cannot authorize a power assertion. This intentionally stops legacy automatic schedule execution while keeping stored definitions readable and diagnosable. A preview never updates `last_fired_time`.

New schedule proposals are limited to 300 seconds. Existing definitions up to 86,400 seconds remain unchanged and are reported as `LEGACY_DURATION_EXCEEDS_POLICY`. P017 does not truncate them or renew them as chained sessions.

See the P017 architecture, timezone/DST, recurrence, conflict, storage, CLI, recovery, safety, validation, and device-acceptance documents in `docs/v0.2/`.
