# P006 — Server Mode Foundation

P006 adds an observable, fail-closed policy layer for later server-mode work. It does not establish that iOS 12 prevents suspension, that SSH or Tailscale survives a locked screen, or that the iPad is safe to run unattended.

## Policy and runtime state

Configuration policy and current daemon state are separate:

| Layer | Values | Meaning |
|---|---|---|
| Configured policy | `DISABLED`, `OBSERVE_ONLY` | Explicit read-only policy preference. Missing, corrupt, unsafe, or unsupported config resolves to `DISABLED`. |
| Current daemon state | `IDLE`, `ACQUIRING`, `ACTIVE`, `RELEASING`, `RELEASE_FAILED`, `SHUTTING_DOWN` | State of the existing single assertion owner. |
| Trial state | `INACTIVE`, `ACTIVE`, `STOPPED`, `EXPIRED`, `RELEASE_FAILED`, `RELEASED` | A user-started, bounded experiment. It is separate from an operational server policy. |
| Readiness | `BLOCKED` until evidence exists | All hardware and operational gates start `PENDING`. |

`OBSERVE_ONLY` does not acquire power assertions. The default is `DISABLED`. No configuration value, daemon launch, diagnostic, or plan command starts a trial or persistent assertion. P004 timed and scheduled holds continue to use the daemon's existing assertion owner.

The status report describes the current daemon's owned assertion. It cannot inspect iOS power state. `backend_verification=UNVERIFIED`, `os_power_state=UNVERIFIED`, and `prior_process_cleanup=UNVERIFIED` must not be interpreted as evidence that the operating system is awake or that a previous process released an assertion.

## Configuration

The optional read-only file is `/var/lib/ioscaffeinate/server-mode.json`:

```json
{"version":1,"policy":"disabled"}
```

The only accepted policies are `disabled` and `observe_only`. Version 1 requires exactly the `version` and `policy` fields. Duplicate, unknown, malformed, trailing, oversized, or unsupported data fails closed. The reader opens path components without following symlinks and requires trusted directories; the file must be owned by the effective user, regular, single-link, mode `0600`, and at most 512 bytes. In the intended rootful deployment, the effective user is root, so the file is root-owned.

P006 has no config writer. There is no command to enable an unattended policy. Any future writer must create a private staging file and atomically rename it into place. Credentials and assertion IDs are not part of this schema. A diagnostic-only `--server-config /absolute/path` option supports tests and offline inspection; it does not change the production default.

## Diagnostics and trials

These commands are read-only and never contact LAN or tailnet peers:

```sh
ic server status
ic server doctor
ic server plan
```

`status` distinguishes a missing daemon from an unverified backend, reports protocol compatibility, current daemon assertion ownership and lifecycle when available, schedule state, hardware readiness, and unavailable telemetry. `doctor` reports socket, protocol, startup, backend, schedule, network, battery, and thermal checks using `UNKNOWN`, `UNAVAILABLE`, `UNVERIFIED`, or `PENDING` where evidence is absent. `plan` lists the ten unmet gates and their consequences; it never applies changes.

An explicit hardware validation session can use the existing daemon owner through:

```sh
ic server trial start --for 1m
ic server trial stop
```

Trials are user initiated and capped at 300 seconds. There is no automatic trial at daemon launch, no indefinite assertion, and no automatic trial resumption after STOP or restart. Expiry and SIGTERM attempt release. Release retries are capped at three attempts during normal operation; the daemon retains `RELEASE_FAILED`, ownership, and the last error if all attempts fail. Shutdown makes one final bounded cleanup attempt. A dead process or SIGKILL may prevent cleanup; a new process does not infer recovery from the prior process.

## Readiness gates

All gates remain `PENDING`; Linux tests and CI cannot pass hardware gates:

1. `device_runtime_verified`
2. `assertion_acquire_verified`
3. `assertion_release_verified`
4. `bounded_hold_verified`
5. `screen_locked_lan_verified`
6. `screen_locked_tailscale_verified`
7. `shutdown_cleanup_verified`
8. `battery_observation_available`
9. `thermal_observation_available`
10. `physical_recovery_confirmed`

Source implementation, iOS ARM64 build, runtime behavior, power-management behavior, network reliability, and operational readiness remain separate claims. There is no production flag that bypasses these gates. `unattended_mode_authorized` always reports `no` in P006.

## Health observations

The daemon reports uptime, assertion lifecycle, last successful acquire/release epochs, last release error, schedule activity, and recent error count. Each comes from the current process and is unavailable when the daemon cannot be queried. P006 does not poll sensors or networks. No supported read-only iOS 12 battery or thermal source has been established, so those metrics report `UNAVAILABLE`. Network measurements are also unavailable unless supplied externally. A local daemon response is not reachability evidence.

## Connectivity evidence

The import format is [`connectivity-evidence-v1.schema.json`](schemas/connectivity-evidence-v1.schema.json). It has required, separate `lan` and `tailscale` objects. LAN captures the local address, TCP port 22, authenticated SSH, latency, timestamp, and operator-reported screen lock. Tailscale captures the tailnet address, peer connectivity, direct/relay/unknown path, authenticated SSH, latency, timestamp, and screen lock. Null means no observation. Never copy one network's result into the other record or infer it from daemon status.

P006 does not run a scanner, open remote connections, change SSH/Tailscale settings, or import fabricated evidence.

## Recovery and overhead

The event loop blocks on socket activity when idle without schedules or a held assertion. With no schedules, active assertion deadlines and bounded release retries wake at their deadlines. When P004 schedules exist, the existing one-second recheck bound is preserved. Diagnostics do not load IOKit, acquire assertions, write configuration, or rewrite schedule state.

Linux mock CPU observations describe only the mock process and are not iPad power measurements. P006 makes no battery-saving claim. There is no automatic launchd activation; the bundled plist remains disabled with `RunAtLoad=false`. See [validation evidence](P006-VALIDATION.md) and the future [P006-HW procedure](P006-DEVICE-TEST.md).
