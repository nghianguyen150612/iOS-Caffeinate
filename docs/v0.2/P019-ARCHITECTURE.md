# P019 Architecture

P019 adds an offline acceptance and analysis layer around the existing P009, P012, and P018 contracts. It does not add a device controller.

```text
P019 protocol v1
      │
      ├── plan / host session template / operator confirmations
      │
      ├── P012 trial records ──> existing P012 validator and analyzer
      │
      ├── raw P009 v1 packages ──> existing P009 validation and replay
      │                              │
      └── P018 sanitized derivative ─┴──> consistency/privacy check only
                                             │
                                  versioned P019 decision and P020 gates
```

## Trust boundary

- `experiments/p019/protocol-v1.json` fixes the target, phases, sample plan, stop rules, evidence requirements, acceptance scope, and revision policy. Its JSON Schema rejects unknown fields. The analyzer also pins the current P012 v1 digest so P019 cannot silently redefine P012 trials.
- `scripts/p019_session.py` reads local files. `plan`, `validate`, `analyze`, and `report` are offline and read-only. `init` and `record-confirmation` write only a new host-side JSON file at an explicit path. The tool has no SSH engine, device transport, package manager, launchd writer, daemon control, or assertion API.
- P012 v1 trial records remain authoritative for A/B/C/D ordering, route, quiet interval, screen-lock confirmation, and one-probe outcomes. P019 does not copy or modify the P012 probe implementation.
- P009 v1 remains the hardware-acceptance authority. P019 references one or more original P009 packages by session ID and hashes, validates each with the existing P009 loader, replays each timeline, and checks referenced event types and source classes. A claimed source class still requires independent provenance review.
- P018 export validation is separate. A valid sanitized derivative establishes structure and privacy compliance only. It cannot replace, rewrite, or authenticate raw P009 evidence.

## Completion levels

Stage A is cloud preparation: protocol and schemas, inert tools, offline analysis, simulated fixtures, documentation, and exact-head CI. It reports `P019_CLOUD_COMPLETE_HARDWARE_ACCEPTANCE_PENDING`.

Stage B requires separately authorized attended device work, exact package and signer provenance, complete bounded sessions, clean recovery, raw P009 validation, P018 derivative review, and independent human evidence review. The versioned result may then name `ACCEPTED_FOR_TESTED_SCOPE`; it never emits a blanket 24/7 readiness result.

`READY_FOR_ATTENDED_TEST` is a computed prerequisite state, not permission to run a physical operation. The device operator retains separate authorization for installation, daemon lifecycle, and each bounded assertion.

## Result states

P019 result v1 includes `NOT_STARTED`, `PREREQUISITES_BLOCKED`, `READY_FOR_ATTENDED_TEST`, `IN_PROGRESS`, `INCOMPLETE`, `FAILED_SAFETY`, `INCONCLUSIVE`, `EVIDENCE_REVIEW_PENDING`, and `ACCEPTED_FOR_TESTED_SCOPE`. Every result carries gate reasons, evidence provenance limits, denominators, route-separated outcomes, and excluded scope. Simulated, mock, or CI evidence cannot satisfy hardware gates.

See [prerequisites](P019-PREREQUISITES.md), [observation format](P019-OBSERVATION-FORMAT.md), and [evidence review](P019-EVIDENCE-REVIEW.md).
