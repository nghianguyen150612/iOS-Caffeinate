# P018 Architecture — CLI, Package Preflight, and Evidence Export

P018 adds an operator-facing layer over the existing C11 CLI, rootful manager, and P009 evidence validator. It does not create a second daemon, a package installer, a launchd controller, an unattended schedule executor, or an automatic rollback path.

## Components

- `src/cli.c` keeps the `ios-caffeinate` binary and `ic` alias. It adds contextual help, source/build version fields, bounded read-only `doctor` aggregation, package-manager forwarding, and evidence-tool forwarding.
- `packaging/rootful/manager` remains the package operation authority. Its existing `status`, `verify`, `doctor`, `rollback-check`, and `uninstall-check` commands remain. `upgrade-check` and richer rollback readiness are read-only additions.
- `scripts/p018_package_preflight.py` inspects an operator-supplied `.deb` by reading its control metadata and streaming its data archive. It never runs package maintainer scripts and never extracts payload into an installation directory. A temporary unlinked snapshot is passed to `dpkg-deb` through an inherited file descriptor so a pathname replacement cannot change the inspected artifact.
- `scripts/p018_evidence.py` discovers only fixed evidence paths and validated P009 attachments. Export requires an explicit new absolute destination.
- `scripts/p018_validate_export.py` validates an export offline using Python's standard library. It reads but never executes bundle content.

The four P018 Python files are installed under `/usr/share/doc/ioscaffeinate/tools/` and included in `SHA256SUMS`. The package manager verifies their ownership, mode, and digest before reporting package integrity.

## Read-only doctor

`ic doctor` runs existing status/doctor/policy/health/schedule interfaces in bounded child processes, plus package-manager status and evidence status. Each component gets a separate status, reason, and next safe step. A failed observation remains unknown or unavailable; it does not become a fabricated result for another component.

The doctor does not start the daemon, acquire an assertion, probe SSH/Tailscale, run a launchd mutation command, repair data, or reset recovery. Each child query has a timeout; helper output and JSON are bounded. `ic doctor --json` uses schema version 1 and stable component keys.

## Package readiness

`ic package upgrade-check` combines the artifact validator with current package, file ownership, launchd, daemon, IPC, assertion, recovery, schedule, policy, and rollback observations. Its only positive result is `READY_FOR_OPERATOR_REVIEW`; this result authorizes no install or upgrade. Exact P010 signer provenance is required for that result, and device signature acceptance is reported separately.

`ic package rollback-check` retains the historic zero exit for a package whose checksum and basic Debian metadata pass. Its `rollback.readiness` field carries the full P018 review state, including service state, provenance, and persistent-data review. A zero exit from this command alone does not mean that rollback is safe or authorized.

The package scripts retain their fail-closed P007/P013 behavior. Unknown launchd registration, live plist, socket, lock, runtime, assertion, or recovery state remains a blocker. The manager does not delete sockets, force-stop processes, invoke `dpkg -i`, invoke `dpkg --remove`, or rewrite persistent data.

## Evidence lifecycle

Inventory distinguishes presence, parsing/validation, provenance class, and review claims. P009 remains authoritative for physical acceptance. A parser result or an export hash cannot establish physical authenticity. Export uses a fixed allowlist, size/count limits, safe no-follow opens, single-link regular files, revalidation before copying, root ownership, mode `0700` directories, and mode `0600` files. A manifest is published atomically only after all payload files are finalized.

Exported bundles report `EXPORT_CREATED`; they always set `hardware_evidence_accepted=NOT_ESTABLISHED`. P009 acceptance remains a separate human-reviewed process.

## Compatibility boundary

The installed names, package identity, architecture, and runtime paths remain unchanged. Legacy CLI commands and service exit codes are preserved. New JSON is opt-in. See [CLI contract](P018-CLI-CONTRACT.md), [package preflight](P018-PACKAGE-PREFLIGHT.md), [export security](P018-SECURITY.md), and [device acceptance](P018-DEVICE-ACCEPTANCE.md).
