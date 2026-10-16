# Architecture — iOS-Caffeinate

## System Overview

iOS-Caffeinate is a native C11 CLI and daemon system targeting jailbroken iOS 12.5.7 (Amethyst/Procursus rootful) on Apple A7 (ARM64) hardware.

Components:
1. `ios-caffeinate`: Client CLI.
2. `ios-caffeinated`: Daemon service managing power assertions and client IPC.
3. `ic`: Relative symlink to `ios-caffeinate`.

## Daemon Lifecycle & Assertion State Machine

The daemon (`ios-caffeinated`) manages IOKit power assertions via an explicit C11 state machine:

- `IDLE`: Daemon running, no active power assertion.
- `ACQUIRING`: Transition state while calling power backend acquire.
- `ACTIVE`: Assertion acquired and held until deadline or explicit client `STOP`.
- `RELEASING`: Transition state while releasing an assertion.
- `RELEASE_FAILED`: State when backend release fails; periodic retries scheduled.
- `SHUTTING_DOWN`: Final state during signal-driven or fatal exit; attempts assertion cleanup.

Key state invariants:
1. Only one active assertion is owned by the daemon.
2. Assertion IDs are tracked and never overwritten while held.
3. Release failures do not report false successful `STOP` or `IDLE` status.
4. Clean initial state on daemon start (no automatic re-acquisition of past unverified IDs).

## Event Loop & Timing

- Monotonic clock: `clock_gettime(CLOCK_MONOTONIC)` guarantees immunity against wall-clock changes or NTP adjustments.
- Deadline calculation: Active holds compute deadline `now() + duration_seconds`.
- Poll event loop: Uses `poll()` with dynamic timeout calculated from the nearest upcoming deadline or release retry time, eliminating CPU spinning while remaining immediately responsive to client sockets and signals (SIGTERM/SIGINT).

## IPC Security & Framing

- Endpoint: `/var/run/ioscaffeinated.sock` (permissions `0600`).
- Sidecar lock: `/var/run/ioscaffeinated.sock.lock` serializes stale socket check, bind, and listen operations.
- Peer Credential Authentication:
  - On Darwin/iOS, `getpeereid()` verifies client effective UID.
  - On Linux, `SO_PEERCRED` checks `ucred.uid`.
  - Default socket path requires root access (UID 0). Private socket paths for unprivileged tests enforce match against the daemon process EUID.
- Protocol framing:
  - ASCII newline-terminated frames.
  - Maximum 127 byte command frame.
  - Non-blocking socket I/O with 1-second timeout per client read/write to prevent slow-client blocking.

## Structured Logging

Diagnostics are printed to `stderr` with standardized timestamps:
`[YYYY-MM-DD HH:MM:SS] [LEVEL] Message`

Log levels used: `INFO`, `WARN`, `ERROR`.

## Backend Separation

1. `IOKit_RUNTIME_UNVERIFIED` (Apple iOS): Dynamically resolves `IOPMAssertionCreateWithName` and `IOPMAssertionRelease` from `/System/Library/Frameworks/IOKit.framework/IOKit`.
2. `MOCK_NO_POWER_EFFECT` (Linux test mock): Gated behind `-DIOSCAFFEINATE_TEST_MOCK`. Supports fault injection via environment variables (`IOSCAFFEINATE_MOCK_FAIL_ACQUIRE`, `IOSCAFFEINATE_MOCK_FAIL_RELEASE`) for deterministic lifecycle testing.
