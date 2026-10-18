# P008 — Deferred Engineering Backlog

P008 only fixes confirmed assertion-lifecycle, persistence, data-loss, and integration-blocking issues. These follow-ups are not release blockers for the bounded cloud candidate and should be handled in focused changes.

| Item | Reason to defer |
|---|---|
| Define and test policy for ambiguous and nonexistent local times across DST transitions | Recurrence currently delegates local-time resolution to the platform C library's `mktime`; the target iOS runtime has not been measured. Document policy with Linux tests and later confirm against iOS tzdata. |
| Validate timezone database names against the target's installed zoneinfo | P008 rejects unsafe characters and traversal, but does not claim that every syntactically safe timezone exists on iOS. Unknown-zone behavior must be made explicit without guessing device filesystem layout. |
| Review whether recurring schedules with adjacent 24-hour occurrences should be permitted | Each native assertion is bounded to 24 hours, but a user-created recurrence can request repeated windows. Any aggregate cap would change P004 behavior and needs a separate product decision. |
| Evaluate directory-metadata durability for schedule renames on the target filesystem | P008 syncs the temporary file before atomic rename. Sudden power-loss durability of the rename has not been established on the target filesystem; no such test is reported in P010. |
| Replace the small schema-specific schedule JSON reader with a general parser only if the schema grows | Version 1 is now strictly bounded and malformed records fail closed. Avoid adding a dependency or broad parser rewrite without a format need. |

These items do not change the hardware status. No backlog item authorizes daemon startup, device installation, signing, or an indefinite assertion.
