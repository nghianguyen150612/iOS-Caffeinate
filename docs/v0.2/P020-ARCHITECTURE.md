# P020 Integration and Release Architecture

**State:** cloud integration work is under review; v0.2.0 publication is blocked pending physical acceptance.

P020 sits above the P011–P019 stack. It integrates the existing native C11 CLI and daemon, the iOS IOKit backend, rootful Debian packaging, guarded service/recovery/policy modules, calendar-only schedule handling, read-only health observation, and offline evidence tools. It adds a strict build-provenance record, a separately versioned unsigned development candidate, and an offline release gate. It does not add a device executor.

## Runtime boundaries

- `src/cli.c` speaks a bounded line protocol to `src/daemon.c` over the Unix socket. The default endpoint is `/var/run/ioscaffeinated.sock`; the root daemon creates it mode `0600` and verifies peer effective UID before parsing commands.
- `src/power.c` owns the native IOKit assertion calls. The daemon tracks one assertion and bounded expiry. A release error leaves the identifier present, changes state to `RELEASE_FAILED`, and blocks a successful cleanup report.
- `src/recovery.c` and `src/server_policy.c` store or evaluate policy. They do not spawn a replacement daemon. An unknown or unsafe recovery journal blocks all assertion acquisition.
- `src/schedule.c` stores and evaluates recurrence, DST, conflicts, and generation preconditions. The daemon explicitly does not poll future schedule occurrences or acquire an assertion for them.
- `src/service.c` reports service state and builds a disabled managed profile. Launchd operations are capability-gated and remain unaccepted on the target. Package scripts stage an inert template under `/usr/share/ioscaffeinate/launchd/`.
- `src/health*.c` provides on-demand snapshots. Missing values remain unavailable or unknown. Diagnostics do not authorize execution.
- P009/P012/P018/P019 scripts validate or transform evidence offline. P020 consumes structured data and hashes; it never imports or executes evidence-bundle code.

## Release path

The regular v0.1 package job remains on `packaging/rootful/VERSION` (`0.1.0-1`) for P010/P011 compatibility. A separate P020 macOS job builds two iOS ARM64 unsigned trees with `0.2.0~rc1-1` compiled into the binaries. Ubuntu packages each tree independently, checks Debian ordering and payload identity, and compares hashes. The candidate state is `UNSIGNED_DEVELOPMENT`; it is preparatory and not ready for installation.

The provenance record binds source commit/tree, branch, target, compiler, SDK, Xcode, configuration, dependencies, package identity, binary/package hashes, unsigned signing state, workflow run, and the measured reproducibility result. A hash match is a byte-for-byte result for those builds, not hardware acceptance or signer provenance.

The release gate reads a versioned manifest plus relative evidence files. It validates strict schemas, file type, single-link count, per-file and aggregate size bounds, path traversal, SHA-256, evidence class, and independent review receipts. Hardware gates have no user-set `status` property. A gate can pass only after required typed evidence is present, hashes match, provenance is physical, and a signed review receipt binds each evidence hash. The GPG signature must verify against an absolute reviewer keyring supplied from outside the evidence bundle; without that externally managed trust root, the result remains `UNVERIFIED`. Synthetic sources are blocked. Human reviewers still assess the underlying observation and P009 provenance.

A `READY_FOR_RELEASE_AUTHORIZATION` report would still not publish. The tool always reports `publication_authorized=false`; a stable package, tag, GitHub Release, and public assets require a separately authorized action.

## Persistent state and package boundary

Runtime state remains under `/var/lib/ioscaffeinate/`; logs under `/var/log/ioscaffeinate/`. P014 journal, schedule v1 data, Server Mode configuration, and P009/P018 evidence are separate records. P020 assessment is read-only. Package validation extracts into an isolated temporary location and does not install or alter device state.

The package identity remains `com.ioscaffeinate.cli`, architecture `iphoneos-arm`, with `/usr/local/bin/ios-caffeinate`, `/usr/local/bin/ios-caffeinated`, `/usr/local/bin/ic`, and `/usr/local/libexec/ioscaffeinate-manager`. No schedule or Server Mode configuration is seeded.
