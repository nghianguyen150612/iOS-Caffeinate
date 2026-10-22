# P013 — Rollback and Recovery

P013 does not auto-activate the packaged template or make a live plist during package installation. If a collision, ownership mismatch, unknown launchd state, or shutdown failure appears, stop the operation and preserve the evidence.

## Before service activation

1. Use direct local access and run `ic service status` and `ic service doctor`.
2. Do not delete a socket that appears stale, remove an unrecognized live plist, or unload a job using unverified syntax.
3. If the live path is present but not an exact P013 managed plist, treat it as unrelated and `INCONSISTENT`; inspect it manually before any separate recovery action.
4. Keep package, schedules, server policy, logs, and P009 evidence intact.

## Failed stop or restart

- A release error or `RELEASE_FAILED` result is not success. Do not continue to start or restart.
- A missing shutdown acknowledgement or timeout means cleanup is unresolved. Do not send SIGKILL and do not remove the socket.
- Preserve the daemon's sidecar lock and socket for diagnosis. Follow the existing P003/P009 recovery procedure with physical access.
- P013 restart performs no stop/start sequence while launchctl start semantics are unverified.

## Disable and package rollback

The P013 cloud build refuses `enable`, `disable`, and `start` because iOS 12 launchctl mutation semantics are unverified. It cannot activate a service and therefore cannot roll back a cloud-created registration. If a later supervised build has enabled lifecycle operations, first confirm graceful shutdown and assertion release, then disable with the exact verified mechanism and confirm the label is not registered.

`prerm` blocks package removal or upgrade while the live plist exists or launchd/runtime/IPC state is uncertain. It does not remove the plist. After the operator has explicitly disabled the service and status positively reports no registration, no observed process, and unavailable IPC, package removal may proceed. Data under `/var/lib/ioscaffeinate` and `/var/log/ioscaffeinate` remains preserved.

Do not reboot or respring as a rollback step. Device reboot persistence testing is separate and hardware gated.
