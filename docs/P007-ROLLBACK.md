# P007 Rollback and State Preservation

## Scope

P007 provides read-only rollback checks and an operator procedure. It does not implement automatic rollback, copy a previous package, restore launchd, restart a daemon, or erase state. A rollback is complete only after the previous package artifact, package status, files, service state, assertion release, and preserved user state have been verified.

## Capture before upgrade

Before a future device upgrade, retain the currently installed `.deb` (or obtain the exact prior package from a trusted source), its matching SHA-256 sidecar, and the CI manifest/report. Record the installed package version and checksums. Save an operator-reviewed inventory of the current files and the relevant state files. Do not describe a backup as available unless it was actually captured and its hash recorded.

Do not capture raw assertion IDs as recovery tokens. Record daemon state and whether release was observed. If no prior package or prior-state evidence is available, rollback readiness is **NOT VERIFIED**.

## Before any upgrade or removal

1. Run `ioscaffeinate-manager status`, `verify`, and `uninstall-check` and retain the output.
2. Stop the active bounded assertion using the CLI and confirm the daemon reports an idle state and successful release. Then stop the manually launched daemon using the exact process/service procedure used to start it. Do not kill a process by name.
3. Confirm the default socket path is absent. The package `prerm` fails closed if any entry remains there. If the daemon used a custom socket, verify that process and endpoint separately.
4. If release did not succeed or cannot be confirmed, stop. Record the assertion as unresolved and do not treat package removal as recovery.
5. Verify previous package provenance and hash. Run `ioscaffeinate-manager rollback-check /absolute/path/to/previous.deb`; it also requires the adjacent `.sha256` file. Inspect its control metadata and extract it into a temporary directory for independent payload review. The command only checks metadata/hash/version and never performs a downgrade.
6. Record current schedules, server-mode policy, evidence, and logs without modifying them. Keep copies only if the operator actually captured and verified them.

## Failure cases

| Condition | Required response |
|---|---|
| Interrupted extraction or half-configured package | Preserve `/var/lib/ioscaffeinate` and logs. Inspect `dpkg --audit`, package status, file list, and package hash. Do not blindly repeat installation or delete partial files. |
| Failed install/upgrade | Keep the package manager's status output and logs. Check collision or architecture diagnostics, active daemon state, and files actually present before retrying. |
| Version mismatch | Compare control metadata and installed package version. Use only the retained, hash-verified prior artifact. |
| Incorrect architecture | Stop before installation. Require `dpkg --print-architecture` to be `iphoneos-arm`; do not force installation or substitute rootless packages. |
| Missing executable or invalid checksum | Do not launch the daemon. Re-extract the trusted package into a temporary directory and compare its files and hashes. If package integrity fails, retain evidence and stop. |
| Invalid/unaccepted signature | Do not assume ad-hoc signing or signature presence proves device acceptance. Use a trusted signing tool and device-supported verification evidence; otherwise mark signing acceptance pending and do not run. |
| Unsafe permissions or ownership | Do not launch or overwrite data. Record the actual owner/mode and correct only package-owned files under an explicitly authorized repair procedure. Never recursively change broad paths. |
| Existing daemon remains active | `prerm` refuses when the default endpoint exists. Stop the exact manually started daemon, verify assertion release, then inspect the endpoint. The script never kills it. Check custom socket paths separately. |
| Service cleanup or assertion release fails | Keep launchd disabled. Record unresolved state and use physical recovery. A package-manager success message does not resolve this failure. |
| Previous package unavailable | Do not claim rollback is possible. Preserve the current package/data and seek a trusted matching artifact before changing package state. |
| Existing persistent data | Preserve schedules, server policy, evidence, and logs. No package operation in P007 purges them or replaces them with defaults. If a file is corrupt or unsafe, preserve it for diagnosis and keep server mode fail-closed. |

## Downgrade procedure

After all preconditions pass, perform an explicit package-manager downgrade to the verified previous `.deb` from the device's root shell:

```sh
dpkg -i /absolute/path/to/verified-previous.deb
```

P007's manager does not do this. Keep the daemon stopped and launchd disabled throughout. Follow the package manager's exact version/downgrade prompts; do not use force options to bypass architecture or integrity failures.

Afterward, verify package name/version/architecture, package-owned executables and checksums, symlink target, ownership/modes, staged launchd state, and that the live launchd file was not activated. Compare user state and logs with the recorded pre-upgrade evidence. Start no daemon and reacquire no assertion as part of rollback. Any mismatch, unavailable prior artifact, or failed release means rollback is unresolved.

## Ordinary uninstall and purge

After the same stop/release and state checks, an explicitly requested ordinary removal from the device's root shell is:

```sh
dpkg -r com.ioscaffeinate.cli
```

Ordinary package removal removes package-owned executables, manager, documentation, staged launchd template, and empty package-owned directories. It does not erase files under `/var/lib/ioscaffeinate` or `/var/log/ioscaffeinate`; non-empty directories remain. It does not disable/unload launchd, stop an external service, change SSH/Tailscale, or make an assertion-release claim. The `prerm` only detects a default endpoint and stops removal with instructions.

There is no P007 purge command. A future separately authorized purge would need a specific reviewed list, backup evidence, and per-file confirmation. Do not run broad `rm -rf` commands against project directories.
