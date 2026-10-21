# P019 Preregistered Experiment Protocol v1

The preregistered source is [protocol-v1.json](../../experiments/p019/protocol-v1.json), validated by [protocol-v1.schema.json](../../experiments/p019/protocol-v1.schema.json). It was fixed before P019 hardware measurements. No P019 hardware measurements have been collected.

Target: iPad mini 2 A1489 / `iPad4,4`, Apple A7 ARM64, iOS 12.5.7, Amethyst/Procursus rootful.

## Fixed plan

P019 reuses P012 v1 without changing its trial definitions:

- Conditions A (daemon stopped), B (daemon idle), C (one active bounded assertion), and D (confirmed expired/released).
- Initial quiet interval 120 seconds; P012 permits 60–180 seconds when the selected duration is recorded. No incoming probe or operator interaction during quiet time.
- Proposed active hold 180 seconds, maximum 300 seconds. One route and at most one SSH probe per trial; eight-second default timeout, 15-second ceiling; no retry.
- Three repetitions per condition per route, 24 planned probe trials. Preserve the registered condition and route orders. Keep LAN and Tailscale separate.
- Repeat bounded reliability plan: 3 attended periods on separate calendar dates, 4 manually started cycles per period, 12 total. Target 180-second hold, hard maximum 300 seconds, at least 300 seconds of unasserted rest between cycles. No automated runner or overnight execution.

The sample plan is a recurrence and cleanup consistency screen. It is not a reliability-rate estimate. P012’s 24 trials are exploratory and clustered on one device. A finite successful sample does not establish 24/7 reliability.

## Measurement and inclusion

Record exact source/build/package/binary/profile/signer identity, installed path hashes, previous rollback artifact, operator attendance, independent recovery readiness, phase and trial IDs, condition/order/route, screen state, daemon and assertion state, acquisition/release, quiet interval, probe result and latency, battery/charging/thermal availability, Wi-Fi and route state, timebase IDs, UTC timestamps, monotonic elapsed values when available, uncertainty, rest, carryover, reboot/respring, and deviations.

Use device observations, independent Arch/Linux host observations, operator confirmations, and CI/mock results as separate source classes. Do not compare unrelated monotonic clocks. Cross-device event order is inconclusive unless both clocks are reconciled with uncertainty. A probe after a requested assertion does not establish that the probe occurred while the assertion remained active.

P012 inclusion and exclusion rules remain authoritative for its records. Unknown or contradictory states, contaminated quiet intervals, duplicate cells, mismatched route/order, unconfirmed release, host-key failure, or unresolved clocks are retained with their actual outcome and excluded only from comparisons they invalidate.

## Revision control

After collection begins, v1 is immutable. A future change requires a new protocol version with a UTC timestamp, reason, reviewer, superseded version, and affected trial definitions. Do not change trial definitions retroactively to make results pass. No schema or event meaning in P009 v1 is changed by this protocol.
