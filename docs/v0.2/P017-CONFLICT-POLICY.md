# P017 — Conflict policy

`ic schedule conflicts [--at <ISO-8601>]` compares enabled definitions across a fixed 370-day horizon. It reports duplicate definitions and intersecting UTC windows for one-time, daily, weekly, mixed and midnight-crossing schedules. Each record names both IDs and gives the two exact UTC start/end windows. Timezone or horizon failures mark the analysis `INCOMPLETE`; an incomplete result is not a clean bill of health.

Schedule windows use elapsed UTC durations after each calendar occurrence is resolved. This also handles windows that cross a timezone offset transition. A manual assertion is compared with the read-only daemon status when available. If daemon status is unavailable, manual ownership is unknown rather than assumed absent.

Conflicts require operator review. P017 does not merge windows, select a winner based on storage order, shorten an active legacy hold or create a second assertion. Enabling a definition previews its conflict consequences, but runtime execution remains unauthorized. If an older daemon already owns a hold, use the established attended STOP/release and P014 recovery lifecycle; do not edit its in-memory schedule file concurrently.

Dry-run edit output is a simulated preview, not hardware acceptance:

```text
# SIMULATED CLI output
schedule.preview=DRY_RUN
schedule.operation=enable
schedule.changed=yes
conflicts.before=0
conflicts.after=1
schedule.execution=BLOCKED_POLICY reason=SCHEDULE_EXECUTOR_NOT_AUTHORIZED
schedule.write_performed=no
```
