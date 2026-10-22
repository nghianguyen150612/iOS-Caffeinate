# P014 — P004 Schedule Interaction

P004 keeps schedules in its existing persistent store and evaluates them when the daemon starts and while it runs. A new daemon does not restore an old IOKit assertion identifier. It can, however, evaluate an active scheduled window and request a fresh assertion.

P014 addresses the unsafe case by requiring a durable, trusted, clean recovery marker before any new assertion path is allowed. The gate runs before startup schedule evaluation and also applies to `probe`, normal `START`, and server trial acquisition. A missing journal, unclean `RUNNING` marker, failed release, unknown ownership, or unsafe record blocks those paths. It does not erase schedules or mark an occurrence consumed as a substitute for cleanup evidence.

| Startup situation | P014 behavior |
|---|---|
| First P014 launch with no recovery record | Create an unverified running journal and block assertion requests until attended review. |
| Prior run has clean process and confirmed cleanup record | Proceed with normal P004 schedule evaluation, including a currently active window. |
| Prior run left `RUNNING` or cleanup unverified | Record the unobserved outcome and block scheduled and manual assertion acquisition. |
| Recovery record missing, corrupt, unsafe, or unsupported | Preserve unsafe data and block assertion acquisition. |
| Occurrence became due while blocked | Do not acquire or busy-loop; existing P004 occurrence bookkeeping remains authoritative. |
| Operator-reviewed recovery completed | A later start can use the trusted reviewed journal; the existing P004 schedule is evaluated normally. |

P014 does not promise wake from deep sleep, replay a missed assertion, infer that a schedule was active on the target, or alter the schedule format. Normal schedule semantics are preserved after a trusted clean or operator-reviewed recovery state.
