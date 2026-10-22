# P015 — Policy States

P015 decision values are stable identifiers emitted as `decision=` by `ic server policy explain`.

| Decision | Meaning |
|---|---|
| `DISABLED` | Missing or explicitly disabled policy does not request server activity. |
| `OBSERVE_ONLY` | Diagnostics may run; the policy does not permit assertion control. |
| `ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION` | All required inputs permit a subsequent, separately authorized attended trial. No action has occurred. |
| `DEFER_INSUFFICIENT_EVIDENCE` | At least one required observation is missing, stale, nonphysical, or not reviewed. |
| `BLOCK_RECOVERY` | P014 journal, cleanup, prior ownership, or recovery state blocks the request. |
| `BLOCK_UNSAFE_RUNTIME` | The observed daemon is blocked or reports an unsafe runtime state. |
| `BLOCK_UNVERIFIED_SUPERVISOR` | An automatic-recovery request lacks verified supervisor compatibility. |
| `BLOCK_UNSAFE_CONFIGURATION` | Configuration is invalid or asks for unsupported unattended/automatic behavior. |
| `BLOCK_RESOURCE_SAFETY` | An explicit resource or hardware gate reports a denial or unsafe state. |
| `BLOCK_DURATION` | Requested duration is zero or exceeds the configured or 300-second ceiling. |
| `BLOCK_ASSERTION_CONFLICT` | An active or independently owned assertion conflicts with a new session. |

Each result also reports `eligible`, `execution_authorized`, `runtime_activated`, `primary_reason`, all blocker reasons, maximum permitted duration, recovery status, evidence source, freshness, and the additional evidence required for each gate.

`runtime_activated=YES` is emitted only from a current daemon observation that reports `ACTIVE` or `assertion_owned=1`. `UNKNOWN` is not converted to `NO`. P014 supervisor compatibility remains separately reported as `UNVERIFIED`; a clean P014 journal does not make the P013 launchd lifecycle gate pass.

P014 restart-budget exhaustion blocks automatic recovery eligibility. P015 implements no automatic recovery operation. P013 `enable`, `disable`, `start`, and `restart` remain blocked under their existing launchd compatibility checks.
