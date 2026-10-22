# P018 Upgrade and Rollback Review

P018 adds planning only. It does not invoke `dpkg -i`, `dpkg --remove`, package maintainer scripts, a rollback command, or launchd activation.

## Candidate upgrade

1. Preserve the current package and user state. Confirm the candidate path and matching `.sha256`, `.manifest.json`, and exact P010 signed-candidate manifest.
2. Run `ic package status` and `ic package verify`.
3. Run `ic package upgrade-check "/absolute/path/to/candidate.deb"` and inspect every blocker. If an old artifact is available, include `--rollback-artifact "/absolute/path/to/previous.deb"`.
4. Inspect current service/recovery state, custom socket/manual daemon state, and the persistent-data preservation blocker. P018 has no custom-socket enumeration or reviewed backup/migration procedure, so upgrade readiness remains blocked until separate procedures are reviewed and authorized.
5. Any actual upgrade requires a separately authorized attended procedure and independent physical recovery. P018 cloud engineering does not provide that authorization.

The candidate checker does not unpack into privileged directories. It streams the archive through a bounded reader, checks metadata and contents, and inspects current paths/state. `dpkg-deb` and `dpkg-query` must be available. The package must match `com.ioscaffeinate.cli`, version ordering, `iphoneos-arm`, the approved P010 entitlement profile, package checksums, and exact signer provenance.

## Rollback artifact

`ic package rollback-check "/absolute/path/to/previous.deb"` verifies the historic package checksum/basic metadata contract and adds `rollback.readiness`. The legacy exit result is preserved; inspect that readiness field and every `rollback.blocker`.

Rollback review remains blocked or incomplete when the service state is uncertain, launchd may still be registered, a live plist/socket/lock exists, custom socket or manual daemon state is unreviewed, assertion cleanup is unresolved, recovery is not confirmed healthy, package ownership is inconsistent, P010 provenance is unavailable, or persistent-data preservation has not been reviewed. Do not synthesize `NOT_REGISTERED`, remove a socket, kill a process, reset recovery, or delete state to satisfy a check.

## Uninstall

`ic package uninstall-check` preserves P007/P013's rule that an unknown launchd registration state blocks removal and also requires clear runtime, IPC, assertion, recovery, socket, lock, ownership, custom socket/manual daemon, and persistent-data review. It is read-only and returns nonzero while any prerequisite is unresolved. It does not make package removal safe merely because a diagnostic command ran.

Schedules, server policy, evidence, and logs under `/var/lib/ioscaffeinate` and `/var/log/ioscaffeinate` remain operator data. No P018 command recursively deletes or migrates these directories. Preserve a previous artifact and matching checksum separately; artifact integrity alone does not establish device provenance or a successful rollback.
