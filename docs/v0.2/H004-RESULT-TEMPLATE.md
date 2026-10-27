# H004 — Phase 0 Inspection Result Template

**This is a blank worksheet, not device evidence.** Fill it only during a separately authorized, attended inspection. Do not prefill an observation from H003, CI, a simulation, or memory.

H004 disposition is limited to `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `INCOMPLETE`, `STOPPED`, or `OBSERVATIONS_RECORDED_REVIEW_PENDING`. It has no `PASS` or `DEVICE_VERIFIED` value. This worksheet does not satisfy the P009 v1 session schema or create P009 acceptance.

## Session

| Field | Observed value |
|---|---|
| Session ID (`H004-YYYYMMDDThhmmssZ-<short-random-suffix>`) |  |
| H004 disposition | `NOT_STARTED` |
| Scope approval: approver/reference and UTC time |  |
| Operator attendance confirmation/source class |  |
| Other observer and role/source class, if any |  |
| Device inspection start UTC / end UTC |  |
| Device timebase ID and source |  |
| Device clock uncertainty (ms or `UNKNOWN`) |  |
| Host/observer timebase ID and source |  |
| Host/observer clock uncertainty (ms or `UNKNOWN`) |  |
| Clock relationship (`KNOWN` with basis / `UNKNOWN`) |  |
| Independent physical recovery method (no credentials) |  |
| Recovery method present and available confirmation/source class |  |
| Power and charging condition, direct observation |  |
| Evidence destination and access-control confirmation |  |

## Device identity and package state

| Observation | Result or `UNAVAILABLE` / `UNKNOWN` | Source, UTC, timebase, uncertainty, output reference |
|---|---|---|
| Actual model identifier |  |  |
| Actual iOS version |  |  |
| Kernel/platform string |  |  |
| Effective UID / rootful bootstrap evidence |  |  |
| Debian architecture |  |  |
| Package database status/version/architecture |  |  |
| `dpkg --audit` result and exit code |  |  |
| H005 dpkg technical shape-check result (does not accept exception) |  |  |
| Independent human dpkg exception decision, reviewer and capture hashes |  |  |
| Existing CLI path/type/owner/mode |  |  |
| Existing daemon path/type/owner/mode |  |  |
| Existing `ic` path/type/target |  |  |
| Existing manager path/type/owner/mode |  |  |
| Installed CLI SHA-256 |  |  |
| Installed daemon SHA-256 |  |  |
| Installed manager SHA-256 |  |  |
| Canonical H003 host stable-package SHA-256 reference (not measured on device: `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c`) |  |  |

Do not attribute H003 signer/profile identities to the device. The host-only receipt values are signer `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c` and profile `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca`.

## Runtime, recovery, policy, and evidence observations

| Observation | Result or `UNAVAILABLE` / `UNKNOWN` | Source, UTC, timebase, uncertainty, output reference |
|---|---|---|
| Relevant process rows and owners |  |  |
| Socket type/owner/mode/link metadata |  |  |
| Lock type/owner/mode/link metadata |  |  |
| Active advisory lock ownership, if safely observable; otherwise `UNKNOWN` |  |  |
| Staged launchd plist presence/hash/syntax |  |  |
| Live launchd plist presence/hash/syntax |  |  |
| Launchd label registration |  |  |
| Assertion state and owner, if safely observable |  |  |
| Driver assertion source completeness and registry summary/details |  |  |
| Process assertion source availability/completeness and owner mapping |  |  |
| P014 journal presence/owner/mode/size/mtime |  |  |
| P014 read-only recovery status and blocker |  |  |
| P015 Server Mode policy version/validity/explanation |  |  |
| P017 schedule storage/validation/count/diagnostics |  |  |
| P016 health sources and battery availability |  |  |
| P016 thermal availability |  |  |
| Project log paths and metadata (no raw log content) |  |  |
| P018 evidence status/inventory/validation availability |  |  |
| Root and `/var` free storage |  |  |
| Memory/resource snapshot and limitations |  |  |
| Before/after state-change observation |  |  |

## Command and file record

| Seq. | UTC / timebase / uncertainty | Exact command and path | Exit code or signal | Source class | Raw output reference | Sanitized reference and SHA-256 |
|---:|---|---|---:|---|---|---|
|  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |

| File ID | Host/device | Relative private path | Size | SHA-256 | Contents/privacy review |
|---|---|---|---:|---|---|
|  |  |  |  |  |  |

## Unknowns, unavailable fields, and stop events

| State | Field/command | Exact observation or reason | UTC / timebase / uncertainty | Output reference |
|---|---|---|---|---|
| `UNAVAILABLE` / `UNKNOWN` / stop |  |  |  |  |

Stop-condition event: `NONE OBSERVED` may be entered only after the operator has reviewed every stop condition; otherwise record the exact event. Do not use an empty table to imply that no stop condition occurred.

## Human review and disposition

- Raw evidence preserved privately at reference: `________________________________`
- Sanitized derivative privacy-reviewed by / UTC: `________________________________`
- Independent reviewer / review reference / UTC: `________________________________`
- P009 mapping, if any, uses only existing event semantics: `________________________________`
- H004 disposition: `NOT_STARTED | IN_PROGRESS | BLOCKED | INCOMPLETE | STOPPED | OBSERVATIONS_RECORDED_REVIEW_PENDING`
- Unresolved blockers and unknown ownership/recovery state: `________________________________`
- Separately authorized next action, if any: `NONE | P011 scope review pending | other written authorization reference: __________`

Do not write `PASS`, `DEVICE_VERIFIED`, `P011_ACCEPTED`, `P019_ACCEPTED`, or `RELEASE_READY` in this worksheet. H003, CI, hash validity, and manually entered values cannot assign those results.
