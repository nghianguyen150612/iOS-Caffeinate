# P004 — Timed Awake & Scheduling Architecture

## Overview

The scheduling subsystem in `ios-caffeinated` manages one-time and recurring keep-awake schedule definitions and triggers power assertions when scheduled windows become active.

## Schedule Definitions & Data Structures

Schedule items are defined in `src/schedule.h`:

- `SCHED_TYPE_ONETIME`: UTC timestamp (`target_time`).
- `SCHED_TYPE_DAILY`: Hour (0..23) and Minute (0..59) in local or IANA timezone.
- `SCHED_TYPE_WEEKLY`: Hour, Minute, and Weekday bitmask (Sun=bit 0, Mon=bit 1..Sat=bit 6).
- Duration: 1s to 86400s (24 hours).

State is stored in a bounded JSON file (`/var/lib/ioscaffeinate/schedules.json`) up to 64 schedule definitions.

## Evaluation & Dynamic Event Loop Integration

During each iteration of the daemon `poll()` loop:

1. `schedule_store_evaluate()` calculates:
   - Whether any schedule is currently within an active window (`active_index`, `active_remaining`).
   - The time until the next upcoming scheduled start (`next_index`, `next_start`).
2. If an active schedule is found and no assertion is currently held, `ios-caffeinated` acquires a power assertion for `active_remaining` seconds.
3. The `poll()` timeout is set dynamically to wake up at the exact monotonic/wall deadline for the next event.

## Restart Recovery & Conflict Policy

- **Restart Recovery**: When the daemon starts or restarts, it reloads `schedules.json`. If a scheduled occurrence started in the past but its duration is still active, the daemon acquires an assertion for the remaining duration (`start_time + duration - now`).
- **Missed Occurrences**: Occurrences whose end time passed while the daemon was offline are logged and skipped. They are never replayed.
- **One-Assertion Policy**: Only one native IOPMAssertion is active at any time. Manual holds (`start --for`) take immediate precedence; overlapping schedule triggers are ignored while a hold is active.
