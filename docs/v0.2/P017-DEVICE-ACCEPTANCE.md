# P017 — Supervised device acceptance

Cloud engineering does not connect to or modify the reference iPad. Device scheduling acceptance is pending. Begin with read-only diagnostics only after P011 package acceptance, P012 safety review, P013 launchd compatibility review, P014 recovery acceptance, P015 policy acceptance and P016 telemetry-limit review. Require the operator physically present and an independent local recovery method.

Initial read-only checklist:

1. Record installed binary/package identity and current service state without starting the daemon.
2. Run `ic schedule list`, `ic schedule validate`, `ic schedule next`, `ic schedule conflicts` and `ic schedule doctor`.
3. Run `ic schedule explain <id>` for each relevant definition. Compare IANA/system timezone, DST resolution, next UTC occurrence, conflict windows, legacy duration warning, P014 state and P015 denial.
4. Confirm schedule diagnostics did not start launchd/daemon, modify `schedules.json`, change `last_fired_time` or acquire an assertion.
5. Preserve before/after file hashes and P009-compatible operator records. Report all unavailable observations as unknown.

Do not use an overnight unattended test. Do not reboot or respring to demonstrate wake, force a real-device clock/timezone change for DST, probe SSH/Tailscale during schedule evaluation or treat a calculated next time as an execution promise. Host fixtures cover calendar transitions.

Any schedule mutation or bounded hold requires a separate explicit authorization after the read-only review. It must be attended, generation-checked, no longer than 300 seconds for new sessions, have verified release and direct recovery, and must not imply unattended scheduled operation. Do not test an active legacy long hold by allowing P017 to truncate it.

The P017 cloud report must remain `P017_CLOUD_COMPLETE_DEVICE_SCHEDULING_PENDING` until separately reviewed physical evidence exists. Even a supervised assertion trial cannot prove deep-sleep wake; scheduled wake remains `UNVERIFIED` unless an independently reviewed capability and experiment establish it.
