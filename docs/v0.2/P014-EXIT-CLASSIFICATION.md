# P014 — Exit Classification Contract

The version 1 contract distinguishes process exit facts from assertion cleanup. `UNKNOWN_UNOBSERVED` is a real value and is not treated as success.

| Category | Required interpretation |
|---|---|
| `GRACEFUL_CONFIRMED` | Daemon reached its normal cleanup path and journaled a clean exit. No restart is requested. |
| `EXPLICIT_STOP` | Daemon accepted explicit `SHUTDOWN`; release acknowledgement and later process/socket observation are separate. No automatic restart. |
| `TIMED_EXPIRY_ONLY` | A bounded assertion expired; the daemon process did not exit. Not a crash. |
| `UNEXPECTED_EXIT` | External observer reported an exit that was not an explicit stop. Cleanup still needs evidence. |
| `SIGNAL_TERMINATION` | Signal number must be observed. SIGTERM/SIGINT handling is recorded by the daemon; SIGKILL is never graceful. |
| `STARTUP_FAILURE` | Startup failed; bounded retry is considered only after cleanup and supervisor checks. |
| `RELEASE_FAILURE` | Release returned an error. Blocks restart until reviewed cleanup. |
| `ASSERTION_OWNERSHIP_UNKNOWN` | Prior ownership cannot be established. Blocks restart. |
| `SUPERVISOR_STATUS_UNKNOWN` | No reliable supervisor exit/status result. Remains unverified. |
| `REPEATED_FAILURE` | A repeated failure contributes to the same three-attempt limit. |
| `OPERATOR_REVIEWED_CLEANUP` | Operator supplied a separate reviewed cleanup decision. This is not device evidence. |
| `UNKNOWN_UNOBSERVED` | No reliable cause or signal was available. Never infer graceful cleanup. |

The daemon cannot classify SIGKILL after it occurs. It leaves its durable process marker at `RUNNING`; the next process records an unobserved cause and blocks assertions. A stale socket or missing PID is not promoted to a release acknowledgement.
