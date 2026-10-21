# P017 — Schedule CLI

Read-only schedule diagnostics load persisted definitions directly. They do not start the daemon. Global path overrides are available for fixtures: `--schedule-state /absolute/path`, `--recovery-state /absolute/path`, `--server-config /absolute/path`, and `--socket /absolute/path.sock`.

```sh
ic schedule list [--at <ISO-8601>]
ic schedule next [--at <ISO-8601>]
ic schedule doctor [--at <ISO-8601>]
ic schedule conflicts [--at <ISO-8601>]
ic schedule validate
ic schedule explain <schedule-id> [--at <ISO-8601>]
ic schedule enable <schedule-id> [--if-generation <hex>] [--dry-run]
ic schedule disable <schedule-id> [--if-generation <hex>] [--dry-run]
ic schedule remove <schedule-id> [--if-generation <hex>] [--dry-run]
```

`--at` is a read-only deterministic reference instant with an explicit ISO-8601 timezone. `validate` checks definitions and persistence only. `list` and `next` enumerate definition state and their next diagnostic occurrence; neither implies the daemon is running. `doctor` adds runtime (read-only IPC if already available), P014 journal, P015 scheduled-operation policy, P016 telemetry availability and scheduled-wake capability. Runtime absence remains unknown. `conflicts` reports exact windows or an incomplete analysis. `explain` combines one definition, its next occurrence and conflicts.

Mutations require root through the existing authenticated daemon IPC ownership boundary. The store generation is a compare-and-swap precondition; stale edits fail. The daemon also requires trusted recovery state and idle assertion ownership. `--dry-run` shows the proposed state and conflict counts without writing. Without it, daemon availability, secure storage and safe state are required. Enabling or editing never starts the daemon or acquires an assertion. New `schedule add` proposals are limited to 300 seconds. Existing remove syntax remains available; clients use a generation precondition.

Every output is diagnostic. The executor is `NOT_AUTHORIZED`, and scheduled wake is `UNVERIFIED` even when a future calendar occurrence can be calculated.

```text
# SIMULATED CLI output; not device evidence
schedule.storage=VALID
schedule.count=1
schedule.next_utc=2026-10-22T07:30:00Z
schedule.execution=BLOCKED_POLICY reason=SCHEDULE_EXECUTOR_NOT_AUTHORIZED
scheduled_wake=UNVERIFIED execution=NOT_GUARANTEED
```
