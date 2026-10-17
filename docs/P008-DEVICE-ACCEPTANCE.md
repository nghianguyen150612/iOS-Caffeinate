# P008 — Deferred Device Acceptance Plan

**Status: PENDING.** The target iPad mini 2 A1489 is unavailable. No physical test is part of P008 cloud work.

Every future test requires direct physical recovery access, an independent second device for connectivity measurements, and a way to observe battery and thermal condition. Do not use SSH as the only recovery route. Stop if the device is hot, has insufficient battery, or behaves unexpectedly.

## Required sequence

1. **Read-only preflight.** Record device model/iOS version, current package state, daemon/socket state, current configuration and schedule files, and recovery method. Run `ic status`, `ic wake status`, and `ic server status`, `doctor`, and `plan`. These must not acquire an assertion or probe network reachability.
2. **Artifact and signing review.** Retrieve binaries and package from the exact P008 workflow artifact. Verify the release-candidate manifest, package checksum, binary checksums, ARM64/iOS 12.0 metadata, package paths, and disabled launchd state. The CI package is unsigned. Do not install until a trusted signing and acceptance process for the jailbreak has been confirmed.
3. **Supervised short assertion trial.** With recovery present and display on, run the read-only probe and then one manually supervised trial capped at one minute. Observe status and backend diagnostics. Check STOP release and bounded expiry. Do not start any network or screen-lock experiment until release is confirmed.
4. **Cleanup gate.** Exercise STOP and SIGTERM cleanup under supervision. If release fails or ownership remains unresolved, keep the screen on, do not continue, and use physical recovery. Preserve logs and return codes.
5. **Separate connectivity observations.** From an independent device, measure LAN SSH and Tailscale SSH separately at baseline, during a bounded supervised hold, and after confirmed STOP/expiry. Record display state, timestamps, latency, authenticated session outcome, and direct/relay path. A LAN result does not pass Tailscale; a Tailscale result does not pass LAN.
6. **Power and recovery observation.** Record battery/charging and thermal state before, during, and after the bounded trial. Confirm physical recovery remains available. Do not run an unattended overnight test.
7. **Installation and rollback.** Only after signing acceptance, perform an explicitly approved package installation with the package scripts and complete rollback prerequisites available. Verify user data preservation and rollback using the prior package artifact. Never activate the staged launchd template during acceptance.

## Existing milestone procedures

- [P002 device and runtime procedure](P002-DEVICE-TEST.md)
- [P003 lifecycle and security procedure](P003-DEVICE-TEST.md)
- [P004 scheduling and restart procedure](P004-DEVICE-TEST.md)
- [P005 scheduled-wake feasibility procedure](P005-DEVICE-TEST.md)
- [P006 bounded server-trial procedure](P006-DEVICE-TEST.md)
- [P007 package inspection procedure](P007-DEVICE-TEST.md) and [rollback prerequisites](P007-ROLLBACK.md)

Scheduled wake remains **UNVERIFIED** and has no command or physical test that can be inferred from a successful assertion trial. A successful short test does not authorize indefinite operation or a 24/7 hold.
