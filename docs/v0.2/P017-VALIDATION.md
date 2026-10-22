# P017 — Validation plan and evidence

The dedicated `p017-scheduling-validation` workflow job checks out the pull-request head and records its exact source SHA. It builds C11 scheduling code, runs deterministic recurrence/DST and conflict fixtures, storage fault cases, schedule CLI tests, missed-window/restart integration, and P014/P015/P016 regressions. It also verifies the iOS cross-build, Mach-O inspection and rootful package jobs remain required in the full workflow.

Coverage includes one-time/daily/weekly schedules; weekday masks; spring gaps and fall folds; multiple injected zones and changed system-zone context; leap day, year/month boundaries, midnight, date-line offsets and DST-crossing windows; rollback/forward reference jumps; repeated evaluation and identities; missed and expired windows; overlap and manual ownership; 300/301/86,400-second limits; invalid/unverified timezone; malformed/duplicate-key storage; atomic-write failure; stale generation; P014 blocks; P015 unattended denial; P016 unknown/stale telemetry; and no implicit daemon, launchd, network or power action.

Expected tests use fixed reference instants and injected timezone transitions. Linux's libc and fixtures do not certify the iOS CoreFoundation runtime. The macOS iPhoneOS 12 ARM64 build checks the SDK interface and binary only. No CI case acquires a real IOKit assertion, installs a package on the iPad, changes its clock, enables launchd or performs a network probe.

The deterministic report and logs are uploaded as `iOS-Caffeinate-P017-scheduling-validation`. The validation class is `SIMULATED_AND_MOCK_ONLY`. Exact-head CI must complete after the final source commit; this document does not claim a run that has not happened.
