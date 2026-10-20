# P015 — Server Policy Schema

The persistent policy remains `/var/lib/ioscaffeinate/server-mode.json`. P006 version 1 is retained exactly. Version 2 requires an exact schema with no unknown or duplicate keys.

```json
{
  "version": 2,
  "policy": "bounded_session",
  "session": {
    "max_duration_seconds": 300,
    "require_operator_confirmation": true,
    "allow_automatic_start": false,
    "allow_restart_resume": false
  }
}
```

`policy` is `disabled`, `observe_only`, or `bounded_session`. A v2 `session` object is required for every policy value and contains exactly the four shown fields. `max_duration_seconds` is an integer from 1 through 300. Confirmation must be `true`; automatic start and restart resume must be `false`. A policy that asks for any of those prohibited behaviors is invalid.

The loader rejects unsupported versions, duplicate keys, unknown fields, malformed or truncated input, trailing data, non-integer durations, integer overflow, invalid booleans, symlink traversal, hard links, unsafe directories, wrong ownership or mode, and files larger than 512 bytes. Invalid configuration fails closed.

The accepted JSON uses ASCII field names and enum values. Escaped strings are not needed by this schema and are rejected by the small strict parser. No secret, address, executable path, command, or extension property is accepted.

The evaluator's evidence inputs are separate from this policy file. Each input carries a P009 source class, current/stale/unknown freshness, observation timestamp, confidence, and review status. `OPERATOR_RECORDED` input remains that source class and cannot pass without separate P009 review. The configuration cannot set evidence values.

## Version 1 compatibility

```json
{"version":1,"policy":"disabled"}
```

Version 1 `disabled` remains disabled and `observe_only` remains read-only observation. Version 1 cannot select `bounded_session`; no config load or diagnostic migrates a file. Missing configuration resolves to disabled.

The v2 validator does not grant execution authority. `allow_automatic_start` and `allow_restart_resume` are present to make the prohibited behavior explicit and must remain false.
