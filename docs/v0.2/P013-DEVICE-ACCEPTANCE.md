# P013 — Supervised Device Acceptance

**Status: PENDING.** No P013 physical service operation has been performed. P011 installed-package acceptance and the stable package signature/provenance gate must pass first. Review P012 safety observations where they affect service activation.

P018's initial attended visit is limited to the read-only command set in [P018 device acceptance](P018-DEVICE-ACCEPTANCE.md). The lifecycle sequence below is a later, separately authorized procedure; P018 does not authorize a launchd mutation or daemon activation.

## Preconditions

- P011 package acceptance passes for the exact installed stable package, including the approved signer provenance check.
- P012 safety observations relevant to assertion ownership, release, and recovery have been reviewed.
- The operator is physically present at the iPad mini 2 A1489 (`iPad4,4`) running iOS 12.5.7 with Amethyst/Procursus rootful.
- Direct recovery independent of SSH/Tailscale is available and has been checked.
- The current daemon process, socket, assertion state, schedules, logs, package identity, and recovery path are known.
- A supervised follow-up build has established the exact launchctl operation and syntax to test. The P013 cloud build reports mutation semantics `UNVERIFIED` and its mutating commands fail closed; do not bypass that gate by manually copying or loading a plist.

## Supervised sequence after the gate is cleared

1. Run `ic service doctor` and `ic service status`; save exact output and source/package hashes.
2. Follow the read-only procedure in [launchd compatibility](P013-LAUNCHD-COMPATIBILITY.md). Do not issue a mutating launchctl command unless its exact iOS 12 syntax and effect are separately reviewed.
3. Inspect the staged plist and confirm no active live plist collision. Confirm package identity, executable ownership/mode, label uniqueness, socket state, and assertion state.
4. If separate persistent enablement is verified, run the explicit enable command and confirm it does not start the daemon or acquire a power assertion. If enablement necessarily starts the service, stop and obtain a separate explicit operator decision before any combined operation.
5. Run explicit start only after enablement is understood. Confirm the launchd response, a responsive daemon IPC status, process/registration fields, and `assertion.state=NONE` after startup.
6. If a bounded assertion-release test is separately authorized, start it explicitly, observe ownership, then use the graceful service stop and verify the daemon confirms release before exit. Do not substitute disappearance of a process for proof of release.
7. Run explicit disable only after stop cleanup is confirmed. Verify the launchd label is no longer registered and the live plist is absent or in the expected disabled state.
8. Confirm `/var/lib/ioscaffeinate`, schedules, server policy, evidence, and `/var/log/ioscaffeinate` are preserved.
9. Exercise the documented rollback from direct local access. Record each result as device evidence; do not infer a reboot persistence result from a successful load or run.

The P013 procedure does not reboot or respring. A supervised reboot trial is a separate hardware-gated action requiring independent operator authorization. Boot persistence remains `UNVERIFIED` until that trial is reviewed. Service running, device awake, and SSH reachable are separate observations.
