# iOS-Caffeinate

Native C11 CLI and daemon for rootful jailbroken iOS 12.5.7 (Amethyst/Procursus), targeting iPad mini 2 A1489 / Apple A7 ARM64. P003 implements a robust daemon lifecycle, state machine, Unix IPC security with peer credential verification, efficient poll event loops, and bounded release retries. Real-device power and networking behavior remain **PENDING** due to physical device unavailability.

Executables: **ios-caffeinate** (CLI), **ios-caffeinated** (daemon). **ic** is a filesystem symlink to the CLI, never a second executable or shell alias. The socket remains `/var/run/ioscaffeinated.sock`.

## Manual use

Run as root on the target only after following [the safe hardware procedure](docs/P003-DEVICE-TEST.md). Start `ios-caffeinated --foreground` in one shell, then in another:

```sh
ios-caffeinate probe
ios-caffeinate status
ios-caffeinate start --for 5m
ios-caffeinate status
ios-caffeinate stop
```

With the symlink in PATH, `ic probe`, `ic status`, `ic start --for 5m`, and `ic stop` run the same CLI. First trials must be bounded to five minutes or less, with physical recovery available. A successful assertion call does not prove Wi-Fi, LAN SSH, or Tailscale survives display lock.

## Build and tests

Linux tests explicitly compile `IOSCAFFEINATE_TEST_MOCK`; this backend has **NO POWER EFFECT** and is never an iOS fallback:

```sh
./scripts/build-linux-test.sh
python3 tests/integration.py
```

macOS with Xcode and the official **iPhoneOS** SDK:

```sh
./scripts/build-macos.sh
python3 scripts/inspect-ios.py
```

Outputs: `dist/ios-caffeinate`, `dist/ios-caffeinated`, and relative symlink `dist/ic -> ios-caffeinate`. CI uploads the two **UNSIGNED, HARDWARE-UNVERIFIED** binaries and a separate Mach-O inspection report. Recreate `ic` after downloading; artifact archives need not preserve permissions or symlinks. No build step signs, installs, deploys, or activates a service.

## Planned rootful installation layout

| Component | Path |
|---|---|
| CLI | `/usr/local/bin/ios-caffeinate` |
| Daemon | `/usr/local/bin/ios-caffeinated` |
| CLI symlink | `/usr/local/bin/ic -> /usr/local/bin/ios-caffeinate` |
| Manager (planned) | `/var/lib/ioscaffeinate/manager.sh` |
| Installation state (planned) | `/var/lib/ioscaffeinate/install-state` |
| Project data | `/var/lib/ioscaffeinate/` |
| Logs (planned) | `/var/log/ioscaffeinate/` |
| IPC socket | `/var/run/ioscaffeinated.sock` |
| LaunchDaemon template | `/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist` |

A `0600` socket sidecar lock (`/var/run/ioscaffeinated.sock.lock`) serializes manual daemon instances. It is left in place to avoid lock inode races. The default endpoint requires root and verifies peer credentials (`getpeereid` / `SO_PEERCRED`); mock tests use private temporary directories without root.

The launchd template remains disabled (`Disabled=true`) and must not be installed, loaded, bootstrapped, or enabled during P003. Manager, installer state, log directories and final `.deb` packaging are future components, not created by P003.

## Scope and evidence

Commands support bounded holds from 1 second through 24 hours. No indefinite mode, GUI, tweak injection, Apple daemon changes, schedules, `--until`, or automatic installation. P004 is **NOT AUTHORIZED**; `.deb` packaging belongs to P007.

See [architecture](docs/ARCHITECTURE.md), [roadmap](docs/PLAN.md), [P002 validation](docs/P002-VALIDATION.md), [P003 cloud validation](docs/P003-VALIDATION.md), and [device test/rollback instructions](docs/P003-DEVICE-TEST.md).
