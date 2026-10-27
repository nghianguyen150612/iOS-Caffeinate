# H004 — Evidence Guide

This guide applies to a real, separately authorized Phase 0 session. No H004 device observations have been collected by preparing these documents. The preliminary items in the [H005 acceptance handoff](H005-ACCEPTANCE-HANDOFF.md) and [R05 blocker matrix](R05-RELEASE-BLOCKER-MATRIX.md) are operator-reported only; they are not independently reviewed device evidence or raw command output. Host CI, simulations, H003 receipts, and manually typed worksheet values remain host-side or operator-recorded material; they are never represented as on-device command output.

## Session identity and clocks

- Use a unique, non-identifying session ID such as `H004-YYYYMMDDThhmmssZ-<short-random-suffix>`. Do not include serial number, UDID, Apple ID, phone number, or network address.
- Record UTC start/end timestamps and a separate timebase ID for the device clock and any observer/host clock. Include each clock's source, synchronization basis, and uncertainty. If uncertainty or clock relationship is unknown, leave it unknown; do not align timestamps by assumption.
- Record operator attendance confirmation and independent recovery confirmation as `OPERATOR_RECORDED`. Note the named local method and confirm that it does not depend on SSH/Tailscale or the project daemon. Do not record recovery credentials.
- Keep power/charging and direct visual observations separate from CLI/API telemetry.

## Commands and outputs

For each command actually entered, preserve:

- Sequence number, exact command text, executable path/hash when applicable, and shell/platform context.
- UTC timestamp, timebase ID, uncertainty, stdout reference, stderr reference, and actual exit code or terminating signal.
- Source class and observation source. Directly captured device output may be recorded as `DEVICE_REPORTED` with its capture path; a manually transcribed claim is `OPERATOR_RECORDED`; a distinct independent witness may be `EXTERNAL_OBSERVER`. These labels are provenance claims and still require human review.
- Sanitized derivative reference and SHA-256, when one is created. Keep the unmodified original in private evidence storage.
- `UNAVAILABLE` for a known absent/unsupported command or source; `UNKNOWN` when the state cannot safely be established. Include the reason without guessing a value.

Do not fabricate timestamps, command results, hashes, device identity, process state, assertion ownership, recovery state, exit codes, or output references. If execution fails or is terminated unexpectedly, capture the exact observation and apply the stop rule.

## Hashes and host receipts

Hash installed regular executables and any reviewed evidence files with SHA-256. Record the hash algorithm, utility and version/path, input path, file metadata, observed digest, and whether the object was on-device or host-side. For the stable package, compare against the canonical H003 receipt value `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c`; the signer and profile host identities are `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c` and `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca`. Those H003 values describe host receipts only. Do not copy them into fields that claim an installed device binary was measured.

P009 `manifest.json` may be built and validated offline on the host for a genuine P009 evidence package. Its sorted file hashes establish consistency, not truth, collection method, identity, or authenticity. Preserve the raw H004 worksheet separately: the P009 v1 session schema requires a trial record, so do not invent a trial or change event semantics to force a read-only inspection into that schema. Map observations only to existing P009 events when their meaning fits, then submit physical-source evidence for independent review.

## Privacy and storage

- Store raw output in a secure, access-restricted destination. Do not commit it, upload it to CI, include it in a pull request, or put it in a shared artifact.
- Raw process, launchd, evidence-inventory, and log metadata may reveal personal or system details. Keep raw files private; make a separately reviewed sanitized derivative with unnecessary addresses, identifiers, unrelated labels, credentials, and user data removed.
- Do not read or attach complete project log contents in Phase 0. Do not collect private keys, passwords, tokens, SSH/Tailscale configuration, assertion IDs, process environments, or unrelated application data.
- Keep genuine device output separate from host CI, mock, simulated, and operator-entered material. P009 source classes remain distinct: `DEVICE_REPORTED`, `EXTERNAL_OBSERVER`, `OPERATOR_RECORDED`, `SIMULATED`, `MOCK`, and `CI`.
- Use the P018 export pipeline only after a separate explicit export choice and privacy review. Do not run `ic evidence export` during Phase 0. Preserve original P009 evidence unchanged; an export is a derivative and cannot replace or upgrade it.

## Review and status

Complete [the H004 result template](H004-RESULT-TEMPLATE.md). The H004 worksheet is not a P009 acceptance package and cannot set `DEVICE_VERIFIED` or a hardware `PASS`. Do not infer acceptance from manually entered JSON, a valid manifest, host CI, a hash match, or a successful command. Any physical gate remains pending until an independent human review examines the original observations and provenance under P009.
