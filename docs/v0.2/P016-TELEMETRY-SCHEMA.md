# P016 — Telemetry Schema

The native snapshot is schema version `1`. It is an in-memory C structure, not a persistent JSON record. CLI output is a stable key/value projection. P016 does not write routine measurements to disk.

## Snapshot fields

| Field | Type | Unknown representation |
|---|---|---|
| `schema_version` | unsigned integer | Must equal `1` |
| `battery_percentage` | integer, 0–100 | `-1` internally; `UNAVAILABLE` in CLI output |
| `charging_state` | enum: `CHARGING`, `DISCHARGING`, `FULL`, `UNKNOWN` | `UNKNOWN` |
| `thermal_state` | enum: `NOMINAL`, `ELEVATED`, `CRITICAL`, `UNKNOWN` | `UNKNOWN` |
| `thermal_raw_state` | platform category | `UNKNOWN` |
| `device_uptime_seconds` | unsigned seconds | `UNAVAILABLE` in CLI output |
| Each observation metadata value | status, source, times, freshness, confidence, review flags | `UNAVAILABLE` or `UNKNOWN` per field |

Each field carries `status`, `source`, `source_class`, source detection, acquisition, value validity, UTC observation time, monotonic observation time, timebase identity, clock uncertainty, age, freshness, confidence, physical-source verification, safety-review status, and P009 acceptance status.

Statuses are `AVAILABLE`, `UNAVAILABLE`, `INVALID`, `ERROR`, and `UNSUPPORTED`. Freshness is `CURRENT`, `STALE`, or `UNKNOWN`. Source classes are `DEVICE_REPORTED`, `EXTERNAL_OBSERVER`, `OPERATOR_RECORDED`, `MOCK`, `SIMULATED`, `CI`, or `UNKNOWN`.

Zero percent is a valid reading. Values outside 0–100 are rejected and are never clamped. `FULL` remains distinct from actively charging; P015 has no `FULL` enum, so its diagnostic adapter maps that state to `UNKNOWN`. Thermal categories are not temperatures. No Celsius value is reported.

## Validation and authority

The validator rejects invalid enums, booleans, source identifiers, percentages, timestamps below zero, and inconsistent validity metadata. It preserves raw platform thermal categories when normalization is supported. Unknown platform categories stay unavailable or unsupported; they never become nominal.

A valid observation is diagnostic data only. It does not imply a physically verified source, a reviewed safety interpretation, or accepted P009 evidence. The adapter never marks battery or thermal evidence `SERVER_EVIDENCE_PASS`.

P009 v1 already defines `BATTERY_OBSERVATION` and `THERMAL_OBSERVATION` event types. `scripts/p016_p009_adapter.py` converts one `ic health battery` or `ic health thermal` key/value snapshot into a P009 v1 event fragment. It emits only a valid, acquired, current observation with explicit confidence, UTC time, clock uncertainty, source class, and known timebase identity. It preserves source and review flags in `details`; it does not claim physical verification or P009 acceptance. Unavailable, stale, malformed, or timebase-unknown observations produce no event. The fragment is printed to stdout and is never written into a P009 session automatically.

Example syntax for a future qualifying observation source:

```sh
ic health battery | python3 scripts/p016_p009_adapter.py battery \
  --event-id p016-battery-01 --sequence 12 \
  --trial-id trial-01 --condition-id A --outside-quiet-interval
```

The P012 identifiers and operator assertion are copied into event details; the event timestamp remains the device observation time. This does not record an independent host observation, alter a preregistered trial, or bypass P009 review. Because launching the CLI can perturb device activity, P012 operators must capture before a quiet interval starts or after it ends; never run a telemetry command during the quiet interval. The CLI cannot independently verify the protocol schedule. Host mocks may be serialized as `MOCK` events for format testing, but P009 must continue to treat them as simulated evidence.

The current iOS adapter reports battery and thermal observations unavailable, so these commands return status `3` and emit no event on the target build today.

The optional CLI association is presentation context, not part of the native telemetry snapshot. It accepts a P012 `trial_id` matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and a condition ID `A`, `B`, `C`, or `D`. The command also requires `--outside-quiet-interval`; this is an operator assertion, not an interval sensor. Device timestamps/timebase remain on each observation, host-observer time remains separate, and no P012 record is written.
