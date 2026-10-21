# iOS-Caffeinate

Native C11 CLI and daemon for rootful jailbroken iOS 12.5.7 (Amethyst/Procursus), targeting iPad mini 2 A1489 / Apple A7 ARM64. P003 provides daemon lifecycle and IPC security; P004 adds bounded timed awake and persisted schedule evaluation. P005 adds read-only scheduled-wake diagnostics. P006 adds server diagnostics, bounded trials, health observations, readiness gates, and connectivity evidence. P007 adds rootful Debian packaging. P008 integrates P001–P007; P009 adds offline evidence review. The public GitHub stable release **v0.1.0** has shipped with package `com.ioscaffeinate.cli` version `0.1.0-1`; this release-channel designation does not mean the installed Debian package passed hardware acceptance. On October 18, 2026, the operator reported successful target-device execution with an explicit private no-container entitlement, IOKit assertion lifecycle, cleanup, and locked-screen LAN/Tailscale SSH observations. Those results still need P009 evidence review. Stable package installation, installed-binary execution, rollback, the no-assertion comparison, battery/thermal behavior, scheduled wake, and long-duration reliability remain pending or unverified. The project is not production reliability certified.

Executables: **ios-caffeinate** (CLI), **ios-caffeinated** (daemon). **ic** is a filesystem symlink to the CLI, never a second executable or shell alias. The socket remains `/var/run/ioscaffeinated.sock`.

## Manual use

The following report is local and does not require the daemon or alter power state:

```sh
ic wake status
```

It reports `scheduled_wake=unverified` and `wake_guarantee=no`. It never sets an alarm. Run P004 power commands on the target only after following [the P004 hardware procedure](docs/P004-DEVICE-TEST.md):

```sh
ios-caffeinate probe
ios-caffeinate status
ios-caffeinate start --for 5m
ios-caffeinate schedule list
ios-caffeinate status
ios-caffeinate stop
```

With the symlink in PATH, `ic probe`, `ic status`, `ic start --for 5m`, schedule commands, and `ic stop` run the same CLI. First hardware trials must be bounded to five minutes or less, with physical recovery available. A successful assertion call does not prove Wi-Fi, LAN SSH, Tailscale, or scheduled wake.

P006 server diagnostics are read-only and do not acquire assertions or probe networks:

```sh
ic server status
ic server doctor
ic server plan
```

An explicit server trial is capped at five minutes and is intended for the future physical validation procedure only:

```sh
ic server trial start --for 1m
ic server trial stop
```

P006 does not authorize unattended operation. The default server policy is `DISABLED`; missing, corrupt, or unsafe configuration fails closed. Read [server-mode behavior](docs/P006-SERVER-MODE.md) and the [P010 device acceptance procedure](docs/P010-DEVICE-ACCEPTANCE.md) before any package trial.

## Build and tests

Linux tests explicitly compile `IOSCAFFEINATE_TEST_MOCK`; this backend has **NO POWER EFFECT** and is never an iOS fallback:

```sh
./scripts/build-linux-test.sh
python3 tests/integration.py
python3 -m unittest discover -s tests/packaging -v
```

macOS with Xcode and the official **iPhoneOS** SDK:

```sh
./scripts/build-macos.sh
python3 scripts/inspect-ios.py
```

Outputs: `dist/ios-caffeinate`, `dist/ios-caffeinated`, relative symlink `dist/ic -> ios-caffeinate`, and `dist/SHA256SUMS`. CI records the Xcode, iPhoneOS SDK, and Clang identifiers. CI artifacts remain **UNSIGNED, HARDWARE-UNVERIFIED**. Signing requires an explicitly supplied host-compatible `ldid` and the exact approved profile; see [P010 signing](docs/P010-SIGNING.md). No automatic install or service activation occurs.

## Rootful package

The P010 release candidate used package `com.ioscaffeinate.cli` version `0.1.0~rc1-1`; the published v0.1.0 stable package is version `0.1.0-1`. Both use Debian architecture `iphoneos-arm` and thin ARM64 iOS 12.0 executables. The Debian package architecture is distinct from the binaries' ARM64 CPU architecture. The stable package includes a genuine `ic` symlink, docs, a read-only manager, empty persistent/log directories, and the inactive launchd template under `/usr/share/ioscaffeinate/`. It does not activate launchd or seed server/schedule configuration. The manager is installed at `/usr/local/libexec/ioscaffeinate-manager`, outside writable state directories. The official package SHA-256 is `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c`.

