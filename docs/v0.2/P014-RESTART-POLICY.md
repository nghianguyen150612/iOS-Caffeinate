# P014 — Restart Policy

The policy engine is pure C11 and deterministic. It accepts versioned observations, recovery metadata, and a caller-supplied monotonic clock identity. It returns a state, decision, delay, remaining budget, and blocker reason. It does not invoke launchctl or start a process.

| Limit | Default |
|---|---:|
| Attempts in the rolling window | 3 |
| Rolling window | 10 minutes |
| Backoff before attempt 1 | 5 seconds |
| Backoff before attempt 2 | 15 seconds |
| Backoff before attempt 3 | 60 seconds |
| Healthy interval before clearing attempt history | 30 minutes |

An attempt is appended and persisted before an adapter could attempt an operation. Event IDs are monotonically increasing inside a recovery generation; duplicate or older events are idempotent. Attempt timestamps older than ten minutes are removed only when the current monotonic timestamp and clock identity reconcile safely.

Backoff and rolling-window calculations use monotonic nanoseconds. Wall time is retained for diagnostics but does not control delay. A clock identity change, missing identity, monotonic rollback, stale timestamp, or reboot ambiguity returns `RECOVERY_UNVERIFIED`. Time passing alone never clears unresolved cleanup or ownership uncertainty.

Attempt history resets only after a confirmed 30-minute healthy interval on the same monotonic identity, or after the explicit operator-reviewed recovery operation. The operator command is separate from service retries and has no automatic launchd action. P014 does not ship a restart supervisor, so status reports automatic runtime recovery as disabled even when the policy result is eligible for attended start.

Manual start and automatic recovery remain separate decisions. P013 service start/restart are still disabled pending iOS 12 compatibility evidence. Assertion requests are refused by the daemon while its durable cleanup gate is unresolved.
