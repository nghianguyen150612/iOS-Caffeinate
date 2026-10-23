# iOS-Caffeinate v0.2.0 — Draft Release Notes

**Draft only. v0.2.0 has not been authorized or publicly released.** Current release decision: `RELEASE_BLOCKED` pending physical acceptance, candidate-bound P010 evidence, and independent review.

## Overview

The v0.2 development cycle integrates the P011–P019 cloud engineering work into a reviewed candidate and adds stricter build provenance, package inspection, evidence handling, security review, upgrade planning, and release-readiness gates. These changes do not certify continuous awake state or unattended server operation.

## Cloud-implemented capabilities

- Bounded manual holds with explicit STOP, expiry, state reporting, and conservative cleanup handling.
- Root-only native daemon IPC, CLI diagnostics, package preflight, and offline evidence export/review tooling.
- Persistent schedule definitions and recurrence/DST/conflict diagnostics.
- P013 service status/doctor/plan and P014 recovery accounting and startup gates.
- P015 Server Mode policy evaluation and P016 on-demand telemetry observations.
- P019 supervised-session schemas, analyzers, and privacy-aware evidence workflow.

## Safety and policy

P014 does not include a production automatic restart executor. P013 launchd activation remains gated, and managed profiles require `KeepAlive=false` and `RunAtLoad=false`. Unattended Server Mode remains disabled. Missing or unknown recovery ownership, assertion release, sensor data, or service state remains a blocker.

## Scheduling change

**P017 intentionally disables automatic scheduled assertion execution.** Future occurrences are diagnostic only. Schedule storage does not imply execution and cannot wake a suspended device. Existing schedule data is preserved; upgrade does not enable schedules or migrate policy to execution.

## Package and upgrade

The package identity remains `com.ioscaffeinate.cli`; rootful architecture remains `iphoneos-arm`. P020 CI creates an unsigned `0.2.0~rc1-1` development package. R05 separately prepares a signed, device-unverified candidate using the exact H003 signer; neither artifact is installation-ready before the attended H004/P011 and physical gates pass. The candidate does not replace the published v0.1.0 package or assets. Upgrade preview is read-only; package scripts do not start services, acquire assertions, delete state, reset recovery, or change SSH/Tailscale.

## Known limitations and unsupported operations

- Automatic restart is unavailable.
- Launchd activation remains gated and unverified on iOS 12.5.7.
- Unattended Server Mode is disabled.
- Battery and thermal telemetry may be unavailable; values are not calibrated battery-health measurements.
- Scheduled deep-sleep wake is unverified and not promised.
- 24/7 SSH reliability and continuous awake state are not established.
- Physical endurance acceptance and verified boot persistence are not established.

## Hardware acceptance and rollback

P010 signer provenance, P011 package acceptance, P012 controlled trials, P013/P014 lifecycle and recovery acceptance, P016 resource review, P018 privacy review, P019 supervised cycles, and independent P009 provenance review remain required. Rollback requires a trusted previous package, known preserved state, known cleanup and service state, and a reviewed physical recovery plan. It is not automatic.

## Security notes

P020 reviewed privileged IPC, assertion lifecycle, recovery journal, filesystem boundaries, package scripts, evidence export, signing metadata, and CI artifact boundaries. No confirmed critical or high runtime exploit was identified in the cloud source review. Reviewer receipts require signatures verifiable with an externally managed trusted keyring. This review does not replace physical acceptance or final human approval.
