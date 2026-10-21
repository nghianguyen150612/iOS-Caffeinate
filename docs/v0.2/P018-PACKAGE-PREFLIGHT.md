# P018 Package Preflight

The existing `/usr/local/libexec/ioscaffeinate-manager` remains the package frontend's authority. Commands are read-only:

```sh
ic package status
ic package verify
ic package upgrade-check "/absolute/path/to/candidate.deb"
ic package rollback-check "/absolute/path/to/previous.deb"
ic package uninstall-check
```

An upgrade may include a rollback candidate:

```sh
ic package upgrade-check "/absolute/path/to/candidate.deb" --rollback-artifact "/absolute/path/to/previous.deb"
```

## Artifact inspection

`p018_package_preflight.py` checks the Debian package identity, version ordering, `iphoneos-arm` architecture, SHA-256 and strict sidecar, P010 package-build metadata, payload checksum coverage, signed-state metadata, and the exact embedded entitlement profile. It checks the exact P010 signed-candidate manifest against source commit, package hash, signer identity, pinned CI jobs, and signature-integrity result. A missing exact signer manifest is reported as `UNVERIFIED` with a blocker. A valid hash is not a signature; a signature is not iOS device acceptance.

The helper gives `dpkg-deb` a private snapshot through an inherited descriptor and streams the archive into bounded memory. It rejects traversal, duplicate paths, symlinks except the package's exact `ic -> ios-caffeinate` alias, hardlinks, special files, excessive sizes, unexpected payload paths, and mismatched checksums. It never runs maintainer scripts or extracts to an install location.

## Current-state checks

The manager combines artifact checks with installed identity/integrity, package ownership, live plist state, default socket and lock state, read-only daemon status, launchd registration, assertion ownership, P014 recovery, P017 schedule validation, optional P015 policy validation, and rollback-artifact availability. P018 cannot enumerate arbitrary custom sockets or manually launched daemon arguments, so that state is explicitly `UNVERIFIED` and blocks upgrade, rollback, and uninstall checks until an attended inspection procedure is separately authorized. A live plist, present/unsafe socket, uncertain launchd/runtime/IPC/assertion/recovery state, inconsistent ownership, incompatible persistent state, missing rollback artifact, or unreviewed persistent-data preservation also blocks readiness.

Readiness values are `READY_FOR_OPERATOR_REVIEW`, `BLOCKED`, `INCOMPLETE`, and `UNVERIFIED`. The manager always says `operator_install_authorization=NOT_GRANTED`. Until a separately reviewed and authorized data-preservation procedure exists, upgrade and uninstall checks remain blocked with `persistent_data_preservation=REVIEW_REQUIRED`. `READY_FOR_OPERATOR_REVIEW` is not installation permission and does not mean hardware acceptance.

## Exit result details

`ic package rollback-check` retains its older zero result for a verified checksum/basic Debian artifact. Its new `rollback.readiness` reports the full review state. `upgrade-check` includes that artifact check and returns nonzero while blockers remain. `uninstall-check` also returns nonzero while state or persistent-data review is incomplete. Neither command installs, removes, rolls back, deletes sockets, sends SIGKILL, mutates launchd, or erases `/var/lib/ioscaffeinate`.

Missing `dpkg-deb`, Python 3, metadata, candidate sidecars, exact P010 provenance, or read-only runtime observations are reported explicitly. See [upgrade and rollback procedure](P018-UPGRADE-ROLLBACK.md) and [security](P018-SECURITY.md).
