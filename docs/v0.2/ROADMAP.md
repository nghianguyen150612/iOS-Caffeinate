# iOS-Caffeinate v0.2 — Reliable Server Mode

The public stable release is **v0.1.0** (`com.ioscaffeinate.cli` `0.1.0-1`). Its Debian artifact remains device-unaccepted. The v0.2 cycle starts by verifying that exact package and preparing attended acceptance. A public stable release label describes the release channel; it does not certify installation, device behavior, or reliability.

Feature implementation, physical-device acceptance, and production reliability certification are separate results. CI can validate source, package structure, and deterministic workflows. Only attended observations on the reference iPad can close device gates. P009 remains the evidence authority; its vocabulary and schema are unchanged.

## Milestones

### P011 — Stable Debian package hardware acceptance

**Depends on:** v0.1.0 release `0cfdc645dc1d67ddc4320a00bb114763b9669b66`; P009 evidence schema; P010 signing and package validator.

**Deliverables:** pinned release verifier; read-only device preflight; supervised installation, bounded assertion, state-preservation, and rollback procedure; P009 evidence matrix; CI regressions.

**Safety constraints:** no automatic install/removal; no active LaunchDaemon; no unbounded hold; no device access from cloud; no elevation of operator-reported facts without P009 review.

**Validation and completion:** cloud scripts and tests pass on an exact commit, release metadata and package sidecars agree, and a reviewable PR is merged only after review. Hardware package acceptance separately requires a physically attended installation and installed-path checks. Rollback separately requires a verified prior artifact and physical recovery path.

### P012 — Controlled idle and power-behavior research

**Depends on:** P011 cloud baseline; P011 installed-package acceptance and physical recovery before any device trial.

**Deliverables:** preregistered protocol v1; four explicit conditions; a one-shot attended host SSH probe; operator trial recording; offline analysis; P009 v1 event proposals where representable; deterministic tests and CI artifact; research, operator, format, analysis, evidence, validation, and manifest documentation.

**Safety constraints:** no physical trials before P011 installed-package acceptance, separately authorized installation, installed runtime verification, confirmed acquire/release cleanup, direct physical recovery, operator presence, and battery/thermal review. Each trial has one route and at most one SSH command after a quiet period. No automated device action, unbounded hold, host-key bypass, or implication that SSH reachability proves prevention of sleep.

**Validation and completion:** cloud tooling and synthetic analysis can complete independently of the iPad. Device results need the preregistered A/B/C/D comparisons, separate LAN and Tailscale observations, locked-screen and quiet-period confirmations, battery/thermal/charging/route/timebase records, actual acquire/release cleanup, counterbalanced route order, physical recovery, and P009 human review. P012 must not claim battery, thermal, OS-suspend, or sleep-prevention effects from SSH reachability alone. Hardware remains `PENDING` until separately reviewed.

### P013 — Opt-in LaunchDaemon lifecycle management

**Depends on:** P011 package layout and acceptance procedure; P012 safety findings before any persistent-service trial.

**Deliverables:** read-only service status/doctor/plan, explicit privilege-checked lifecycle commands, launchctl capability reporting, secure managed-plist generation/validation, graceful shutdown acknowledgement, package-removal checks, deterministic tests, and a supervised device procedure.

**Safety constraints:** default remains disabled; no activation during package install; no hidden reboot/respring or power assertion; `KeepAlive=false` in managed configuration; no launchctl mutation while iOS 12.5.7 command syntax and semantics are unverified; no false success on assertion-release or cleanup failure.

**Validation and completion:** injected command-runner tests, package-script audits, disabled-by-default checks, exact-SHA CI, and supervised lifecycle acceptance with physical recovery. P013 cloud validation does not run a service operation. The staged template remains under `/usr/share/ioscaffeinate/`; the live profile is generated separately and uses `KeepAlive=false`. Hardware acceptance remains pending on P011 package acceptance, P012 safety review, direct recovery, and explicit operator authorization.

### P014 — Daemon crash recovery and restart-loop protection

**Depends on:** P013 lifecycle controls and P009 cleanup evidence.

**Deliverables:** bounded deterministic C11 restart eligibility policy, versioned exit classification, protected durable run journal, cleanup-aware assertion gate, read-only P013 diagnostics, crash and filesystem fault injection, exact-source CI evidence, and a supervised acceptance runbook.

**Safety constraints:** no production automatic restart or launchd mutation; `KeepAlive=false` remains in the managed profile; missing, corrupt, unclean, or uncertain recovery state blocks assertion acquisition; release failure and unknown assertion ownership remain blockers; no stale socket or absent PID is treated as cleanup confirmation.

**Validation and completion:** deterministic fault-injection tests, backoff and attempt-limit checks, journal ownership and atomic-write checks, schedule reacquisition regression tests, P013 fail-closed tests, and exact-head CI. Physical cleanup and supervisor behavior remain PENDING; cloud tests do not certify long-duration reliability. See [P014 validation](P014-VALIDATION.md).

### P015 — Server Mode v2 policy engine

**Depends on:** P012 research; P013 lifecycle controls; P014 recovery policy. P014 supplies a cleanup and recovery eligibility input only; it does not supply an active supervisor or verified automatic restart.

**Deliverables:** strict v2 schema with v1 compatibility, pure C11 bounded-session evaluation, deterministic reason codes, read-only show/validate/explain/plan, dry-run migration preview, filesystem/parser and negative policy tests, exact-source CI evidence, and a supervised read-only device procedure.

