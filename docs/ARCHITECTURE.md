# Architecture — iOS-Caffeinate

## System Overview

iOS-Caffeinate is a native C11 CLI and daemon system targeting jailbroken iOS 12.5.7 (Amethyst/Procursus rootful) on Apple A7 (ARM64) hardware.

Components:
1. `ios-caffeinate`: Client CLI.
2. `ios-caffeinated`: Daemon service managing power assertions and client IPC.
3. `ic`: Relative symlink to `ios-caffeinate`.
4. `ic wake status`: Local, read-only capability report; does not use daemon IPC.
5. `ic server status|doctor|plan`: Read-only policy, health, and readiness diagnostics.
6. `ic server trial`: Explicit, single-owner, bounded assertion trial capped at 300 seconds.

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

## P006 Server Policy, Health, and Recovery

The optional `/var/lib/ioscaffeinate/server-mode.json` file has schema version 1 and accepts only `disabled` or `observe_only`. It is read-only in P006; missing, malformed, symlinked, incorrectly owned, linked, oversized, or non-0600 files fail closed. `observe_only` enables diagnostics only. It cannot enable an unattended assertion.

Configured policy is distinct from runtime trial state and current daemon assertion state. The default policy is `DISABLED`; runtime hardware readiness is `BLOCKED` while any of ten hardware evidence gates are pending. All Linux mock and CI results remain source/build evidence only. The CLI reports current daemon-owned assertion information separately from OS power state; OS state and cleanup by a previous process remain `UNVERIFIED`.

Health observations include daemon uptime, assertion lifecycle, acquisition and release timestamps, last release error, schedule activity, and recent error count. Battery, charging, thermal, LAN, and Tailscale measurements report `UNAVAILABLE` until supplied by supported read-only sources or an independent observer. No sensors or networks are polled by the daemon.

Server trials share the existing P004 assertion owner. They require an explicit CLI request, expire after at most 300 seconds, support STOP and SIGTERM cleanup, and never resume after STOP or restart. Automatic release retry is capped at three attempts; persistent failure remains visible as `RELEASE_FAILED` while the daemon runs. Process death can prevent cleanup, and a restarted daemon does not infer that a prior assertion was released.

The connectivity evidence contract lives in `docs/schemas/connectivity-evidence-v1.schema.json`. LAN and Tailscale records are independent and include their own connection, authenticated SSH, latency, time, and screen-lock observations. Daemon status cannot establish reachability. The bundled launchd template remains disabled and is not activated in P006.

## Timed Awake, Scheduled Awake, and Scheduled Wake

These are separate capabilities:

- **Timed Awake**: a bounded hold asks the power backend to inhibit an idle transition. The iOS IOKit call is dynamically resolved and remains runtime- and hardware-unverified.
- **Scheduled Awake**: while `ios-caffeinated` is running, the P004 event loop evaluates persisted calendar schedules and acquires an assertion for an active bounded window. Missed windows are skipped; the daemon does not replay them or attempt to wake itself.
- **Scheduled Wake**: a platform or hardware facility resumes the system at a requested time. P005 has no supported iOS 12 mechanism or command for this capability. It is reported as `unverified`, with `wake_guarantee=no`.

`wake status` is evaluated locally by the CLI and prints the compile-time target/backend identity. It does not resolve IOKit symbols, call an assertion API, acquire/release power, connect to the daemon, or load/modify schedule state. A Linux result identifies `MOCK_NO_POWER_EFFECT` and is never hardware evidence. The report's unavailable runtime probe is deliberate; target wake facilities have not been established by a read-only probe.
