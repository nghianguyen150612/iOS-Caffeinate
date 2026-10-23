# P014 — Architecture

P014 adds a recovery policy beside the P003 assertion state machine. It does not replace that state machine, start a second privileged process, or call launchctl. `src/recovery.c` contains deterministic policy and journal code; `src/daemon.c` uses the journal to block assertions after an unclean or unknown prior run; `src/service.c` adds read-only recovery diagnostics and an explicit operator-reviewed journal reset.

The policy boundary is:

```text
observed exit + cleanup facts + supervisor facts + durable metadata + monotonic clock
                                      │
                                      ▼
                         recovery decision and reason
                                      │
                         attended eligibility only
```

There is no restart executor in P014. A safe policy result never runs a command. The output `ELIGIBLE_FOR_ATTENDED_START` is not launchd authorization. Production automatic recovery remains inactive and reports `recovery.runtime_activated=no`.

`recovery_supervisor_adapter_t` is an injectable observation callback for a future supervisor. It can supply exit, cleanup, socket, lock, service-readiness, and compatibility facts to the pure policy evaluator. Callback failure is represented as unknown supervisor state and blocks eligibility. The interface has no spawn/start/action callback, and no production iOS adapter is installed.

## Existing runtime behavior

- `ios-caffeinate` and its `ic` symlink send commands to the single `ios-caffeinated` owner.
- The daemon owns at most one IOKit assertion and uses monotonic deadlines for expiry.
- `STOP` releases the current assertion but leaves the daemon running.
- `SHUTDOWN` acknowledges only after a successful release; service status separately waits for process/socket cleanup.
- SIGTERM and SIGINT are observed by the daemon and enter its cleanup path. The signal number is recorded only if that handler ran.
- SIGKILL, power loss, and abrupt kernel termination are not observed by the daemon. A later process sees an unclean durable run marker and records the cause as `UNKNOWN_UNOBSERVED`.
- A process exit and assertion cleanup are separate facts. Neither an absent PID nor a stale socket proves the old assertion was released.

P004 originally evaluated an active schedule after daemon startup. Before P014, a new daemon could acquire a new assertion for an active window even though cleanup of an assertion owned by a prior process was unknown. P014 added a recovery gate for schedules, `probe`, bounded `start`, and server trials. P017 later suppresses the schedule executor because P015 does not authorize unattended scheduled assertions; the P014 gate remains authoritative for any manual acquisition and for a future separately reviewed executor. Read-only status, STOP, and SHUTDOWN remain available while blocked.

## Recovery journal and startup gate

The journal is `/var/lib/ioscaffeinate/recovery-state.json`. The daemon writes it only while holding the existing socket lock, which establishes the single-writer invariant. It records a `RUNNING` marker before assertion-capable operation. A later startup blocks acquisitions when the prior marker was still `RUNNING`, the journal was absent, cleanup was unverified, a release/ownership failure still requires review, or the file was unsafe or unsupported.

A clean journal permits manual acquisition subject to the other gates. It no longer authorizes P004 schedule execution: P017's scheduled executor is disabled under P015. A first P014 run with no journal is deliberately unverified; `recovery_store_begin_run()` durably marks that run `RUNNING` with cleanup `UNVERIFIED` and blocks assertions. A root operator may use the existing reviewed recovery operation before first daemon startup, but only after independently establishing service, socket, lock, prior assertion ownership, and cleanup state. A missing file alone never authorizes the reset.

`ic service recovery status` and `ic service recovery plan` expose the recovery state, last exit category, attempt budget, cooldown, cleanup confidence, eligibility, blocker, supervisor compatibility, and runtime activation. Both commands are read-only.

The explicit command `ic service recovery reset --reviewed-cleanup --reviewed-supervisor-state` records an operator-reviewed cleanup decision. It requires root, a confirmed unregistered service, and an absent socket while holding the safe daemon lock through the journal write. From a missing-journal state it can create the initial reviewed record; from corrupt, unsafe, or unsupported state it refuses to rewrite anything. It does not remove stale sockets, call launchctl, or collect device evidence. The operator must complete the direct device review described in [device acceptance](P014-DEVICE-ACCEPTANCE.md) first. The record remains `OPERATOR_REVIEWED`; it is not a `DEVICE_REPORTED` P009 observation.

## P013 boundary

P013 `enable`, `start`, `restart`, and `disable` remain fail-closed while iOS 12 launchctl semantics are unverified. P014 does not add launchd registration or install the live plist. The managed profile keeps `KeepAlive=false`; no `SuccessfulExit=false` restart shortcut is added. The packaged template remains inert. No cloud test starts a launchd job or acquires a real power assertion.

## Separate capabilities

Crash detection, exit classification, assertion cleanup, restart eligibility, an actual process restart, launchd boot persistence, SSH reachability, OS awake state, and long-duration reliability are separate capabilities. P014 validates policy and host simulations only. Device recovery and unattended reliability remain `UNVERIFIED`.