**Safety constraints:** policy presence does not start a session; no config writer or automatic migration; maximum session duration is 300 seconds; P014 cleanup remains authoritative; P013 lifecycle gates remain closed; no automatic launchd, daemon, assertion, schedule, network, or wake action; physical evidence must be current, reviewed, and P009-compatible.

**Validation and completion:** cloud policy/schema/filesystem/CLI tests and P009–P014 regressions can complete without the iPad. Exact-head CI records the final source SHA and simulated/mock scope. Missing device evidence keeps policy blocked or deferred. Physical procedure remains read-only until later separately authorized bounded trials; policy eligibility is not execution authorization.

### P016 — Health, battery and thermal monitoring

**Depends on:** P012 measurement protocol and P015 policy/diagnostic interfaces.

**Deliverables:** versioned native snapshots, on-demand CLI health commands, source/freshness metadata, iOS uptime, existing-daemon health reporting, and a strict P015 diagnostic adapter. P016 cloud engineering is implemented on stacked branch `ios/p016-health-telemetry`.

**Safety constraints:** no polling, persistent telemetry, private sensor interface, or battery-monitoring enablement. Battery percentage and charging remain unavailable; `NSProcessInfo.thermalState` is rejected because unknown or unsupported state maps to nominal. The iOS uptime adapter has not run on the reference iPad. Telemetry cannot pass a P009 gate, alter P014 cleanup rules, or enable unattended operation.

**Validation and completion:** deterministic native and CLI tests, P009/P012 compatibility checks, exact-SHA CI, and iOS ARM64 cross-build. Hardware runtime verification remains pending; any future battery/thermal acceptance needs a supported read-only source and reviewed P009 evidence. Reliability claims require P019.

### P017 — Timed and recurring schedule improvements

**Depends on:** P004 schedule behavior; P012 idle findings; P015 policy rules; P016 observation limits.

**Deliverables:** safer schedule editing, conflict and time-zone handling, recurrence diagnostics, and explicit behavior when the daemon is not running.

**Safety constraints:** schedules do not wake a suspended device; no alarm-clock promise; existing persisted schedules are migrated without destructive defaults.

**Validation and completion:** date/time boundary tests, migration and recovery tests, plus attended target-device schedule trials. Scheduled wake remains unverified unless directly observed and reviewed.

### P018 — CLI and package-manager user experience

**Depends on:** accepted P011 layout and the interfaces delivered by P013–P017.

**Deliverables:** consistent help and errors, safe manager diagnostics, actionable install/upgrade/removal guidance, and evidence export commands.

**Safety constraints:** diagnostics stay read-only unless a command name and prompt make the state change explicit; no destructive default or credential capture.

**Validation and completion:** CLI golden tests, shell compatibility tests, package-manager simulations, and a supervised upgrade/rollback walkthrough.

### P019 — Supervised reliability and endurance validation

**Depends on:** accepted P011 package; P012 protocol; P013/P014 lifecycle; P015 policy; P016 observability; P017 schedules; P018 operating instructions.

**Deliverables:** versioned endurance plan, failure criteria, battery/thermal/network evidence, incident handling, and a P009 evidence bundle.

**Safety constraints:** operator attendance and physical recovery; bounded trials; stop on uncertain assertion cleanup, thermal concern, or state corruption. No unattended testing without a separately reviewed safety plan.

**Validation and completion:** repeated target-device sessions across the agreed duration and conditions, independent evidence review, and explicit limitations. Passing a CI suite or one attended trial does not certify production reliability.

### P020 — Integration, security hardening and v0.2 release

**Depends on:** P011–P019 implementation and acceptance criteria; no unresolved release-blocking security findings.

**Deliverables:** integrated source, release notes, exact-source CI, signed package and manifests, evidence review, migration/rollback instructions, and a release-readiness decision.

**Safety constraints:** do not publish a v0.2 tag or release until required hardware and reliability gates are separately reviewed; keep the Amethyst entitlement opt-in and environment-specific.

**Validation and completion:** all cloud gates pass on the final source SHA; P009 hardware gates and P019 reliability evidence receive human review; package identity and rollback are checked. A v0.2 release remains blocked until those criteria are met.

## Dependency summary

```text
P011 ──┬──> P012 ──> P015 ──> P016 ──> P017 ──┐
       └──> P013 ──> P014 ──> P015            ├──> P019 ──> P020
P004 ───────────────────────────────> P017     │
P011 ───────────────────────────────> P018 ────┘
```

P012 cloud engineering is complete on stacked branch `ios/p012-controlled-idle-power-research` while P011 physical package testing remains pending. P012 device experiments, and every later state-changing device trial, still depend on P011 package acceptance and a confirmed physical recovery path. P019 production reliability certification is a separate gate from feature implementation and from v0.1.0's public stable channel.

P012 preserves the P009 event vocabulary and records the P009 v1 mapping limitation rather than changing historical acceptance semantics. The October 18, 2026 observations remain operator-reported, used manually staged binaries, lack a no-assertion baseline, and are not P012 trial data. See [P012 research questions](P012-RESEARCH-QUESTIONS.md), [protocol](P012-EXPERIMENT-PROTOCOL.md), [operator runbook](P012-OPERATOR-RUNBOOK.md), [measurement format](P012-MEASUREMENT-FORMAT.md), [analysis](P012-ANALYSIS.md), [evidence matrix](P012-EVIDENCE-MATRIX.md), [validation](P012-VALIDATION.md), and [manifest](P012-MANIFEST.md).
