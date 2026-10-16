# P004 — Timed Awake, Persistent Scheduling & Daemon Restart Recovery Validation

## Overview

P004 introduces timed keep-awake scheduling and persistent state management to iOS-Caffeinate.

## Features Implemented

1. **Absolute Deadline (`start --until <ISO-8601>`)**:
   - Converts wall-clock deadlines with explicit ISO-8601 offsets (e.g. `2026-10-18T23:00:00+07:00` or `Z`) into bounded monotonic durations (1s..24h) at acquisition time.
   - Rejects past deadlines, invalid offsets, and durations exceeding 24 hours.

2. **One-Time, Daily & Weekly Schedules**:
   - `schedule add --at <ISO-8601> --for <duration>`
   - `schedule add --daily <HH:MM> --for <duration> [--tz <IANA_TZ>]`
   - `schedule add --weekly <mon,wed,fri> --at <HH:MM> --for <duration> [--tz <IANA_TZ>]`
   - `schedule list` and `schedule remove <schedule-id>`

3. **Persistent Schedule Storage**:
   - Bounded JSON state stored in `/var/lib/ioscaffeinate/schedules.json` (mode `0600`, root-owned).
   - Atomic temporary file write, `fflush`, `fsync`, and `rename`.
   - Symlink traversal and permission checks fail-closed.

4. **Daemon Restart Recovery & One-Assertion Policy**:
   - On daemon startup, active schedules are evaluated against current wall clock time.
   - Restarts during active windows recover only the remaining window duration rather than resetting back to zero.
   - Missed occurrences during daemon downtime are skipped and not replayed as late holds.
   - Only one power assertion is active at a time; conflicts and manual holds take deterministic precedence.

5. **Monotonic vs Wall-Clock Timing**:
   - Calendar matching uses wall clock time (`time(NULL)`).
   - Live assertion expiration uses monotonic deadlines (`CLOCK_MONOTONIC`).

## Linux Mock Test Evidence

```text
Ran 24 tests in 11.350s

OK
```
All 24 unit/integration tests passed.
