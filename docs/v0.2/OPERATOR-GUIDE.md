# iOS-Caffeinate Operator Guide

Use this guide for inspection and supervised operations on the rootful iOS 12.5.7 device. Read-only diagnostics do not establish hardware acceptance. P013 launchd behavior, P014 cleanup, and P017 schedule execution remain gated as documented.

## 1. Check installation

**Read-only:**

```sh
ic --version
ic package status
ic package verify
```

Review package identity, `iphoneos-arm`, checksums, file ownership, signing metadata, and device acceptance separately. A checksum pass does not prove signer trust or iOS acceptance.

## 2. Check daemon and recovery

**Read-only:**

```sh
ic service status
ic service doctor
ic service recovery status
ic doctor
```

Daemon IPC unavailable can mean no daemon is present, but an unsafe or unknown service/socket/launchd state requires separate inspection. Do not automatically start the daemon or reset recovery. P014 has no production automatic restart executor.

## 3. Read Server Mode readiness

**Read-only:**

```sh
ic server status
ic server doctor
ic server policy validate
ic server policy explain
```

Policy eligibility is not execution authorization. Bounded trials have a maximum of 300 seconds and are assertion-changing. There is no unattended server executor or 24/7 SSH guarantee.

## 4. Read schedule diagnostics

**Read-only:**

```sh
ic schedule validate
ic schedule doctor
ic schedule list
ic schedule next
```

P017 previews occurrences but does not execute them. Scheduled wake remains unverified. New schedule definitions are capped at 300 seconds; legacy longer entries are preserved and reported.

## 5. Read health sources

**Read-only:**

```sh
ic health status
ic health sources
```

Battery and thermal data may be unavailable. Do not substitute zero, nominal, or an inferred value.

## 6. Verify package integrity and plan upgrade

**Read-only:**

```sh
ic package verify
ic package upgrade-check "/absolute/path/to/candidate.deb"
```

Include an available prior artifact for rollback review:

```sh
ic package upgrade-check "/absolute/path/to/candidate.deb" --rollback-artifact "/absolute/path/to/previous.deb"
```

`READY_FOR_OPERATOR_REVIEW` is not install authorization. The planner does not install, extract into privileged paths, execute package scripts, mutate launchd, or start a daemon.

## 7. Prepare rollback review

**Read-only:**

```sh
ic package rollback-check "/absolute/path/to/previous.deb"
ic package uninstall-check
```

Read `rollback.readiness` and every blocker; the legacy rollback-check exit code only covers artifact checksum/basic metadata. Preserve schedules, policy, evidence, and logs. Do not remove unknown launchd state, stale sockets, or recovery files to make a check pass.

## 8. Inventory and export diagnostics

**Read-only:**

```sh
ic evidence status
ic evidence inventory --json
ic evidence validate
ic evidence export --dry-run
```

After privacy review, explicitly create a new export directory. **Writes diagnostic files:**

```sh
ic evidence export --output "/var/root/ioscaffeinate-p018-export"
python3 /usr/share/doc/ioscaffeinate/tools/p018_validate_export.py "/var/root/ioscaffeinate-p018-export"
```

Review the manifest and every included file before sharing. `EXPORT_CREATED` does not mean `HARDWARE_EVIDENCE_ACCEPTED`; P009 review remains required.

## 9. Report an incident

**Read-only collection first:** save the output of `ic --version`, `ic doctor`, package/service/recovery status, the relevant schedule/policy/health result, and evidence inventory. Preserve exact output and timestamps. Do not include private keys, credentials, SSH logs, tokens, process environments, or unrelated application files. Create and share an export only after explicit privacy review.

## Operation labels

- **Read-only:** status, doctor, validation, package planning, evidence inventory, export dry-run.
- **Configuration-changing:** schedule edits and existing service/policy configuration commands.
- **Assertion-changing:** `probe`, manual `start`/`stop`, and `server trial start/stop`.
- **Package-changing:** actual installation/removal/downgrade; not provided by P018 and requires separate authorization.
- **Unsupported/unverified:** launchd activation semantics, scheduled execution/wake, automatic restart, unattended server mode, and hardware/endurance claims.

## Device acceptance

Initial attended inspection commands are listed in [P018 device acceptance](P018-DEVICE-ACCEPTANCE.md). Do not reboot/respring or perform unattended power tests during P018. Current outcome: `P018_CLOUD_COMPLETE_DEVICE_UX_PENDING`.

## P019 next milestone

P019 should be a separately authorized, supervised endurance study after P011 package/signer provenance and P013/P014 runtime gates are reviewed. Preregister duration, screen/charging/network conditions, comparison periods, battery/thermal criteria, observation cadence, assertion acquisition/release and cleanup criteria, and abort/recovery steps. Capture genuine P009 device and independent-observer records, including failure/cleanup events. Fail if cleanup is unresolved, state/provenance is ambiguous, safety limits are crossed, or observations cannot be attributed to the exact build. P018's bounded export can carry sanitized snapshots and validated P009 records to a reviewer; it cannot itself pass a hardware gate.
