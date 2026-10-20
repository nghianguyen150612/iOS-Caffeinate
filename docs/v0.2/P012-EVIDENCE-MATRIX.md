# P012 — Evidence matrix

P012 raw records and P009 acceptance sessions have different jobs. P012 captures route-specific trial context and comparisons. P009 remains the authority for installation, assertion lifecycle evidence, physical recovery, and human-reviewed hardware acceptance.

| Claim or control | P012 evidence | P009 v1 mapping | Current status |
|---|---|---|---|
| A/B/C/D daemon/assertion condition | Operator-recorded condition and state fields | Existing daemon/assertion events only when explicitly timestamped; no new event semantics | Not measured in P012 |
| Locked display during measurement | Explicit operator status and observation time | `SCREEN_LOCK` only when explicitly timestamped and operator-confirmed | Existing October 18 report is operator-reported and awaits P009 review |
| Quiet interval had no probes/interactions | Start/end, counts, contamination marker | Not representable in P009 v1 | Not measured in P012 |
| LAN authenticated SSH | One host result and timing record | `LAN_OBSERVATION` proposal; address omitted; TCP is unknown except explicit result mapping | No controlled P012 trial |
| Tailscale authenticated SSH | One separate host result and timing record | `TAILSCALE_OBSERVATION` proposal; peer status/path remain unknown unless separately recorded in P009 | No controlled P012 trial |
| Assertion acquire/release | Actual operator/device-reported timestamps and results | Existing `ASSERTION_ACQUIRE_*`, `ASSERTION_RELEASE`, or `NATURAL_EXPIRY` only with supplied times | Existing operator report is not a controlled baseline |
| Battery/thermal/Wi-Fi/charging/carryover | P012 state fields and confirmation source | Battery/thermal event proposals where timestamped; Wi-Fi/charging/carryover are P012-only | Not measured in P012 |
| Physical recovery and package acceptance | Prerequisite confirmations only; no automatic claims | Must be supported by actual P009 physical events and review | P011 physical acceptance pending |
| OS suspend/deep sleep or scheduled wake | Not inferred from SSH or assertion API | No P012 v1 event represents an inferred sleep state | Not established / scheduled wake remains unverified |
| Long-duration server reliability | Not established by sparse point samples | P019 evidence required | Not validated |

## Existing operator-reported observations

The October 18, 2026 reports (native CLI, foreground daemon, IOKit lifecycle, 30-second expiry, STOP, SIGTERM cleanup, LAN 24/24, Tailscale 24/24, locked display, and the approximate 180-second assertion timestamps) remain `OPERATOR_RECORDED` pending P009 review. They used manually staged binaries, lack an A baseline, include potentially wake-inducing SSH activity, and do not represent an installed stable package. P012 must not copy those times or upgrade their evidence class.

## Mapping rules

- Reuse only source classes and event types accepted by P009 v1.
- Emit a candidate P009 event only from a supplied, explicit timestamp and observed value. Never invent screen-lock, assertion, battery, thermal, recovery, hash, or clock data.
- Preserve host SSH samples as `EXTERNAL_OBSERVER` proposals and manual states as `OPERATOR_RECORDED` proposals.
- Do not generate a complete P009 session or acceptance decision from a P012 trial.
- Do not represent `peer_connected=true` from a successful SSH command. Do not treat unknown TCP/peer fields as false.
- Keep raw P012 JSON, any P009 event proposal, and P009 human review status clearly separate.

The P009 v1 validator accepts the mapped event structures in deterministic tests. That compatibility check establishes format interoperability only; it does not establish physical provenance or pass a hardware gate.
