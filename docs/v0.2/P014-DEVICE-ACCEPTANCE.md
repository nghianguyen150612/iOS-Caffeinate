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
2. Start and stop the daemon manually with no active assertion; verify release, process exit, socket, and lock observations separately.
3. Exercise a controlled ordinary exit without holding an assertion and compare daemon observations with an independent supervisor observation.
4. Exercise a startup failure before assertion acquisition; verify bounded cooldown reporting and the P013 gate.
5. Verify explicit operator cancellation remains authoritative.
6. Verify repeated simulated failures are suppressed by the three-attempt policy without spawning a real launchd job.
7. Verify recovery and P004 schedule records remain unchanged across the planned cases except for documented events.

Do not intentionally crash a daemon holding an active assertion in the first physical session. Do not automate SIGKILL, unattended endurance testing, or reboot-persistence testing. A reboot-persistence test requires a separate authorization and recovery plan. Any uncertain cleanup, stale socket, held/ambiguous lock, release failure, or unexpected schedule acquisition stops the session and requires direct operator review.

## Evidence and limits

Record exact timestamps, timebase IDs and uncertainty; distinguish operator statements, device-reported observations, and external observer results. P009 `SIMULATED`/`MOCK` records are not hardware evidence. A successful process restart, release call, or SSH connection does not independently prove assertion cleanup, launchd boot persistence, OS awake state, or long-duration reliability. P014 acceptance does not authorize unattended production use.
