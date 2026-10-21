# P019 Observation Format

P019 session records are defined by [session-v1.schema.json](../../experiments/p019/session-v1.schema.json); result records use [acceptance-result-v1.schema.json](../../experiments/p019/acceptance-result-v1.schema.json). P012 trial records are embedded without altering their v1 schema. P009 raw package schemas remain unchanged.

## Identity and clocks

Each session binds the preregistered protocol digest, exact P019 tooling source commit, session ID, current phase, evidence class, candidate provenance, prerequisite gates, operator attendance/recovery, P012 trial records, repeated bounded cycles, P009 package hashes/event references, P018 manifest hash, independent review, incidents, and deviations. P019 cycle, resource, incident, deviation, and operator-confirmation records carry a source class, UTC timestamp, timebase identity, and uncertainty field. A null uncertainty stays unknown; the host confirmation helper uses `host-clock-unreconciled` and leaves uncertainty null. Cycle records keep observer and device timebases separate and bind measured duration to the selected timebase. The validator does not compare unrelated monotonic clocks.

Every event or observation records UTC time, source class, timebase identity, and timestamp uncertainty. Record monotonic elapsed time and boot/timebase identity when available. Never compare unrelated monotonic clocks. If host and device time cannot be reconciled, cross-device ordering remains inconclusive. `DEVICE_REPORTED`, `EXTERNAL_OBSERVER`, and `OPERATOR_RECORDED` remain distinct. `SIMULATED`, `MOCK`, and `CI` remain synthetic.

## P009 v1 mapping

P019 references actual P009 event IDs without changing their meanings:

| P019 purpose | P009 v1 event |
|---|---|
| Package preflight | `DEVICE_PREFLIGHT` |
| Package integrity/signature/install | `PACKAGE_INTEGRITY_CHECK`, `SIGNATURE_ACCEPTANCE`, `PACKAGE_INSTALL` |
| Daemon lifecycle | `DAEMON_LAUNCH`, `DAEMON_EXIT`, `EXPLICIT_STOP` or `SIGTERM` where applicable |
| Assertion | `ASSERTION_ACQUIRE_ATTEMPT`, `ASSERTION_ACQUIRE_SUCCESS`, `HOLD_ACTIVE`, `ASSERTION_RELEASE`, `NATURAL_EXPIRY` |
| Screen and route | `SCREEN_LOCK`, `SCREEN_UNLOCK`, `LAN_OBSERVATION`, `TAILSCALE_OBSERVATION` |
| Resources and recovery | `BATTERY_OBSERVATION`, `THERMAL_OBSERVATION`, `PHYSICAL_RECOVERY` |

P009 v1 does not encode every P019 period/cycle number, charging-state category, interruption reason, quiet-interval contamination, or trial-validity decision. P019 keeps these in its versioned session and P012 record. If a required state cannot be represented without changing an existing P009 meaning, publish a versioned extension proposal before collection.

## Resource values

Use `UNAVAILABLE` with a null value when P016 does not provide a reading. Do not use zero, 100%, or nominal temperature as a substitute. Store API readings and operator observations separately. Visual battery percentage is not calibrated battery health. Absence of a thermal alert does not prove a safe unattended envelope.

## Privacy

Keep raw addresses, device identifiers, assertion IDs, credentials, SSH keys, Tailscale tokens, and raw debug logs out of CI artifacts. Preserve original raw P009 evidence securely. A P018 derivative may omit sensitive fields and must be separately reviewed; it cannot alone prove every raw observation.