Read [P010 signing](docs/P010-SIGNING.md), [package validation](docs/P010-PACKAGING-VALIDATION.md), and [device acceptance](docs/P010-DEVICE-ACCEPTANCE.md) before using an artifact. CI `.deb` files remain **UNSIGNED / DEVICE-UNVERIFIED**. A locally signed package is not device-accepted until the supervised installation gates pass.

## Rootful installation layout

| Component | Path |
|---|---|
| CLI | `/usr/local/bin/ios-caffeinate` |
| Daemon | `/usr/local/bin/ios-caffeinated` |
| CLI symlink | `/usr/local/bin/ic -> /usr/local/bin/ios-caffeinate` |
| Read-only manager | `/usr/local/libexec/ioscaffeinate-manager` |
| Project data | `/var/lib/ioscaffeinate/` |
| Logs | `/var/log/ioscaffeinate/` |
| IPC socket | `/var/run/ioscaffeinated.sock` |
| Staged launchd template | `/usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist` |
| Future live launchd path | `/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist` (not installed or activated by P007) |

A `0600` socket sidecar lock (`/var/run/ioscaffeinated.sock.lock`) serializes manual daemon instances. It is left in place to avoid lock inode races. The default endpoint requires root and verifies peer credentials (`getpeereid` / `SO_PEERCRED`); mock tests use private temporary directories without root.

The project launchd template remains disabled (`Disabled=true`, `RunAtLoad=false`) and is staged outside the active LaunchDaemons directory. P007 does not load, enable, or start a persistent service. Package lifecycle scripts only reject unsafe file collisions and a present default daemon endpoint; they do not stop processes or modify user data.

## P008 v0.1 cloud candidate

P008 audits the integrated source and package, requires the Linux protocol, official iPhoneOS SDK cross-build, artifact-inspection, and rootful-package jobs, and generates a manifest from that workflow run's actual hashes. The manifest reports its exact source SHA, toolchain, workflow ID, and package checksum. The generated release-readiness matrix keeps hardware gates separate from cloud validation. See [P008 integration](docs/P008-INTEGRATION.md), [validation](docs/P008-VALIDATION.md), [release readiness](docs/P008-RELEASE-READINESS.md), [device acceptance plan](docs/P008-DEVICE-ACCEPTANCE.md), and [backlog](docs/P008-BACKLOG.md).

Passing cloud jobs establish a reviewable engineering candidate only. They do not authorize a production release, device installation, automatic daemon activation, an indefinite hold, or a public release. Scheduled wake remains unverified.

## P009 device acceptance harness

P009 supplies a versioned evidence schema, deterministic manifest builder, offline validator, timeline replay, and gate report. It is fully separate from the production daemon and never contacts the device. Use explicit paths:

```sh
python3 scripts/p009_evidence.py validate /path/to/evidence
python3 scripts/p009_evidence.py replay /path/to/evidence --json
python3 scripts/p009_evidence.py report /path/to/evidence --format json
```

Mock, simulated, and CI evidence cannot pass hardware gates. The October 18, 2026 device observations are operator-reported and remain `REVIEW_REQUIRED`; package integrity, installation, and rollback are `INSUFFICIENT_EVIDENCE`. Current gates are in [P010 release readiness](docs/P010-RELEASE-READINESS.md), [operator findings](docs/P010-HARDWARE-FINDINGS.md), and the [P009 evidence format](docs/P009-EVIDENCE-FORMAT.md). `unattended_24_7=NOT_VALIDATED` and `scheduled_wake=UNVERIFIED` remain unchanged.

## P010 hardware signing and RC1

P010 adds the opt-in `amethyst-ios12-rootful` profile, exact entitlement extraction, source-to-signed-binary identity checks, final `.deb` validation, operator-reported evidence bundling, and the `v0.1.0-rc1` release process. The Debian version `0.1.0~rc1-1` sorts before `0.1.0-1`. The exact-source CI release manifest is an Actions artifact; it is not a signed installation package. See [P010 validation](docs/P010-VALIDATION.md) and [RC1 draft notes](docs/releases/v0.1.0-rc1.md).

