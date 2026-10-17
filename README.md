# iOS-Caffeinate

Native C11 CLI and daemon for rootful jailbroken iOS 12.5.7 (Amethyst/Procursus), targeting iPad mini 2 A1489 / Apple A7 ARM64. P003 provides the daemon lifecycle and IPC security; P004 adds bounded timed awake and persisted schedule evaluation. P005 adds a read-only scheduled-wake capability report. P006 adds read-only server diagnostics, explicit bounded trials, health observations, readiness gates, and an external connectivity evidence schema. P007 adds rootful Debian packaging and safety checks. Real-device assertion, schedule, sleep, package installation, and networking behavior remain **PENDING** because the iPad is unavailable.

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

P006 does not authorize unattended operation. The default server policy is `DISABLED`; missing, corrupt, or unsafe configuration fails closed. Hardware gates remain pending. Read [server-mode behavior](docs/P006-SERVER-MODE.md) and the [deferred device procedure](docs/P006-DEVICE-TEST.md) before any future iPad trial.

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

Outputs: `dist/ios-caffeinate`, `dist/ios-caffeinated`, relative symlink `dist/ic -> ios-caffeinate`, and `dist/SHA256SUMS`. CI uploads the **UNSIGNED, HARDWARE-UNVERIFIED** binaries, inspection report, and rootful `.deb` with checksums. The default build does not sign, install, deploy, or activate a service. The package builder can run an explicitly requested local `ldid -S` stage; see [P007 packaging](docs/P007-PACKAGING.md).

## Rootful package

P007 defines package `com.ioscaffeinate.cli` version `0.1.0-1`, Debian architecture `iphoneos-arm`, and thin ARM64 iOS 12.0 executables. The package architecture is distinct from the binaries' ARM64 CPU architecture. It carries unsigned binaries in CI, a genuine `ic` symlink, docs, a read-only manager, empty persistent/log directories, and the disabled launchd template staged under `/usr/share/ioscaffeinate/`. It does not activate launchd or seed server/schedule configuration. The manager is installed at `/usr/local/libexec/ioscaffeinate-manager`, outside writable state directories.

Read [P007 packaging](docs/P007-PACKAGING.md), [validation](docs/P007-VALIDATION.md), [deferred device test](docs/P007-DEVICE-TEST.md), and [rollback](docs/P007-ROLLBACK.md) before using an artifact. The CI `.deb` is **UNSIGNED / DEVICE-UNVERIFIED**. Its archive and checksums are cloud evidence only; installation, signature acceptance, execution, assertion behavior, screen-locked connectivity, and 24/7 operation remain pending.

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

## Scope and evidence

Timed holds and scheduled awake windows are bounded to 24 hours. P004 schedule evaluation requires the daemon to be running; it does not wake a suspended system. There is no indefinite mode, GUI, tweak injection, Apple daemon change, scheduled-wake command, or automatic installation. P005 makes no 24/7 unattended reliability claim. P006 provides engineering and diagnostics only; all hardware gates remain pending. P007 cloud packaging engineering is implemented, but device validation remains pending. Package success does not authorize unattended operation.

See [architecture](docs/ARCHITECTURE.md), [roadmap](docs/PLAN.md), [P007 package contract](docs/P007-PACKAGING.md), [P007 validation](docs/P007-VALIDATION.md), [P007 deferred device procedure](docs/P007-DEVICE-TEST.md), [P007 rollback](docs/P007-ROLLBACK.md), [P006 server-mode design](docs/P006-SERVER-MODE.md), [P006 validation](docs/P006-VALIDATION.md), [deferred P006 device tests](docs/P006-DEVICE-TEST.md), [P005 feasibility report](docs/P005-WAKE-FEASIBILITY.md), [P005 validation](docs/P005-VALIDATION.md), [deferred P005 device tests](docs/P005-DEVICE-TEST.md), [P004 schedule details](docs/P004-SCHEDULING.md), and earlier [device recovery instructions](docs/P003-DEVICE-TEST.md).
