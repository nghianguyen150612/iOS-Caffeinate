# P009 — Device Acceptance Harness

P009 provides an offline evidence format, validator, timeline replay engine, and readiness report for later supervised iPad testing. It does not install packages, contact a device, start a daemon, or claim hardware acceptance.

The acceptance path has three separate parts:

1. **Collection contract.** Operators, the iPad, and an independent observer record timestamped, source-classified observations in a versioned session. See [the evidence format](P009-EVIDENCE-FORMAT.md).
2. **Offline validation.** The validator checks the schema, safe paths, file sizes, manifest coverage, hashes, duplicate identifiers, secret-like fields, and event structure before interpreting the session.
3. **Offline replay and review.** Replay checks ordering, duration, cleanup, screen state, and LAN/Tailscale evidence separately. Complete physical claims remain `REVIEW_REQUIRED` until an operator runs the interactive review process. Simulated, mock, and CI evidence remains blocked from physical gates.

## Commands

The commands require an explicit evidence directory and use only Python 3's standard library:

```sh
python3 scripts/p009_evidence.py manifest /path/to/staged-evidence
python3 scripts/p009_evidence.py validate /path/to/evidence
python3 scripts/p009_evidence.py replay /path/to/evidence --json
python3 scripts/p009_evidence.py report /path/to/evidence
python3 scripts/p009_evidence.py report /path/to/evidence --format json
python3 scripts/p009_evidence.py review /path/to/evidence
```

`manifest` is a separate staging operation. It fills the session's attachment descriptors and writes deterministic `session.json` and `manifest.json` records; it refuses to replace an existing manifest unless `--replace` is explicit. Validation, replay, and report commands are read-only. None of these commands makes a network connection.

Exit codes are `0` for structurally valid input or a completed report, `2` for malformed/unsafe input, and `3` for a replay with a definite error finding. A valid report can still show blocked or incomplete gates.

## Gate state meanings

The registry is [device-acceptance-gates-v1.json](schemas/device-acceptance-gates-v1.json). It covers device identity, iOS runtime, package hashes, signature acceptance, installation and rollback; assertion acquisition and release; STOP, expiry and SIGTERM cleanup; independent locked-screen LAN and Tailscale SSH; battery, thermal, recovery and disabled launchd; unresolved assertions; and scheduled wake.

| State | Meaning |
|---|---|
| `PENDING` | No readiness evaluation is available. |
| `INSUFFICIENT_EVIDENCE` | Required observation or causal/time correlation is missing. |
| `REVIEW_REQUIRED` | Physical-origin evidence is structurally supported and needs an individual human decision. |
| `FAIL` | Evidence records a failed or contradictory condition. |
| `BLOCKED` | Evidence is simulated/mock/CI, or physical presence is not confirmed. |
| `PASS` | A gate with physical-origin evidence was individually approved in the interactive review. |

The session's own `review_status` is an untrusted claim and never approves a gate. The interactive review does not create a digital signature; a reviewer must inspect physical provenance and the underlying evidence separately. Hashes detect alteration but do not authenticate the observer.

Scheduled wake is a separate gate from scheduled awake. No report authorizes unattended operation. `unattended_24_7` remains `NOT_VALIDATED` even if a future bounded trial passes.

## Trial limits

Every acceptance trial is attended and capped at 300 seconds. The first device trial should normally be 30–60 seconds. The tool does not retry, resume, or restore an interrupted trial. A missing release, failed release, incomplete cleanup, or unresolved assertion cannot pass the safety gates.

## Current project report

The actual P009 project status is recorded in [P009-READINESS.md](P009-READINESS.md) and [P009-READINESS.json](P009-READINESS.json). The iPad remains unavailable; every real-device gate is pending.

The deterministic synthetic fixtures used in tests live in the generator and case list under `tests/fixtures/p009/`. They are marked `SIMULATED` and are not bundled as a production acceptance session.
