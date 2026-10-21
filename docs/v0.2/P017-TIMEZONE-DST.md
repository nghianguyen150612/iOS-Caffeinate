# P017 — Timezones and daylight saving

## Conversion backend

UTC uses UTC calendar arithmetic. Empty timezone text means the current system-local timezone. On Apple, that timezone is represented by `CFTimeZoneCopySystem`; IANA identifiers are resolved as validated `CFTimeZone` objects and converted through a Gregorian `CFCalendar` bound to that object. No scheduling path sets or clears process-wide `TZ`, calls `tzset()` or uses `mktime()`.

The iPhoneOS 12.4 SDK declares the required CoreFoundation timezone and calendar APIs. The target iPad has not run this code. If the backend cannot prove the requested identifier or convert a date, diagnostics return `TIMEZONE_UNVERIFIED` (or `INVALID` for a malformed identifier) and leave the occurrence unresolved. Linux accepts UTC and the host system timezone where available; arbitrary IANA zones are gated as unverified. Test fixtures are not platform evidence.

IANA text is syntactically checked and resolved by the platform timezone database, never concatenated into a timezone-file path. UTC aliases are supported. A timezone name unavailable on the target is not silently replaced by UTC or system local.

## Civil-time policy

- A nonexistent local time in a forward transition is skipped. The analysis records `DST_NONEXISTENT_LOCAL_TIME`; it is not shifted to a later wall time.
- An ambiguous local time in a backward transition resolves to the earliest UTC instant, called `AMBIGUOUS_FIRST`. The later fold is not a second logical occurrence.
- A logical identity includes schedule ID and definition revision, intended local date and time, effective timezone, resolution and UTC start/end. Repeated evaluation and a wall-clock rollback therefore refer to the same logical instance.
- One-time schedules are UTC instants; DST does not alter their start.

These rules are v2 semantics. P004 did not define a stable gap/fold contract: its `mktime()` result depended on the C library defaults and process timezone. P017 intentionally stops legacy automatic execution, preserves all schedule records and does not rewrite their timestamps. Any future executor must receive a separate reviewed migration/compatibility decision before it can consume recurring definitions.

System timezone changes affect future system-local recurrence analysis. Each preview resolves against the effective zone at evaluation time and shows that zone in the occurrence identity. Already stored `last_fired_time` is an absolute timestamp and is not rewritten. Explicit IANA schedules remain tied to their named zone.
