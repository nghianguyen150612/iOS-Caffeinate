# P014 — P004 Schedule Interaction

P004 keeps schedules in its existing persistent store. At P004/P014, the daemon evaluated them on startup and while it ran. P017 preserves those definitions but removes automatic scheduled assertion acquisition because P015 does not authorize unattended execution. Diagnostics can still calculate an active window without implying runtime execution.

P014 addresses the unsafe case by requiring a durable, trusted, clean recovery marker before any new assertion path is allowed. The gate applies to `probe`, normal `START`, and server trial acquisition, and remains the required recovery authority for any future separately reviewed schedule executor. A missing journal, unclean `RUNNING` marker, failed release, unknown ownership, or unsafe record blocks manual acquisition. It does not erase schedules or mark an occurrence consumed as a substitute for cleanup evidence.

| Startup situation | P014 behavior |
|---|---|
| First P014 launch with no recovery record | Create an unverified running journal and block assertion requests until attended review. |
| Prior run has clean process and confirmed cleanup record | Manual operations may continue through their normal gates; schedule preview remains read-only and execution is blocked by P015. |
| Prior run left `RUNNING` or cleanup unverified | Record the unobserved outcome and block scheduled and manual assertion acquisition. |
| Recovery record missing, corrupt, unsafe, or unsupported | Preserve unsafe data and block assertion acquisition. |
| Occurrence became due while blocked | Do not acquire or busy-loop; existing P004 occurrence bookkeeping remains authoritative. |
| Operator-reviewed recovery completed | A later manual start can use the trusted reviewed journal; the stored schedule remains diagnostic only under P017. |

P014 does not promise wake from deep sleep, replay a missed assertion, infer that a schedule was active on the target, or alter the schedule format. P017 intentionally changes legacy automatic execution while preserving the stored format and `last_fired_time`.
