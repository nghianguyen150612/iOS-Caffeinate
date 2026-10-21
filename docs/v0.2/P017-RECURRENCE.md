# P017 — Recurrence and occurrence identity

One-time definitions use a UTC epoch target. Daily and weekly definitions enumerate Gregorian local dates, then resolve each requested wall time through the timezone conversion boundary. The implementation does not add 86,400 seconds to reach the next civil day. Weekday masks retain P004's Sunday-based bits (`Sun=0` through `Sat=6`). Month/year boundaries and leap years follow Gregorian dates.

The analysis horizon is bounded to 370 local calendar dates. Every conversion checks `time_t` and end-boundary overflow. Unsupported zones, failed conversions and an exhausted horizon produce an incomplete/unverified result rather than an apparent valid time. Durations are fixed elapsed seconds from the resolved UTC start, so a window crossing an offset transition has an unambiguous UTC end.

Outcomes distinguish `UPCOMING`, `ACTIVE_WINDOW`, `EXPIRED`, `MISSED`, `ALREADY_FIRED`, `CONFLICT`, `BLOCKED_RECOVERY`, `BLOCKED_POLICY`, `RESOURCE_UNAVAILABLE`, `TIMEZONE_UNVERIFIED` and `INCOMPLETE`. The current CLI computes temporal outcomes; execution blockers remain explicit and no outcome starts an assertion.

The occurrence identity binds the schedule ID, a hash of the definition revision, intended calendar date/time, effective timezone, resolution, UTC start and end. `last_fired_time` remains the v1 absolute end-boundary marker. Preview commands do not change it. Marking is monotonic and idempotent; a failed assertion acquisition is never recorded as success. Since P017 has no scheduled executor, blocked or missed definitions are not caught up later.

Clock jumps change the reference instant used by a preview, not the intended occurrence identity. A forward jump beyond a window reports a missed/expired outcome; a backward jump cannot turn the same end-boundary marker into a second successful occurrence. A daemon restart has no auto-replay behavior because scheduling evaluation is not part of daemon startup or its event loop.

Scheduling an assertion does not guarantee waking the device from deep sleep. The daemon must be running and evaluating when a window is relevant; P017 provides no RTC alarm or boot guarantee.
