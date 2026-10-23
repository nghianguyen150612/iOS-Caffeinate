# P014 — Supervised Device Acceptance

**Status: PENDING.** No iPad was accessed during P014 cloud engineering. The recovery gate remains active in source, and production automatic restart is unavailable.

## Prerequisites

- P011 signed-package installation, provenance, installed-binary, and rollback gates accepted.
- P012 safety findings reviewed and its supervised trial prerequisites met.
- P013 iOS 12.5.7 launchctl read-only and lifecycle semantics accepted in a separate supervised investigation.
- Operator physically present with a tested direct recovery path.
- Installed daemon, service registration, socket, lock, current assertion ownership, and schedules inspected and recorded.
- Battery and thermal conditions reviewed using supported observations.
- Exact package and source provenance recorded in P009 evidence.
- A bounded test plan, stop conditions, and recovery action reviewed before starting.

## Initial supervised cases

1. Run read-only recovery status and record journal provenance.
2. If this is the first v0.2 installation and the journal is absent, complete the first-install review below before starting the daemon.
3. Start and stop the daemon manually with no active assertion; verify release, process exit, socket, and lock observations separately.
4. Exercise a controlled ordinary exit without holding an assertion and compare daemon observations with an independent supervisor observation.
5. Exercise a startup failure before assertion acquisition; verify bounded cooldown reporting and the P013 gate.
6. Verify explicit operator cancellation remains authoritative.
7. Verify repeated simulated failures are suppressed by the three-attempt policy without spawning a real launchd job.
8. Verify recovery and P004 schedule records remain unchanged across the planned cases except for documented events.

## First v0.2 installation with no journal

`recovery_store_begin_run()` deliberately creates a durable `RUNNING` record with cleanup `UNVERIFIED` when the journal is missing. It blocks all new assertions. This is fail-closed behavior, not proof that the first run is clean. To avoid starting the daemon into that blocked state, the existing supervised review command can attest a clean first-install baseline before the first daemon start.

Use this path only after P011 installation gates pass and a physically present operator has independently established all of the following from current device observations and known device history:

- No earlier iOS-Caffeinate daemon or assertion remains unresolved.
- No project daemon process, registered launchd label, live plist, IPC endpoint, or socket is active.
- The current assertion owner and cleanup state are known; `UNKNOWN` is a stop condition.
- A direct recovery method is available and the remaining P014/P011 prerequisites are satisfied.

First run the read-only command and preserve its output. If it reports missing, corrupt, unsafe, unsupported, or otherwise unknown recovery state, do not treat that result as clean. A corrupt or unsafe journal must be preserved and requires a separate recovery plan.

The following command changes the recovery journal and may create the root-owned lock file. It requires its own operator authorization. Run it as root only after the observations above are reviewed and recorded; the flags are an operator attestation, not evidence collected by the command:

```sh
/usr/local/bin/ic service recovery reset --reviewed-cleanup --reviewed-supervisor-state
```

The command refuses to proceed unless it holds the daemon lock, the service is confirmed unregistered, and the default socket is absent. For a missing journal it writes a clean `OPERATOR_REVIEWED` record; for a trusted existing journal it records a reviewed reset. It refuses corrupt, unsafe, or unsupported records and does not remove stale state, call `launchctl`, inspect historical evidence, or verify the operator's external observations.

Afterward, run `ic service recovery status` and preserve the exact output. Proceed only when the record is trusted and cleanup is reported `OPERATOR_REVIEWED`; this label is not a `DEVICE_REPORTED` P009 observation. The next daemon startup writes its `RUNNING` marker. If a crash, release failure, assertion-ownership uncertainty, unsafe filesystem state, or save failure occurs, stop and preserve the journal; do not repeat the reset to clear it.

If the daemon was already started before this review, its first startup should have blocked assertion acquisition. Stop it through the documented graceful path, independently confirm process/socket cleanup and assertion release, then use the reviewed command only if those observations are conclusive. A crash or unknown ownership state remains a blocker.

Do not intentionally crash a daemon holding an active assertion in the first physical session. Do not automate SIGKILL, unattended endurance testing, or reboot-persistence testing. A reboot-persistence test requires a separate authorization and recovery plan. Any uncertain cleanup, stale socket, held/ambiguous lock, release failure, or unexpected schedule acquisition stops the session and requires direct operator review.

## Evidence and limits

Record exact timestamps, timebase IDs and uncertainty; distinguish operator statements, device-reported observations, and external observer results. P009 `SIMULATED`/`MOCK` records are not hardware evidence. A successful process restart, release call, or SSH connection does not independently prove assertion cleanup, launchd boot persistence, OS awake state, or long-duration reliability. P014 acceptance does not authorize unattended production use.
