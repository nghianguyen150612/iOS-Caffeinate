# P015 — P014 Recovery Integration

P015 reads the existing P014 journal with `recovery_store_load` and uses the P014 record and decision types. It does not create, rewrite, reset, repair, or delete recovery state.

The session policy blocks when the journal is missing, unsafe, corrupt, unsupported, unreadable, or not validated; when the process is not clean; when cleanup is unverified; when the last exit records `RELEASE_FAILURE`; when prior assertion ownership is unknown; when the daemon reports `BLOCKED`; or when assertion release is unresolved. The P014 journal's strict file ownership, mode, link, and parser checks remain in force.

The result reports P014 process, cleanup, last-exit, and recovery decision status. The P014 supervisor capability remains a separate observation. It is not inferred from a clean journal. Restart-budget exhaustion blocks automatic recovery eligibility; P015 has no recovery executor and never restarts a process. P013 service lifecycle commands are not unlocked by a P015 result.

An operator-reviewed P014 cleanup reset remains an operator review record. It does not become a P009 `DEVICE_REPORTED` observation or satisfy the separate physical recovery gate by itself. P015 never synthesizes a clean record to make policy eligible.
