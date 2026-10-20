# P014 — Recovery States

The recovery state machine is independent of the assertion states `IDLE`, `ACQUIRING`, `ACTIVE`, `RELEASING`, `RELEASE_FAILED`, `SHUTTING_DOWN`, and `BLOCKED`.

| Recovery state | Meaning |
|---|---|
| `HEALTHY` | A trusted journal records a clean prior run; this says nothing about OS awake state. |
| `STOP_REQUESTED` | An explicit stop request was observed; it does not confirm process exit. |
| `EXIT_CONFIRMED` | Exit evidence was observed. Cleanup is evaluated separately. |
| `CRASH_SUSPECTED` | An external observer reports an unexpected exit; this is not an assertion cleanup result. |
| `CLEANUP_UNVERIFIED` | Release acknowledgement, ownership, or external cleanup evidence is missing or failed. |
| `COOLDOWN` | Backoff remains according to the same monotonic clock identity. |
| `RESTART_ELIGIBLE` | Policy permits an attended start after all gates; no operation is executed. |
| `RESTART_BLOCKED` | Socket, lock, service readiness, or another observed state is inconsistent. |
| `RESTART_LIMIT_REACHED` | Three attempts remain in the rolling ten-minute window. |
| `RECOVERY_UNVERIFIED` | State, clock identity, exit cause, or persistence cannot be trusted. |

## Observed facts and inferences

The daemon observes successful or failed release calls, its own `SHUTDOWN` request, and SIGTERM/SIGINT when their handlers run. It can observe that a journal remains marked `RUNNING` after a later start. It cannot observe that SIGKILL occurred, identify a signal after it has died, or infer whether the kernel retained an assertion.

`UNKNOWN_UNOBSERVED` is used when the cause was not observed. `CRASH_SUSPECTED` requires an external supervisor observation. P014 has no compatible iOS 12 supervisor adapter, so it does not produce that fact in production.

## Blocking transitions

- Missing, corrupt, unsupported, unsafe, or partially replaced journal → `RECOVERY_UNVERIFIED` and no new assertion.
- Prior `RUNNING` marker or unconfirmed cleanup → `CLEANUP_UNVERIFIED` and no new assertion.
- Release failure or unknown prior ownership → `BLOCK_CLEANUP_UNVERIFIED`, regardless of elapsed time or remaining budget.
- Explicit stop, confirmed graceful exit, or timed expiry only → `NO_ACTION`.
- Unknown supervisor status, socket ambiguity, lock ambiguity, or unverified service readiness → blocking decision.
- A verified attended cleanup review can clear the journal gate. It does not activate automatic restart or change P013 launchd gates.

The state names describe the policy input and result. They do not imply that launchd, the kernel, the device, or a network path was observed successfully.
