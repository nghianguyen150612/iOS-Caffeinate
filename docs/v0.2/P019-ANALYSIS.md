# P019 Reliability Analysis

`scripts/p019_session.py analyze` and `report` are deterministic offline summaries. The P012 host probe and analyzer remain the only SSH engine and A/B/C/D comparison authority. P019 transforms neither raw observations nor the P012 protocol.

## Reported denominators

Every report includes 24 planned P012 probe trials and the actual attempted, valid, invalid, incomplete, and interrupted counts. It also reports the 12 planned bounded cycles, successful bounded holds, confirmed endurance-cycle releases, separate P012 release confirmations, release failures, unexpected daemon exits/restarts, cleanup blockers, protocol deviations, missing P009 event purposes, and remaining gates. A cycle cannot count as a successful bounded hold when its measured duration has no timebase or uncertainty record.

LAN and Tailscale each receive independent attempt and outcome counts. Authenticated SSH successes, failures, failure categories, and successful host-monotonic latency summaries include `n`, median, quartiles, minimum, and maximum. Failed probes remain outcomes; a port or peer connection without authenticated SSH is not success.

Resource summary distinguishes P016 API availability from operator observations. Charging categories are reported without filling unknown fields. Aggregate supervised observation time sums individually attended sessions; it is not represented as one continuous uptime interval.

## Comparisons and limits

Preserve P012 A/C, B/C, and C/D comparisons separately for LAN and Tailscale. Three repetitions per condition and route are exploratory, not statistically significant. The analyzer makes no confidence interval or independent Bernoulli assumption. It does not infer causal sleep prevention, OS suspend, deep sleep, or 24/7 availability.

Missing, duplicate, invalid, or interrupted trials remain visible. If timebases disagree, quiet windows are contaminated, clock order cannot establish a C probe before release, or resource/carryover conditions confound a comparison, report `INCONCLUSIVE`. Do not delete an inconvenient outcome or redefine v1 trial rules.

The initial 12-cycle plan checks recurrence and cleanup consistency across three dates. It cannot estimate rare failure probability. A zero-failure short observation does not guarantee later uptime.
