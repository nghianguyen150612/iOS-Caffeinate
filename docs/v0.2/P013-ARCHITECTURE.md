# P013 — Service Management Architecture

P013 adds a service-management surface to the existing `ios-caffeinate` CLI. It does not add a second daemon, privileged socket, network endpoint, watcher, or package-time activation step.

## Commands

The public interface is `ic service status|doctor|plan|enable|disable|start|stop|restart`.

`status`, `doctor`, and `plan` are read-only. They inspect fixed package paths, the fixed service socket, and read-only `launchctl help` and `launchctl list` output when the executable passes ownership and permission checks. Their daemon status request does not run the timer-expiration path; the daemon event loop handles expirations independently. They do not write configuration, package state, schedules, logs, or launchd state, and they never call the power backend.

`enable`, `disable`, `start`, and `restart` require root and fail closed while iOS 12 command semantics remain unverified. Help text can establish that a command name is advertised; it cannot establish its domain syntax, start behavior, persistence, or cleanup semantics. The implementation therefore does not infer permission to mutate from a Linux mock or from a command name in help output.

`stop` is designed around an acknowledged `SHUTDOWN` request over the existing root-only daemon socket. It is allowed only for an exact P013 managed plist, a launchd row with a positive PID, a responsive compatible daemon, and an unambiguous `IDLE` or `ACTIVE` assertion state. The daemon releases any owned assertion before acknowledging shutdown. P013 waits for socket removal and a read-only launchd listing that reports the job stopped. A timeout or release error is an unresolved result; there is no SIGKILL fallback.

## Managed plist

The immutable packaged template remains at `/usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist` with `Disabled=true`, `RunAtLoad=false`, and its historical `KeepAlive=true` value. It is not copied to `/Library/LaunchDaemons` by package scripts.

The native generator prepares a distinct managed profile for the live path `/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist`: `Disabled=false`, `RunAtLoad=false`, and `KeepAlive=false`. This profile has the fixed label, executable, arguments, and log paths. `KeepAlive=false` prevents P013 from introducing an indefinite crash relaunch policy. The generator is available to deterministic tests; no production command installs the live file while launchd registration semantics remain unverified.

The file installer uses a root-owned safe parent, `O_NOFOLLOW`, a private exclusive temporary file, file sync, and a same-directory hard-link operation that fails if the destination exists. It validates exact package identity, daemon path, staged template, label uniqueness, socket absence, exact content, owner, mode, link count, and bounded size. Existing content is never overwritten. Production installation remains gated off until a reviewed source change marks iOS 12 file-placement semantics verified; host tests compile the same atomic filesystem path behind a test-only flag.

## State and power boundaries

Package installation, live-plist presence, configured enablement, launchd registration, process observation, IPC, assertion ownership, last shutdown outcome, and recovery blockers are reported as separate fields. See [service states](P013-SERVICE-STATES.md).

Enabling or registering a service does not create a power assertion. A responsive daemon may be idle, active, or in a release failure state. A registered job does not prove assertion ownership, OS awake state, SSH reachability, or boot persistence. None of these fields proves 24/7 availability.

P013 introduces no persistent control-state file. Existing schedules, server policy, logs, and P009 evidence stay under their existing paths and are not removed by service commands.

## Lifecycle and P014 boundary

P013 separates a manually requested start, a manually requested graceful stop, an unexpected daemon exit, launchd restart behavior, and persistent boot enablement. The current CLI refuses start/enable/disable/restart while iOS 12 semantics are unverified. If a later verified lifecycle path uses the managed profile, `KeepAlive=false` means an unexpected exit is not automatically relaunched. Boot persistence remains unverified until a supervised reboot trial. P014 may add bounded restart attempts, backoff, restart-loop suppression, crash classification, health-gated recovery, and cleanup-aware restart decisions after P013 lifecycle behavior is reviewed on hardware.

Cloud CI tests use an injected launchctl runner. The test build cannot execute host launchd commands, and the Linux result is not iOS compatibility evidence.
