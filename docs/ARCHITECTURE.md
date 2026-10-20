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

## P014 Crash Recovery Policy

P014 adds `src/recovery.c` as a separate C11 decision engine. The engine consumes caller-supplied exit, cleanup, supervisor, socket, lock, clock, and persisted-accounting observations. It returns a reasoned policy result and attended-start eligibility; it never runs a process or calls launchctl. The current iOS implementation has no enabled supervisor adapter, so automatic runtime restart is reported as `no`.

The root-owned `/var/lib/ioscaffeinate/recovery-state.json` journal records a durable `RUNNING` marker before the daemon evaluates P004 schedules. An unclean or untrusted prior record gates new assertion acquisition from schedules, probe, start, and server trials. It preserves P004 schedule data and permits ordinary evaluation after trusted clean state or an explicit operator-reviewed cleanup reset. P013 mutation gates remain closed and the managed launchd profile remains `KeepAlive=false`.

Crash detection, exit classification, assertion cleanup, restart eligibility, process restart, launchd boot persistence, SSH reachability, OS awake state, and long-duration reliability remain distinct. Cloud mocks and simulations validate policy and persistence behavior only; they do not establish kernel cleanup after SIGKILL or physical reliability.

## P015 Server Mode v2 Policy

P015 extends the P006 configuration path with strict schema v2 while preserving v1 `disabled` and `observe_only`. The pure C11 evaluator in `src/server_policy.c` consumes a requested operation, bounded duration, read-only runtime observation, P014 journal status, reviewed P009-compatible hardware evidence, and explicit battery/thermal availability. It returns a deterministic decision and all known blocker reasons. Missing data remains missing; CI, mocks, simulations, and unreviewed operator statements cannot satisfy hardware gates.

`ic server policy show|validate|explain|plan|migrate --dry-run` only read state. Migration does not write. A config writer is gated. `ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION` only permits a later separate authorization step; execution authorization remains false and P015 includes no executor. The policy path never calls launchctl, IOKit, service start/restart, or schedule mutation. P013 `KeepAlive=false` and P014 cleanup/recovery gates remain unchanged. Battery/thermal measurement integration belongs to P016; SSH/Tailscale reachability does not prove awake state.

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

CI packages the unsigned Mach-O files and labels the `.deb` **UNSIGNED / DEVICE-UNVERIFIED**. P010 adds an opt-in `amethyst-ios12-rootful` profile containing only `com.apple.private.security.no-container=true`. The builder requires an explicit host-compatible `ldid`, validates embedded entitlements, and proves the result is a signature-only transformation of the exact source copy. It records signature presence separately from host integrity verification, device execution, and package acceptance. See [P010 signing](P010-SIGNING.md), [package validation](P010-PACKAGING-VALIDATION.md), and [device acceptance](P010-DEVICE-ACCEPTANCE.md).

## P008 Integration Evidence

P008 uses `c8512508a80be5fc09d0c62b2e26877717af23df` as the P007 integration baseline. Its CI preserves the four source/build/package jobs and adds a dependent evidence job. That job emits the version 1 release-candidate manifest, exact-SHA CI attestation, checksums, and release-readiness matrix from the artifacts actually built and inspected in the same workflow run. The manifest records its exact source SHA, toolchain, workflow ID, and package checksum. It never marks hardware gates passed. Cloud CI cannot authorize release or device installation.

## P009 Offline Device Acceptance

The Python standard-library tool in `scripts/p009_evidence.py` is an offline companion, not part of the C CLI or daemon. It checks a versioned session against the acceptance and P006 connectivity schemas, verifies deterministic evidence-manifest hashes and safe package paths, reconstructs event order within declared timebases, and evaluates independent LAN/Tailscale and safety gates. It does not open network sockets, collect device state, install/sign packages, or activate launchd. P010 preserves the October 18 operator summary outside a P009 session because raw files and provenance were not provided; its review field cannot approve a gate.

Input source classes separate `SIMULATED`, `MOCK`, and `CI` records from `DEVICE_REPORTED`, `EXTERNAL_OBSERVER`, and `OPERATOR_RECORDED` observations. Complete physical-origin evidence is still `REVIEW_REQUIRED`; the session's own review-status field cannot pass a gate. An interactive per-gate human review can produce a reviewed report but no signature or proof of provenance. Hashes detect mismatches only. P010's operator-reported execution, assertion, cleanup, and SSH observations need P009 review; package acceptance remains pending. Unattended operation is never authorized by the report, and scheduled wake remains independent of scheduled awake.

## P013 Opt-in LaunchDaemon Lifecycle

`ic service status|doctor|plan` read fixed package, plist, launchctl, daemon IPC, and assertion observations without changing service, package, schedule, or power state. Fields keep package installation, managed-plist presence, enablement, launchd registration, runtime process, IPC, and daemon-owned assertion state separate. Missing observations remain unknown.

The packaged LaunchDaemon template remains at `/usr/share/ioscaffeinate/launchd` with `Disabled=true` and `RunAtLoad=false`; package scripts do not copy it to `/Library/LaunchDaemons`. A distinct managed profile is generated with `Disabled=false`, `RunAtLoad=false`, and `KeepAlive=false`. It is validated for exact content, root ownership, permissions, parent safety, link count, and collisions. Its file installer uses a private temporary file and no-replace atomic installation. P013 does not install that file while iOS 12 launchd mutation semantics are unverified.

`enable`, `disable`, `start`, and `restart` require root and fail closed while the relevant launchctl syntax and behavior are unverified. `stop` requires confirmed managed registration and responsive daemon IPC. The daemon's new `SHUTDOWN` protocol request releases its owned assertion before acknowledging and exiting; the CLI then waits for socket removal and launchd's stopped PID report. Release failure, unknown assertion ownership, or timeout remains unresolved. The managed profile prevents an indefinite P013 crash-relaunch loop. Boot persistence, OS awake state, and SSH reachability are independent and remain `UNVERIFIED`.

Package removal/upgrade refuses an existing default socket or live plist and also refuses if read-only status cannot positively establish no registered job, observed process, or IPC service. User schedules, server policy, evidence, and logs remain untouched. The P013 device acceptance procedure requires P011 package acceptance, P012 safety review, operator presence, and direct recovery; CI does not execute it.
