# P013 — Service Management Security

## Privilege and inputs

Read-only commands accept no service path, label, launchctl executable, or command string from runtime configuration. The launchctl path, label, executable, socket, plist, and log paths are compile-time constants. Launchctl and `dpkg-query` are invoked with `posix_spawn`, fixed argv, and a small sanitized environment; no shell command is assembled.

Mutating commands require effective UID 0. Unsupported or ambiguous operations return without modifying service, package, launchd, or power state. Exit codes are documented in [P013-VALIDATION.md](P013-VALIDATION.md).

## Filesystem checks

Before managed plist validation or installation, P013 walks absolute path components with directory descriptors and `O_NOFOLLOW`. It rejects `.`/`..`, symlinked parents and files, non-regular files, unsafe parent ownership/modes, unexpected owners/modes, link counts other than one, oversized files, content mismatch, and existing destination collisions. The managed profile is generated from fixed literal values. Installation uses a private same-directory temporary file, flush/sync, and a no-replace hard-link operation; it never overwrites an unrelated plist.

The canonical daemon path is `/usr/local/bin/ios-caffeinated`. Before a mutating operation, P013 also checks the rootful package manager's exact package name and `iphoneos-arm` architecture using fixed-argv, read-only `dpkg-query`. An executable outside the approved rootful package layout is not accepted as managed service content. The packaged template and active managed plist have different exact content and are never interchangeable.

The production file installer is compile-time gated off while iOS 12 file-placement/registration semantics are unverified. A test-only build can exercise its safe atomic filesystem procedure without changing launchd or the host service state.

## Lifecycle protections

P013 does not run `launchctl` mutations with unverified iOS syntax, does not start a second daemon, does not delete stale sockets, and does not use `SIGKILL`. `service stop` requires an exact managed plist, a positively registered launchd PID, a responsive daemon, and an unambiguous assertion state. It asks the daemon to release its own assertion and exit, then waits for socket removal and a stopped launchd PID. Release failure, missing acknowledgement, or timeout is reported as unresolved.

Enabling or starting a service does not acquire an assertion. The managed profile uses `KeepAlive=false` and has no restart loop. The service code does not reboot, respring, change SSH/Tailscale, or create network listeners.

## Package removal

`prerm` refuses removal or upgrade if the default daemon socket exists, if the managed live plist exists (including a symlink), if the installed CLI cannot provide a read-only status, or if launchd registration, runtime, and IPC are not positively clear. It never removes a live plist or mutates launchd. `/var/lib/ioscaffeinate` and `/var/log/ioscaffeinate` remain preserved by package behavior.

Cloud tests can validate these checks and injected results. They cannot establish root filesystem state or launchd compatibility on the target iPad.
