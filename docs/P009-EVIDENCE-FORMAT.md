# P009 — Evidence Format

The primary schema is [device-acceptance-v1.schema.json](schemas/device-acceptance-v1.schema.json). It references the existing P006 [connectivity-evidence-v1.schema.json](schemas/connectivity-evidence-v1.schema.json) so the documented LAN/Tailscale shape remains compatible. The validator applies the schemas offline and then checks cross-field and timeline rules.

## Package layout

```text
evidence-session/
├── session.json
├── manifest.json
└── evidence/
    ├── observer-log.txt
    └── operator-notes.json
```

Start with [the session template](templates/device-acceptance-v1.template.json), replace all example values, and put supporting files under `evidence/`. The template's zero hashes and sample timestamps are placeholders, not evidence. The session records:

- Schema version, session ID, P008/P009 source commit, build ID, package identifier/version, and package/binary SHA-256 values.
- Device model, iOS version, bootstrap, origin classification, and the operator's physical-presence statement.
- Session and trial bounds, attendance, clock source and uncertainty.
- Timestamped observations with event ID, sequence, source class, timebase, uncertainty, and event-specific details.
- Cleanup outcome, unresolved conditions, evidence file references, and a claimed review state.

Source classes are `SIMULATED`, `MOCK`, `CI`, `DEVICE_REPORTED`, `EXTERNAL_OBSERVER`, and `OPERATOR_RECORDED`. The first three are never accepted as physical-device evidence. Physical classifications are still claims that require human provenance review.

## Events and clocks

Observation event types include preflight, package integrity/signature/install/removal/rollback, daemon launch/exit, assertion acquire attempt/success/failure, hold active, screen lock/unlock, LAN and Tailscale observations, STOP, natural expiry, assertion release, SIGTERM, physical recovery, battery/thermal observations, and scheduled wake observation.

Each event has a UTC-offset date-time, a `timebase_id`, and `uncertainty_ms`; the session clock uncertainty is applied as a conservative lower bound. Replay compares order only within a shared timebase. It does not infer that the iPad clock and an independent observer clock agree. Cross-timebase ordering remains uncertain unless evidence explicitly associates an observation with the same `trial_id`.

LAN and Tailscale events are separate. A LAN record needs TCP/22 reachability, an authenticated SSH result, address, latency, independent-observer timestamp, operator-confirmed locked-screen state, and trial association. `screen_lock_event_id` links the observer record to the operator's `SCREEN_LOCK` event. Tailscale uses its tailnet address, peer result, direct/relay/unknown path, authenticated SSH result, latency, time, screen state, and trial association. A connected peer or reachable port without authenticated SSH does not pass either path. One path never substitutes for the other.

## Deterministic manifest

`manifest.json` covers `session.json` and every attachment; it does not list itself, which avoids a circular hash. Entries are sorted by relative path and contain file ID, size, and lowercase SHA-256. The session repeats attachment IDs, paths, sizes, media types, and hashes. The validator requires exact coverage with no additional files.

To stage a package, create a valid `session.json`, place attachments under `evidence/`, then run:

```sh
python3 scripts/p009_evidence.py manifest /path/to/staged-evidence
```

The builder hashes all attachments and atomically writes the updated session and manifest. When changing a previously manifested package, inspect the staged files and explicitly rebuild:

```sh
python3 scripts/p009_evidence.py manifest /path/to/staged-evidence --replace
```

Validation rejects unsupported schema versions, malformed JSON, duplicate JSON keys, unsafe relative paths, path traversal, symlinks, special files, missing or unexpected files, duplicate IDs, size-limit violations, bad hashes, and credential-like fields or material. Evidence files are limited to 2 MiB each and 16 MiB total; a session has a 2 MiB limit. Hashes establish consistency only, not truth or provenance.

## P006 compatibility

An optional `connectivity_evidence` value may preserve the P006 version 1 object with separate `lan` and `tailscale` records. The adapter records that legacy shape as operator-recorded evidence. Because P006 did not classify each observation's source, the adapter will not treat legacy data as an independent observer result or silently promote it to a hardware PASS.

## Credentials and privacy

Never include passwords, SSH keys, Tailscale keys/tokens, private files, or credentials. Do not capture command lines containing secrets. The validator rejects common secret field names and recognizable private-key/token material. Reports omit arbitrary event details and do not reproduce attachment contents.
