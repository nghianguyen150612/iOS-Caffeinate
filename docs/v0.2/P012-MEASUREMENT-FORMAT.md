# P012 — Measurement and evidence format

P012 raw records use [trial-record-v1.schema.json](../../experiments/p012/trial-record-v1.schema.json). The standalone host probe emits a `probe_version: 1` object with a deliberately small, sanitized field set. These JSON records are not a P009 acceptance package.

## Host probe output

The host output records trial/condition/repetition IDs, route, a sanitized `target_id`, exact result and authentication classification, SSH exit code when available, UTC start/end, monotonic elapsed milliseconds, wall-clock elapsed milliseconds, timeout, quiet interval, operator-confirmed screen state, operator/P011/recovery/safety confirmations, observer timebase, and uncertainty. The operator destination is never serialized.

Result values are:

| Result | Meaning |
|---|---|
| `AUTHENTICATED_SUCCESS` | SSH authenticated and remote `true` returned exit code 0. |
| `AUTHENTICATION_FAILURE` | SSH explicitly reported authentication rejection. |
| `PROBE_TIMEOUT` | Client or connection timed out before a completed command. |
| `CONNECTION_REFUSED` | SSH reported a refused connection. |
| `HOST_KEY_FAILURE` | Existing host-key verification rejected or could not match the host. |
| `TRANSPORT_ERROR` | Other recognized network/SSH transport failure. |
| `REMOTE_COMMAND_FAILURE` | SSH authenticated, but the minimal command returned nonzero. |
| `SSH_CLIENT_MISSING` | Host did not have the SSH client available. |
| `INTERRUPTED` | The probe was interrupted; no assertion cleanup is inferred. |

Raw stderr, authentication debug logs, passwords, keys, tokens, destination addresses, and unrelated files are not recorded. The client uses `BatchMode=yes`, one connection attempt, a bounded timeout, `StrictHostKeyChecking=yes`, and the existing host trust database. It never enables password automation or disables host-key checks.

## Trial record

One record represents one condition and one route. Its main fields cover:

- `trial_id`, `pair_id`, `repetition`, `condition_id`, `route`, condition/route order, and `evidence_origin`.
- Operator/device timebases and uncertainty; trial and probe UTC times.
- `state`: screen lock, charging, battery, thermal, Wi-Fi association/profile label, LAN/Tailscale route state, daemon state, assertion state and actual acquire/release outcomes, quiet interval, probe/interactions during quiet, elapsed time since the previous trial, and reboot/respring state.
- `operator_confirmations`: operator presence, direct recovery, P011 preflight, separate install authorization, installed runtime, assertion cleanup, battery/thermal safety, locked screen, Wi-Fi, route, daemon/assertion state, and counterbalance order.
- One `probe` object or `null`; interruption state and a sanitized interruption code.

The top-level observer clock metadata must agree with the nested host-probe metadata. Cross-clock event ordering is accepted only when both observations identify the same timebase and record uncertainty; otherwise Condition C probe-before-release ordering remains incomplete. A UTC rendering by itself does not prove that two clocks were synchronized.

The controller uses `VALID`, `INVALID`, `INCOMPLETE`, and `INTERRUPTED` as derived trial-review states. These are not empirical acceptance decisions. The host tool cannot infer a screen lock or assertion state, and script exit does not establish assertion cleanup.

Records use P009 source classes: `SIMULATED`, `MOCK`, `CI`, `DEVICE_REPORTED`, `EXTERNAL_OBSERVER`, and `OPERATOR_RECORDED`. CI fixtures are always `SIMULATED`; physical state confirmations remain operator-reported until human review. P012 writes atomically with exclusive-create semantics and rejects duplicate JSON keys, unsafe identifiers, symlinks, secret-like fields/values, and unknown fields.

## P009 mapping

`p012_trial.py map-p009` emits event proposals only, using existing P009 v1 event types such as `SCREEN_LOCK`, `ASSERTION_ACQUIRE_SUCCESS`, `ASSERTION_RELEASE`/`NATURAL_EXPIRY`, `LAN_OBSERVATION`, `TAILSCALE_OBSERVATION`, `BATTERY_OBSERVATION`, and `THERMAL_OBSERVATION`. It emits an event only when the P012 record contains an explicit timestamp and state observation. It does not generate a complete P009 session, file hash, physical recovery event, or acceptance decision.

For SSH-only observations, the LAN TCP field is true only when the SSH result establishes a service connection, false only on an explicit refusal, and otherwise `null`. P012 does not query a Tailscale peer-status API, so `peer_connected` remains `null`; authenticated SSH is recorded separately. No destination address is copied into P009 event proposals.

P009 v1 cannot represent P012 quiet-period contamination, condition/route order, pairing, charging state, Wi-Fi association, daemon-only effect, trial validity, or all timing uncertainty relationships. Keep those fields in P012 raw records. Do not change P009 event meanings to make P012 data pass. Human review remains mandatory for hardware claims.
