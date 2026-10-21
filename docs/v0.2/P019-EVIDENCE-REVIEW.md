# P019 Evidence Review

P009 v1 remains the hardware-acceptance authority. P019 does not treat JSON source labels, hashes, validator output, CI artifacts, or a claimed `REVIEWED` value as proof that a physical observation is authentic.

## Review sequence

1. Preserve each original P009 package and its manifest in a secure private location. Do not edit observations, remove raw addresses/assertion IDs, or rewrite source classes to pass export filtering.
2. Run the existing P009 `validate`, `replay`, and `report` commands offline. Inspect exact source/package hashes, installed path identity, device identity, clock/timebase provenance, event source classes, cleanup, release, contradictions, missing evidence, and attachments.
3. Check the referenced P009 packages and event IDs against the P019 session. P019 verifies package hashes and event types but cannot authenticate the operator or device.
4. Run P018 export dry-run/validation as appropriate. Preserve raw evidence separately. The export must retain `hardware_evidence_accepted=NOT_ESTABLISHED`; its privacy validator checks structure and sensitive fields, not empirical truth.
5. Review provenance and safety independently from the operator who performed the trial. Record reviewer ID, exact P009 session hash, hashes checked, decision, timestamp, and findings. The review record is still an auditable claim, not a cryptographic identity proof.
6. Accept only the exact behavior/condition/route/build covered by complete reviewed evidence. List limitations and all excluded claims.

## Raw evidence and sanitized export

P009 raw records can contain network addresses or identifiers needed for independent review. P018 intentionally rejects or excludes sensitive network identifiers and assertion IDs. Raw P009 and sanitized P018 export are different artifacts with different purposes. A sanitized derivative cannot establish every raw observation. If a valid derivative cannot safely represent required material, record `EXPORT_BLOCKED_BY_PRIVACY`; do not weaken filters or make a derivative by altering the original.

## Synthetic data

Every cloud fixture is `SIMULATED`, `MOCK`, or `CI`. CI artifacts are useful for reviewing deterministic output and compatibility only. They cannot be included as P009 device evidence or promoted by editing a JSON field.
