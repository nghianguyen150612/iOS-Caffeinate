# P017 — Safety and authorization boundary

P017 separates five facts: a definition is valid; an occurrence is temporally due; resources appear available; recovery is clean; and an operation is authorized. None implies the next. The recurrence engine and CLI never call IOKit. The daemon does not poll schedules or acquire assertions for them.

P014 recovery and single-assertion ownership remain authoritative. P015 policy is evaluated specifically as `SCHEDULED_UNATTENDED`; it returns `SCHEDULE_EXECUTOR_NOT_AUTHORIZED`. Eligibility for a manual bounded session cannot authorize unattended work. No operator override or policy PASS is fabricated. P016 is on-demand only: unavailable battery, charging or thermal values remain unknown, stale data cannot pass review, and no polling or network probes are added.

New schedule proposals are at most 300 seconds. Legacy definitions up to 86,400 seconds remain stored and visible as `LEGACY_DURATION_EXCEEDS_POLICY`; they are not truncated, renewed or automatically executed. No active hold is silently shortened. No schedule edit acquires an assertion.

The daemon may evaluate definitions only while it happens to be executing, but P017 does not keep it running or wake it. A persisted future time is not an alarm. `scheduled_wake=UNVERIFIED`; no RTC alarm, boot execution, launchd activation, SSH availability or unlimited renewal is claimed. CI fixtures and Linux mock builds have no real power effect and are not device evidence.

Cloud validation status is `P017_CLOUD_COMPLETE_DEVICE_SCHEDULING_PENDING` once exact-head CI completes. Device acceptance still depends on the P011–P016 gates, physical operator presence, an independent recovery method and separately authorized state-changing trials.
