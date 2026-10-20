# P012 — Preregistered experiment protocol

The versioned protocol is [protocol-v1.json](../../experiments/p012/protocol-v1.json), with its format in [protocol-v1.schema.json](../../experiments/p012/protocol-v1.schema.json) and the trial record contract in [trial-record-v1.schema.json](../../experiments/p012/trial-record-v1.schema.json). Protocol v1 was recorded on 2026-10-20 before any P012 hardware data. It is a proposal for later supervised work; it does not authorize hardware testing.

## Fixed conditions

| Condition | Daemon | iOS-Caffeinate assertion | Required interpretation |
|---|---|---|---|
| A — Baseline | STOPPED | INACTIVE | Confirm no daemon-owned assertion. This does not claim that every iOS system assertion is absent. |
| B — Daemon-only | RUNNING, reports IDLE | INACTIVE | Isolates daemon availability without an active iOS-Caffeinate assertion. |
| C — Active hold | RUNNING | ACTIVE, bounded | Operator starts a 180-second hold; probe is completed before expiry. Actual acquisition and release are recorded. The absolute ceiling is 300 seconds. |
| D — Post-expiry | RUNNING, reports IDLE | EXPIRED/RELEASED and confirmed | Confirm the daemon no longer owns an assertion before quiet time. D is not treated as A. |

## Quiet intervals, probes, and order

The initial quiet interval is 120 seconds. The reviewed protocol permits a value from 60 through 180 seconds; any selected value is written into the trial and compared explicitly. No incoming SSH probes or operator interactions are allowed during the quiet interval. A missing or contaminated interval is retained as incomplete or invalid data.

One trial observes one route and runs at most one SSH command (`true`) with `BatchMode=yes`, one connection attempt, existing host-key verification, and an eight-second default timeout (15-second maximum). A timeout, refusal, authentication rejection, host-key failure, transport failure, command failure, or interruption is an outcome. The host does not retry.

The exploratory matrix has three repetitions for each of four conditions and two routes: 24 manually started probe trials. LAN and Tailscale trials have separate quiet intervals. The two route trials in one condition/repetition pair share a sanitized `pair_id` and have distinct `trial_id` values. Route order by repetition is LAN/Tailscale, Tailscale/LAN, LAN/Tailscale. Condition order is A/B/C/D, B/D/A/C, C/A/D/B. The fixed order is counterbalanced, not randomized; the analyzer records order and possible carryover. It does not automate a series of device trials.

The small, single-device design is exploratory. The analyzer does not calculate confidence intervals or significance under an independence assumption. Three repetitions do not establish statistical proof or production reliability.

## Required controls and observations

For every trial, record:

- Operator presence and direct physical recovery availability.
- P011 package preflight, separately authorized installation, installed CLI/daemon execution, and assertion acquire/release cleanup prerequisites.
- Screen lock state and observation time; charging state; battery percentage; thermal observation.
- Wi-Fi association and a sanitized Wi-Fi profile label; LAN and Tailscale route state.
- Daemon and daemon-owned assertion states, plus actual acquire/release results and timestamps for C/D.
- Quiet interval duration, start/end, incoming-probe count, and operator-interaction count.
- Probe order, condition order, route, host monotonic elapsed time, UTC timestamps, observer timebase, and timing uncertainty.
- Elapsed time since the prior trial and any reboot/respring or other interaction.

Unknown values remain unknown. The operator must not infer absence of unrelated iOS assertions from the daemon state. To classify the Condition C probe as preceding release, the host probe and device-reported release must use the same declared UTC timebase with both uncertainties recorded. If their timebases differ, the temporal relation remains inconclusive; the analyzer must not infer order from timestamps alone.

## Inclusion, exclusion, and stop rules

Include a trial only when the selected condition, screen lock, quiet period, operator presence, recovery path, battery/thermal review, Wi-Fi, route, daemon state, assertion state, and probe identity are recorded. C requires a successful confirmed acquisition and successful release within its registered bound; the probe must precede confirmed release/expiry. D requires release/expiry confirmation before its quiet interval.

Record invalid or incomplete trials rather than deleting them. Exclude them from valid comparison counts, but retain their probe result and reason in the report. A missing probe, interrupted command, or uncertain cleanup is not converted into success.

Stop if the operator cannot confirm the screen state, the device becomes unexpectedly hot, battery falls below the operator-approved threshold, release fails, host identity changes, recovery becomes unavailable, the approved time limit is exceeded, or a prior trial leaves uncertain daemon/assertion state. Do not attempt automatic physical recovery.

## Hardware gate

P012 device experiments require P011 stable-package preflight PASS, separately authorized installation, installed CLI/daemon verification, confirmed acquire/release cleanup, direct recovery independent of SSH/Tailscale, physical operator presence, and battery/thermal review. P011 physical acceptance is pending. The known `ldid` provenance blocker remains in force; P012 does not substitute another signer or claim package acceptance. See [P011 validation](P011-VALIDATION.md).
