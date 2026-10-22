# P020 Upgrade and Rollback Review

## v0.1 to v0.2 migration matrix

| Area | v0.2 handling | Preview/rollback requirement |
|---|---|---|
| Package files and aliases | Keep package identity and rootful paths; `ic` remains a symlink to the CLI. | Inspect version, owner/mode, hashes and collisions before any separately authorized install. |
| Schedule data | Preserve schedule v1 and legacy definitions. P017 occurrences remain diagnostic only. | Validate and copy state under an attended, verified backup procedure; do not auto-migrate or enable schedules. |
| Server Mode | Preserve v1 `disabled`/`observe_only`; preserve v2 data. No automatic policy promotion. | Read-only schema and policy preview; bounded-session is never enabled by upgrade. |
| P014 recovery journal | Preserve exact journal bytes and schema. Missing, corrupt, unknown, or unsafe state stays blocking. | Review cleanup confidence and independent supervisor state; no automatic reset. |
| Logs | Preserve existing records and ownership. | Collect only project logs needed for review; do not sweep `/var`. |
| Hardware evidence | Keep P009 raw evidence private and unchanged; store P018 sanitized exports separately. | Verify hashes and privacy review; an export is not a replacement for raw material. |
| Existing live plist | Do not register, rewrite, load, enable, or remove a registered service. | Unknown launchd registration stops the operation pending supervised review. |
| Daemon/socket/lock | Do not silently terminate a process or unlink an uncertain socket/lock. | Confirm daemon identity, assertion state, socket ownership and cleanup before a separate operation. |
| Manager scripts | Retain read-only package/status and safety checks. | Inspect exact candidate and previous trusted artifact; scripts do not perform rollback. |

## Read-only preview

Use the manager’s planner before any separately authorized package operation:

```sh
ic package status
ic package upgrade-check "/absolute/path/to/candidate.deb"
ic package upgrade-check "/absolute/path/to/candidate.deb" --rollback-artifact "/absolute/path/to/trusted-previous.deb"
ic package rollback-check "/absolute/path/to/trusted-previous.deb"
```

This preview checks identity, architecture, hashes, signature metadata, ownership/collision state, runtime/recovery/service blockers, and whether a previous artifact is available. It does not install, extract into privileged paths, execute package scripts, activate launchd, restart the daemon, acquire assertions, modify SSH/Tailscale, delete state, or reset recovery.

## Rollback prerequisites

Rollback is not available merely because a file is named “previous”. Require a trusted previous package with verified provenance and hashes, compatible preserved state, known daemon/assertion cleanup, known launchd registration, an attended operator, and a direct recovery path. If any state is unknown, stop and preserve it for review. Do not automatically roll back after an error. Never claim rollback readiness without a successful read-only preview and a separately reviewed recovery plan.
