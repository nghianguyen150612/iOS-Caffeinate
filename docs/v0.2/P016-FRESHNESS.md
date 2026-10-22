# P016 — Freshness and Timebases

The default sampling model is on demand. There is no cached sample, persistent telemetry record, timer, or background poll. Default freshness limit is 300 seconds. The API accepts research/policy limits from 1 through 3600 seconds; values outside that range are rejected.

Each acquired value records wall-clock UTC seconds, boot-scoped monotonic nanoseconds when available, a timebase identity, and clock uncertainty. On the target, `mach_continuous_time()` is the monotonic clock because it advances during sleep. `KERN_BOOTTIME` scopes the value to a boot when the read succeeds. If the boot identity cannot be read, the ID remains `UNKNOWN`; P016 never reuses a fixed placeholder as though it identified one boot. These reads are not yet runtime-verified on the reference iPad.

Freshness is computed conservatively:

- `CURRENT`: the upper bound on observation age, including declared clock uncertainty, is within the limit.
- `STALE`: the lower bound on age exceeds the limit.
- `UNKNOWN`: timestamps are missing, in the future beyond uncertainty, use conflicting boot identities, or have a monotonic rollback; uncertainty overlaps the limit.

When the same timebase is available, age comes from monotonic time. A wall-clock rollback never makes an older observation current. If monotonic identity is unavailable, bounded UTC age is used; a future UTC stamp is never evidence of freshness. Timestamps from different boots are never compared as one monotonic clock.

Unavailable measurements have no current sensor value. The CLI refreshes freshness from the same command's clock sample and displays age and uncertainty. It does not persist or reuse expired telemetry. No API caller can use an arbitrarily large age limit to promote historical readings to `CURRENT`.
