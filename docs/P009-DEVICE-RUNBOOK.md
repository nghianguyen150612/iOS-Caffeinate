# P009 — Attended Device Runbook

This runbook predates the operator-reported test on October 18, 2026. P010 records those observations and provides the current supervised package-acceptance and idle-comparison procedure. The P009 session format and human-review requirements remain applicable. Read [P010 hardware findings](P010-HARDWARE-FINDINGS.md) and [P010 device acceptance](P010-DEVICE-ACCEPTANCE.md), plus the existing [P002](P002-DEVICE-TEST.md), [P003](P003-DEVICE-TEST.md), [P004](P004-DEVICE-TEST.md), [P005](P005-DEVICE-TEST.md), [P006](P006-DEVICE-TEST.md), [P007 device](P007-DEVICE-TEST.md), and [P007 rollback](P007-ROLLBACK.md) procedures.

All phases are manual. Keep the device operator beside the iPad, maintain a recovery path that does not depend on SSH or Tailscale, and keep launchd disabled. Do not schedule an unattended test.

## Phases

1. **Physical preflight and recovery.** Confirm the model/iOS/bootstrap in person, battery and thermal baseline, current package/daemon state, and direct physical recovery. Keep the local console/CLI available so the operator can stop the trial without network access.
2. **Artifact and signing review.** Select the exact workflow artifact and source SHA. Verify package and binary SHA-256 values, package paths, signing/profile status, and disabled launchd payload using the [P010 signing](P010-SIGNING.md) and [package validation](P010-PACKAGING-VALIDATION.md) procedures. Do not use an untrusted signing tool.
3. **Manual installation authorization.** Review installation and rollback prerequisites with the operator. Install only under separate explicit authorization. Never let the evidence harness install, sign, or deploy an artifact.
4. **Read-only diagnostics.** Follow P002–P008 read-only status, doctor, plan, package, and wake checks. Do not infer network reachability from local daemon status.
5. **Manual foreground daemon startup.** Start only the foreground daemon using the established P006 procedure. Confirm it remains manually controlled and that launchd stays disabled.
6. **Supervised short assertion test.** Begin with one attended 30–60 second trial, below the 300-second hard ceiling. Record preflight, acquisition attempt/result, hold, clock uncertainty, and screen state. Do not repeat automatically.
7. **STOP and expiry verification.** Run separate bounded trials for explicit STOP and natural expiry. Record each release result. A STOP observation does not substitute for expiry, or vice versa.
8. **SIGTERM and release verification.** In a separate supervised run, terminate the foreground daemon with SIGTERM and record release, daemon exit, and any unresolved assertion. Stop if release fails; do not continue to network tests.
9. **Separate LAN and Tailscale trials.** From a second computer, record LAN and Tailscale independently while the operator confirms the display is locked. Include port 22, authenticated SSH session result, latency, observer timebase/uncertainty, screen state, trial ID, and Tailscale path where applicable. Use only existing operator-authorized credentials; never put them in logs or evidence. P009 does not install, configure, authenticate, or restart Tailscale.
10. **Battery and thermal observations.** Record the operator's observations before, during, and after each bounded test. Stop if the device becomes hot, battery is low, or behavior changes unexpectedly.
11. **Evidence export.** Export sanitized session metadata and evidence attachments. Remove credentials, private files, unrelated personal data, and unneeded log lines. Set honest source classifications and preserve separate clock uncertainty.
12. **Offline validation and human review.** On a trusted computer, build the deterministic manifest, run `validate`, `replay`, and `report`, inspect each contradiction and attachment, then run `review` for gates with physical-origin evidence. Human review is required; hashes alone do not prove provenance.
13. **Rollback if required.** Use the existing P007 rollback checklist. Record package removal/rollback and confirm preserved user data and disabled launchd. Do not use network access as the only recovery route.

Any failed release, unexpected behavior, unsafe temperature, missing physical recovery, or uncertain cleanup ends the session. Keep the screen awake and use the established local recovery procedure. Do not restart an interrupted trial automatically.

The harness does not collect data from the iPad and this runbook does not authorize installation. Operator-reported observations exist, but remain `REVIEW_REQUIRED` or `INSUFFICIENT_EVIDENCE` until source files and provenance are reviewed through P009. Package installation and acceptance remain pending.
