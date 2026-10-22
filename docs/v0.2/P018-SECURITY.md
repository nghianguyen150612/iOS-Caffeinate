# P018 Security Boundaries

## Read-only operations

`ic doctor`, package status/verification/planning, evidence status/inventory/validation, and schedule/server/service/health diagnostics only query existing interfaces. Doctor uses bounded local children and existing read-only IPC. It does not start the daemon, acquire an assertion, probe SSH/Tailscale, invoke launchd mutations, repair state, or reset P014 recovery.

`ic probe` and manual/server trial commands are assertion-changing. Schedule definitions and service configuration operations are state-changing. Help labels these classes separately.

## Package operations

The P018 package helper never runs a `.deb` script. It reads metadata and streams payload content into bounded memory. It uses no shell evaluation of package data and no privileged package extraction. The manager never invokes `dpkg -i`, `dpkg --remove`, automatic rollback, launchd activation, process kill, or socket deletion. `prerm` blocks when launchd registration, runtime, IPC, assertion cleanup, P014 recovery, package integrity/ownership, custom socket/manual daemon review, or persistent-data review is missing or uncertain. Unknown launchd registration is never rewritten as `NOT_REGISTERED`.

P010 signer provenance, host signature integrity, device execution, and iOS package acceptance remain separate checks. P018 does not substitute a different `ldid`, treat hash validity as trust, or claim device acceptance.

## Export filesystem controls

All evidence and destination paths are treated as untrusted. Opens reject symlink traversal, non-regular files, and hardlinks. P009 paths are validated before attachment discovery. Contents, total size, and file count are bounded. Sources are read safely, ownership and stat identity are checked, and each source is revalidated before copying. Destinations must be new, root-owned, mode-restricted directories. Files use exclusive creation and restrictive permissions. Manifest publication is atomic; failure/interruption cleanup is explicit.

Privacy filtering rejects credential-like fields and values, raw IPv4/IPv6 and MAC addresses, unnecessary device-identifier fields (including raw assertion IDs), and private home/application paths. Default export uses only the fixed allowlist and P009-validated attachments. Additional operator files require explicit opt-in, are scanned separately, and retain `UNKNOWN`/`UNREVIEWED` provenance. No arbitrary log or `/var` archive is produced.

## Limits

Hashes establish byte consistency, not source authenticity. Filesystem checks cannot prevent a privileged attacker from changing the system. The export validator does not authenticate device-origin records. Review exports before sharing. No hardware evidence or P009 acceptance is inferred from a valid export.