The subsequent public [v0.1.0 stable release](https://github.com/nghianguyen150612/iOS-Caffeinate/releases/tag/v0.1.0) contains a separately signed `SIGNED-DEVICE-UNVERIFIED` Debian package. Signature integrity remains `PENDING`; the stable package has not been installed or accepted on the reference iPad.

## P011 and v0.2 roadmap

P011 verifies the published stable artifact and prepares a read-only device preflight and supervised acceptance procedure. Its physical installation, installed-binary, rollback, power, and reliability gates remain pending. See the [v0.2 roadmap](docs/v0.2/ROADMAP.md), [P011 device procedure](docs/v0.2/P011-DEVICE-ACCEPTANCE.md), [evidence matrix](docs/v0.2/P011-EVIDENCE-MATRIX.md), and [validation commands](docs/v0.2/P011-VALIDATION.md).

## P012 controlled idle research

P012 adds a preregistered A/B/C/D research protocol, an inert-by-default host SSH probe, an operator record controller, a deterministic offline analyzer, and a conservative P009 v1 event mapper. The probe requires `--run-attended`, an operator-supplied destination, a completed quiet period, locked-screen/state confirmations, P011 package/runtime prerequisites, and direct recovery before it can connect. Tests use subprocess mocks. P012 does not automate device operations, infer assertion cleanup, or claim that SSH or an IOKit API call proves OS sleep behavior. No P012 hardware trials were run during cloud engineering.

P011 installed-package acceptance and its exact `ldid` provenance gate remain pending, so the iPad procedure is not ready to run. The October 18 operator observations remain separate operator-reported evidence and are not P012 trial data. See [P012 questions](docs/v0.2/P012-RESEARCH-QUESTIONS.md), [protocol](docs/v0.2/P012-EXPERIMENT-PROTOCOL.md), [operator runbook](docs/v0.2/P012-OPERATOR-RUNBOOK.md), [measurement format](docs/v0.2/P012-MEASUREMENT-FORMAT.md), [analysis](docs/v0.2/P012-ANALYSIS.md), [evidence matrix](docs/v0.2/P012-EVIDENCE-MATRIX.md), [validation](docs/v0.2/P012-VALIDATION.md), and [manifest](docs/v0.2/P012-MANIFEST.md).

## P013 opt-in service management

P013 adds `ic service status`, `doctor`, and `plan` as read-only diagnostics, plus explicit `enable`, `disable`, `start`, `stop`, and `restart` entry points. The immutable packaged LaunchDaemon template remains staged and disabled; it is never copied or activated by package installation. The separately generated managed profile uses `KeepAlive=false` to avoid an uncontrolled crash relaunch loop.

iOS 12.5.7 launchctl mutation syntax and semantics remain **UNVERIFIED** until a supervised device investigation. P013 reports `help`/`list` observations but does not assume modern macOS domains. `enable`, `disable`, `start`, and `restart` fail closed while compatibility is unverified. `stop` requires confirmed managed registration and daemon IPC and uses an acknowledged graceful shutdown that confirms assertion release; uncertain state is not treated as success. Service registration does not create a power assertion and does not prove that iPadOS remains awake or that SSH is reachable.

P011 stable-package acceptance and P012 safety review are prerequisites to any physical P013 lifecycle trial. No device service operation or reboot has been run during cloud engineering. See [P013 architecture](docs/v0.2/P013-ARCHITECTURE.md), [launchd compatibility](docs/v0.2/P013-LAUNCHD-COMPATIBILITY.md), [service states](docs/v0.2/P013-SERVICE-STATES.md), [security](docs/v0.2/P013-SECURITY.md), [packaging](docs/v0.2/P013-PACKAGING.md), [device acceptance](docs/v0.2/P013-DEVICE-ACCEPTANCE.md), [rollback](docs/v0.2/P013-ROLLBACK.md), [validation](docs/v0.2/P013-VALIDATION.md), and [manifest](docs/v0.2/P013-MANIFEST.md).

## P014 crash recovery policy

P014 adds a separate bounded recovery policy and a root-owned durable run journal. An unclean, missing, corrupt, or unsafe recovery record, or a release failure awaiting review, blocks scheduled and manual assertion acquisition until explicit attended cleanup review. Read-only `ic service recovery status` and `plan` report recovery state, budget, cooldown, cleanup confidence, blocker, supervisor compatibility, and runtime activation. The explicit `recovery reset --reviewed-cleanup --reviewed-supervisor-state` operation records an operator review; it does not perform cleanup or collect device evidence.

P014 does not perform an automatic restart. `ELIGIBLE_FOR_ATTENDED_START` is a policy result only; `automatic_restart=no`. P013 `enable`, `start`, and `restart` remain fail-closed pending iOS 12 launchd compatibility, no launchd job is enabled, and the managed profile retains `KeepAlive=false`. Crash detection, exit classification, assertion cleanup, restart eligibility, actual process restart, launchd boot persistence, SSH reachability, OS awake state, and long-duration reliability remain separate capabilities. Device recovery remains pending. See [P014 architecture](docs/v0.2/P014-ARCHITECTURE.md), [restart policy](docs/v0.2/P014-RESTART-POLICY.md), [persistence](docs/v0.2/P014-PERSISTENCE.md), [security](docs/v0.2/P014-SECURITY.md), [schedule interaction](docs/v0.2/P014-SCHEDULE-INTERACTION.md), [device acceptance](docs/v0.2/P014-DEVICE-ACCEPTANCE.md), [validation](docs/v0.2/P014-VALIDATION.md), and [manifest](docs/v0.2/P014-MANIFEST.md).

## P015 Server Mode v2 policy

P015 adds strict schema v2 while preserving v1 `disabled` and `observe_only`. The `bounded_session` setting is only a policy request; it never starts a daemon, creates an assertion, enables launchd, resumes after a crash, or creates a schedule. Eligibility requires current reviewed P009-compatible physical evidence, a safe P014 recovery journal, no conflicting assertion, operator attendance, physical recovery, and known battery/thermal safety.

Use read-only policy diagnostics:

```sh
ic server policy show
ic server policy validate
ic server policy explain
ic server policy plan
ic server policy migrate --dry-run
```

There is no `apply` command. Migration is preview-only and preserves v1 files. The 300-second maximum is the ceiling for a future separately authorized manual session. `ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION` does not grant execution authorization.

Illustrative simulated report; it is not device output:

```text
policy.mode=BOUNDED_SESSION
policy.config_valid=yes
decision=BLOCK_RECOVERY
eligible=no
execution_authorized=no
runtime_activated=UNKNOWN
recovery.journal=MISSING
recovery.supervisor=UNVERIFIED
evidence.battery_safety.state=PENDING
evidence.thermal_safety.state=PENDING
next_safe_step=resolve the P014 recovery blocker and review recovery status
```

P015 cloud completion is `P015_CLOUD_COMPLETE_DEVICE_POLICY_PENDING` until hardware evidence is separately reviewed. The P016 adapter supplies explicit source, freshness, and availability metadata to P015 diagnostics without turning a sensor value into reviewed P009 evidence. See [P015 architecture](docs/v0.2/P015-ARCHITECTURE.md), [schema](docs/v0.2/P015-POLICY-SCHEMA.md), [states](docs/v0.2/P015-POLICY-STATES.md), [decision matrix](docs/v0.2/P015-DECISION-MATRIX.md), [migration](docs/v0.2/P015-CONFIG-MIGRATION.md), [recovery integration](docs/v0.2/P015-RECOVERY-INTEGRATION.md), [security](docs/v0.2/P015-SECURITY.md), [device procedure](docs/v0.2/P015-DEVICE-ACCEPTANCE.md), [validation](docs/v0.2/P015-VALIDATION.md), and [manifest](docs/v0.2/P015-MANIFEST.md).

## P016 health diagnostics

P016 adds on-demand, read-only health diagnostics:

```sh
ic health status
ic health battery
ic health thermal
ic health doctor
ic health sources
```

For an explicitly associated P012 observation outside a quiet interval, use `ic health status --trial-id <id> --condition-id A|B|C|D --outside-quiet-interval`. This labels the output only; it does not save a P012 record or supply the independent host timestamp.

For an available current observation, `scripts/p016_p009_adapter.py` can print a P009 v1 `BATTERY_OBSERVATION` or `THERMAL_OBSERVATION` event fragment with `--event-id` and `--sequence`. The optional P012 association also requires `--outside-quiet-interval`. The adapter never writes a session or marks evidence accepted; current iOS battery and thermal sources return unavailable and therefore produce no event.

The iOS adapter reports device uptime through `mach_continuous_time` and uses the existing `SERVER STATUS` IPC for daemon lifecycle details. Battery and charging remain `UNAVAILABLE` because UIKit reports unknown when monitoring is disabled and enabling it would mutate process state. Thermal remains `UNAVAILABLE` because the iOS 12 `NSProcessInfo.thermalState` API maps unknown or unsupported state to `NOMINAL`. No temperature is inferred. `battery` and `thermal` return exit code 3 when their source is unavailable. All target API runtime behavior remains unverified until the iPad procedure is completed.

Simulated host output (Linux `MOCK`; not device evidence):

```text
health.platform=MOCK_NO_SENSOR_DATA
battery.percentage=UNAVAILABLE
battery.charging=UNKNOWN
thermal.state=UNKNOWN
health.polling=ON_DEMAND
```

P016 cloud engineering status is `P016_CLOUD_COMPLETE_DEVICE_TELEMETRY_PENDING`. It does not poll in the background, persist measurements, acquire assertions, activate launchd, or enable unattended Server Mode. P009 v1 and P012 remain unchanged. See [P016 architecture](docs/v0.2/P016-ARCHITECTURE.md), [schema](docs/v0.2/P016-TELEMETRY-SCHEMA.md), [iOS 12 capabilities](docs/v0.2/P016-IOS12-CAPABILITY-MATRIX.md), [battery](docs/v0.2/P016-BATTERY.md), [thermal](docs/v0.2/P016-THERMAL.md), [freshness](docs/v0.2/P016-FRESHNESS.md), [policy integration](docs/v0.2/P016-POLICY-INTEGRATION.md), [security](docs/v0.2/P016-SECURITY.md), [device acceptance](docs/v0.2/P016-DEVICE-ACCEPTANCE.md), [validation](docs/v0.2/P016-VALIDATION.md), and [manifest](docs/v0.2/P016-MANIFEST.md).

## Scope and evidence

Timed holds and scheduled awake windows are bounded to 24 hours. P004 schedule evaluation requires the daemon to be running; it does not wake a suspended system. There is no indefinite mode, GUI, tweak injection, Apple daemon change, scheduled-wake command, or automatic installation. The reported IOKit success does not establish scheduled wake or prevention of deep sleep. Battery/thermal characterization, causal network comparison, package acceptance, rollback, and unattended 24/7 reliability remain open. Package success does not authorize unattended operation.

See [architecture](docs/ARCHITECTURE.md), [roadmap](docs/PLAN.md), [P008 integration and evidence](docs/P008-INTEGRATION.md), [P009 evidence format](docs/P009-EVIDENCE-FORMAT.md), [P009 security](docs/P009-SECURITY.md), [P009 validation](docs/P009-VALIDATION.md), [P009 device runbook](docs/P009-DEVICE-RUNBOOK.md), [P007 package contract](docs/P007-PACKAGING.md), [P007 validation](docs/P007-VALIDATION.md), [P007 deferred device procedure](docs/P007-DEVICE-TEST.md), [P007 rollback](docs/P007-ROLLBACK.md), [P006 server-mode design](docs/P006-SERVER-MODE.md), [P006 validation](docs/P006-VALIDATION.md), [deferred P006 device tests](docs/P006-DEVICE-TEST.md), [P005 feasibility report](docs/P005-WAKE-FEASIBILITY.md), [P005 validation](docs/P005-VALIDATION.md), [deferred P005 device tests](docs/P005-DEVICE-TEST.md), [P004 schedule details](docs/P004-SCHEDULING.md), and earlier [device recovery instructions](docs/P003-DEVICE-TEST.md).
