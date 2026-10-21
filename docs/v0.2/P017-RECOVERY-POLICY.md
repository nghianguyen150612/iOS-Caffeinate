# P017 — P014 recovery and assertion ownership

P017 diagnostics cannot reset or repair P014 state. Before a future scheduled assertion could be considered, the same recovery restrictions that block manual acquisition must apply: missing or unsafe journal, unverified prior cleanup, corrupt metadata, failed release, ambiguous assertion ownership, blocked daemon state, failed persistence or an already-owned assertion all block. P017 does not infer cleanup from an absent PID, socket or launchd job and never fabricates a clean journal.

`schedule doctor` reads the recovery journal and, when an existing daemon responds, reports its recovery schedule gate and active assertion state. A missing runtime response is `UNKNOWN_RUNTIME_UNAVAILABLE`; a missing or invalid journal is separately shown. Schedule mutations are refused unless recovery is trusted and the daemon is idle with no assertion owned. Diagnostics remain read-only. They never invoke `ic service recovery reset` or start a daemon.

P017 currently suppresses all scheduled acquisition because P015 denies the unattended operation, regardless of a clean recovery result. A schedule can therefore remain `UPCOMING` or `ACTIVE_WINDOW` in calendar analysis while execution is `BLOCKED_POLICY`. No blocked window is queued for catch-up after recovery changes. Any later action requires a fresh, explicit eligibility review and separately authorized executor design.

Existing active legacy holds are not truncated by schedule edits. An operator must follow the P014-aware attended STOP/release lifecycle. If release or ownership is uncertain, stop and resolve recovery before any new manual operation. Schedule mutation is never an implicit release or assertion action.
