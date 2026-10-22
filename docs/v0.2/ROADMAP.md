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

**Deliverables:** preregistered A/B/C/D conditions, measurement protocol, confounder controls, and an analysis that separates daemon availability, assertion state, display lock, LAN, and Tailscale.

**Safety constraints:** attended trials only; bounded assertions; quiet idle intervals before sparse probes; no implication that SSH reachability proves prevention of sleep.

**Validation and completion:** cloud protocol review can complete independently. Device results need separate LAN and Tailscale observations, a no-assertion baseline, timebase and uncertainty records, cleanup evidence, and P009 review. P012 must not claim battery, thermal, or sleep-prevention effects from connectivity alone.

### P013 — Opt-in LaunchDaemon lifecycle management

**Depends on:** P011 package layout and acceptance procedure; P012 safety findings before any persistent-service trial.

**Deliverables:** explicit opt-in install/enable/disable/status actions, ownership and plist validation, and an uninstall path that preserves user data.

**Safety constraints:** default remains disabled; no activation during package install; no hidden reboot/respring; no service action unless the operator requests it.

**Validation and completion:** mocked lifecycle tests, package-script audits, disabled-by-default checks, and a supervised manual enable/disable trial with physical recovery. The staged template remains under `/usr/share/ioscaffeinate/` until P013 is accepted.

### P014 — Daemon crash recovery and restart-loop protection

**Depends on:** P013 lifecycle controls and P009 cleanup evidence.

**Deliverables:** bounded restart policy, crash classification, backoff, observable loop protection, and explicit stop behavior.

**Safety constraints:** never restart into an indefinite assertion; restart limits fail closed; a failed release remains visible and blocks another trial.

**Validation and completion:** fault-injection tests, restart-loop limits, state-recovery checks, and attended crash/restart trials. CI fault tests do not certify long-duration reliability.

### P015 — Server Mode v2 policy engine

**Depends on:** P012 research; P013 lifecycle controls; P014 restart safeguards.

**Deliverables:** versioned policy evaluation for bounded server sessions, explicit readiness reasons, policy migration, and a read-only explain/doctor path.

**Safety constraints:** opt-in policy, conservative defaults, no hidden indefinite hold, and no automatic interpretation of network reachability as proof of awake state.

**Validation and completion:** policy unit/property tests, migration tests, negative configuration cases, and supervised policy transitions on the target device.

### P016 — Health, battery and thermal monitoring

**Depends on:** P012 measurement protocol and P015 policy/diagnostic interfaces.

**Deliverables:** read-only health snapshots, battery and thermal observations where iOS exposes them, data freshness and unavailable-state reporting.

**Safety constraints:** no polling that keeps the device awake, no unsupported private API assumptions, and no battery/thermal safety claims from a single trial.

**Validation and completion:** deterministic parser tests and documented sampling bounds; device acceptance requires repeated attended measurements and P009 evidence. Reliability claims require P019.

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

P012 cloud protocol work can start while P011 physical package testing is pending. P012 device experiments, and every later state-changing device trial, still depend on P011 package acceptance and a confirmed physical recovery path. P019 production reliability certification is a separate gate from feature implementation and from v0.1.0's public stable channel.
