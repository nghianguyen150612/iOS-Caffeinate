# P013 — Service State Model

`ic service status` reports observations separately. Unknown data stays `UNKNOWN`, `UNVERIFIED`, or `UNAVAILABLE`; plist existence alone never means a process is running.

## Top-level states

| State | Evidence |
|---|---|
| `NOT_INSTALLED` | Exact package database entry, canonical daemon executable, and staged template are absent, and a complete launchd listing positively shows this label is not registered. |
| `STAGED_ONLY` | Root-owned daemon and valid staged template exist; no managed live plist or confirmed runtime is present. |
| `DISABLED` | Exact managed live plist is present with `Disabled=true`; no confirmed runtime conflicts with it. |
| `REGISTERED_STOPPED` | Exact launchd label is present in a successful, complete `launchctl list` result with a stopped PID marker and daemon IPC is unavailable. |
| `RUNNING` | Daemon IPC responds with the expected protocol. This does not by itself establish launchd ownership. |
| `STOPPING` | Reserved for a future observable shutdown-in-progress signal; P013 does not infer it from a request. |
| `FAILED` | Responsive daemon explicitly reports `RELEASE_FAILED` or `BLOCKED`; unresponsive IPC alone is not enough. |
| `INCONSISTENT` | Ownership, mode, link count, exact content, package layout, or socket type conflicts with the P013 contract. Mutations fail closed. |
| `UNVERIFIED` | Evidence conflicts or is incomplete, such as an enabled plist without confirmed registration or a launchd PID without responsive IPC. |

## Separate fields

The CLI includes `package.installation`, `managed_plist`, `configured_enablement`, `launchd.registration`, `launchd.registration_pid`, `runtime.process`, `ipc.availability`, `daemon.state`, `assertion.state`, `assertion.release_pending`, `last_shutdown_result`, `boot_persistence`, `device_awake`, and `recovery_blocker`.

`launchd.registration=REGISTERED` does not imply `runtime.process=RUNNING`, an active assertion, or a responsive daemon. `ipc.availability=RESPONSIVE` proves that the current daemon answered its protocol; it does not prove that launchd started it. `assertion.state=OWNED` is reported only from the daemon's own protocol. The OS awake state and SSH reachability remain unverified.

P013 does not persist a shutdown ledger. `last_shutdown_result=UNAVAILABLE` after a new CLI invocation means no durable result record exists. A successful `service stop` prints the acknowledged release and process-cleanup result in that invocation.

## Example: default package state

Output varies with device observations. A common safe result after package installation and before explicit service management is:

```text
state=STAGED_ONLY
package.installation=INSTALLED
package.database_identity=INSTALLED
package.staged_template=PRESENT_VALID
managed_plist=ABSENT
configured_enablement=NOT_CONFIGURED
launchd.registration=NOT_REGISTERED
runtime.process=NOT_OBSERVED
ipc.availability=UNAVAILABLE
daemon.state=UNKNOWN
assertion.state=UNKNOWN
assertion.release_pending=UNKNOWN
last_shutdown_result=UNAVAILABLE
boot_persistence=UNVERIFIED
device_awake=UNVERIFIED
changed=no
```

If package database identity or `launchctl list` cannot be safely observed, its field remains `UNVERIFIED` and the top-level state is not upgraded based on an absent plist.
