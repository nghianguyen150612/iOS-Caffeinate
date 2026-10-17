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
7. Rootful Debian package: `com.ioscaffeinate.cli`, architecture `iphoneos-arm`, with ARM64/iOS 12.0 Mach-O executables, a read-only manager, project documentation, and an inert staged launchd template.

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
  - Maximum 510-byte command payload plus its newline terminator.
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

The connectivity evidence contract lives in `docs/schemas/connectivity-evidence-v1.schema.json`. LAN and Tailscale records are independent and include their own connection, authenticated SSH, latency, time, and screen-lock observations. Daemon status cannot establish reachability. The bundled launchd template remains disabled and is not activated.

## Timed Awake, Scheduled Awake, and Scheduled Wake

These are separate capabilities:

- **Timed Awake**: a bounded hold asks the power backend to inhibit an idle transition. The iOS IOKit call is dynamically resolved and remains runtime- and hardware-unverified.
- **Scheduled Awake**: while `ios-caffeinated` is running, the P004 event loop evaluates persisted calendar schedules and acquires an assertion for an active bounded window. Missed windows are skipped; the daemon does not replay them or attempt to wake itself.
- **Scheduled Wake**: a platform or hardware facility resumes the system at a requested time. P005 has no supported iOS 12 mechanism or command for this capability. It is reported as `unverified`, with `wake_guarantee=no`.

`wake status` is evaluated locally by the CLI and prints the compile-time target/backend identity. It does not resolve IOKit symbols, call an assertion API, acquire/release power, connect to the daemon, or load/modify schedule state. A Linux result identifies `MOCK_NO_POWER_EFFECT` and is never hardware evidence. The report's unavailable runtime probe is deliberate; target wake facilities have not been established by a read-only probe.

Schedule state is loaded only from an absolute, bounded path and a private regular file owned by the daemon user with mode `0600`. The daemon pins each parent directory without following symlinks, rejects hard links and file replacement during load, and rejects malformed or unsafe schedule records instead of silently dropping them. Schedule writes use a private exclusive temporary file, flush and sync its contents, then rename it into place. Before a scheduled assertion is acquired, the occurrence marker must be written successfully; a failed write blocks that acquisition. If assertion acquisition then fails, the daemon restores the prior marker only when the rollback write succeeds.

## P007 Rootful Package and Lifecycle Boundary

The Debian package architecture (`iphoneos-arm`) is the rootful package-manager convention; the actual executable architecture is thin ARM64 Mach-O targeting iOS 12.0. The two identifiers are validated separately. P007 follows Theos' rootful packaging convention and does not support rootless `iphoneos-arm64`.

The package installs the CLI and daemon in `/usr/local/bin`, `ic` as a relative symlink to the CLI, and the manager in root-owned executable storage at `/usr/local/libexec/ioscaffeinate-manager`. Documentation and SHA-256 manifests are under `/usr/share`; schedules and optional server policy remain in `/var/lib/ioscaffeinate`; logs remain in `/var/log/ioscaffeinate`. No schedule/server-mode fixture is packaged. The launchd plist is inert under `/usr/share/ioscaffeinate/launchd`, not auto-discoverable from `/Library/LaunchDaemons`.

Package scripts reject unowned file collisions before extraction and refuse upgrade/removal while the default daemon socket path exists. They never launch or terminate a process, alter launchd, erase persistent data, or download tools. There are no post-install or post-remove scripts. Ordinary removal leaves non-empty state/log directories and their contents intact. The manager's status, verify, doctor, rollback-check, and uninstall-check commands are read-only.

CI packages the unsigned Mach-O files and labels the `.deb` **UNSIGNED / DEVICE-UNVERIFIED**. A caller may explicitly provide a trusted local `ldid` path for an ad-hoc `ldid -S` stage without entitlements; the package tool checks only for signature presence. Signature verification, jailbreak acceptance, package installation, iOS execution, IOKit assertion behavior, network survival, and continuous operation are separate gates and remain hardware-unverified. See [P007 packaging](P007-PACKAGING.md), [validation](P007-VALIDATION.md), [device procedure](P007-DEVICE-TEST.md), and [rollback](P007-ROLLBACK.md).

## P008 Integration Evidence

P008 uses `c8512508a80be5fc09d0c62b2e26877717af23df` as the P007 integration baseline. Its CI preserves the four source/build/package jobs and adds a dependent evidence job. That job emits the version 1 release-candidate manifest, exact-SHA CI attestation, checksums, and release-readiness matrix from the artifacts actually built and inspected in the same workflow run. The manifest records its exact source SHA, toolchain, workflow ID, and package checksum. It never marks hardware gates passed. Cloud CI cannot authorize release or device installation.

## P009 Offline Device Acceptance

The Python standard-library tool in `scripts/p009_evidence.py` is an offline companion, not part of the C CLI or daemon. It checks a versioned session against the acceptance and P006 connectivity schemas, verifies deterministic evidence-manifest hashes and safe package paths, reconstructs event order within declared timebases, and evaluates independent LAN/Tailscale and safety gates. It does not open network sockets, collect device state, install/sign packages, or activate launchd.

Input source classes separate `SIMULATED`, `MOCK`, and `CI` records from `DEVICE_REPORTED`, `EXTERNAL_OBSERVER`, and `OPERATOR_RECORDED` observations. Complete physical-origin evidence is still `REVIEW_REQUIRED`; the session's own review-status field cannot pass a gate. An interactive per-gate human review can produce a reviewed report but no signature or proof of provenance. Hashes detect mismatches only. Hardware acceptance remains PENDING until a real supervised iPad session is collected and reviewed. Unattended operation is never authorized by the report, and scheduled wake remains independent of scheduled awake.
