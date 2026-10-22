# P011 — Supervised v0.1.0 package acceptance

**Status: PENDING physical iPad session.** No installation, installed-binary execution, package removal, or rollback is performed by this document or by the P011 cloud workflow. Installation, assertion trials, removal, and rollback each require separate operator authorization during a physically attended session.

P018's initial device session is read-only and is documented in [P018 device acceptance](P018-DEVICE-ACCEPTANCE.md). This P011 procedure describes later package acceptance steps; do not run its installation or rollback phases as part of P018 without separate explicit authorization.

Target: iPad mini 2 A1489 (`iPad4,4`), Apple A7 ARM64, iOS 12.5.7, Amethyst/Procursus rootful. Stable artifact: `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb`, SHA-256 `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c`.

## H002 host compatibility note

The H002 P011 route accepts only that exact release archive SHA. It verifies the historical seven-record checksum contract and the complete post-publication derived layout, then reports `checksum_coverage=HISTORICALLY_PARTIAL`; the derived inventory is not presented as an original full manifest. Current v0.2 package validation remains strict.

The H002 host run verified the release API identity, package hash, eight pinned release assets, Debian identity, package structure, historical checksums, signing metadata, profile bytes, Mach-O properties, and maintainer-script safety. It stopped at the missing verified H001 `ldid` executable, required for independent entitlement extraction. The report records `embedded_entitlements=PENDING_PINNED_LDID`, `signature_integrity=PENDING`, and `device_acceptance=PENDING`. Do not substitute a different signer.

Proceed to physical P018 read-only inspection only after the exact signer input is available, the P011 host command reports `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING`, P012 findings are reviewed, P013/P014 behavior is reviewed, and an operator is physically present with independent recovery. That initial P018 session remains separately authorized and does not install a package or start the daemon.

The shell preflight is read-only. A successful preflight does not authorize installation. Do not continue after a mismatch, unresolved process/socket, unclear assertion cleanup, or missing physical recovery.

## Phase A — Pre-installation

1. Confirm the operator is physically beside the iPad and has a local recovery method that does not use LAN SSH or Tailscale. Keep that method available for the full session.
2. On an Arch/Linux or other supported host, retrieve all official assets and verify the pinned package, sidecars, profile identity, and P010 package checks. `--ldid` must name the host-compatible executable matching the version and SHA-256 recorded by P010.

   ```sh
   mkdir -m 700 /tmp/ioscaffeinate-p011-v0.1.0
   gh release download v0.1.0 --repo nghianguyen150612/iOS-Caffeinate --dir /tmp/ioscaffeinate-p011-v0.1.0
   python3 scripts/p011_release_preflight.py \
     --package /tmp/ioscaffeinate-p011-v0.1.0/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb \
     --asset-dir /tmp/ioscaffeinate-p011-v0.1.0 \
     --ldid /absolute/path/to/pinned-host-compatible-ldid \
     --json-out /tmp/ioscaffeinate-p011-v0.1.0/P011-release-preflight.json
   ```

   Stop unless the command exits successfully and reports `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING`, the exact release/package identity, `historical_archive=VERIFIED`, `legacy_checksum_manifest=VERIFIED`, `checksum_coverage=HISTORICALLY_PARTIAL`, `package_structure=VERIFIED`, independently rechecked `embedded_entitlements=EXACT_MATCH`, and `device_acceptance=PENDING`. `signature_integrity=PENDING` remains pending; signature presence alone is not cryptographic trust. The H002 preflight currently exits blocked because the verified H001 signer executable is unavailable.
3. Inspect Debian control metadata and maintainer scripts on the host without executing them. Confirm the package has only the expected `preinst` and `prerm`, no live LaunchDaemons plist, and the inactive staged template. The release verifier runs the isolated historical parser/safety checks and does not execute package scripts.

   ```sh
   dpkg-deb --field /tmp/ioscaffeinate-p011-v0.1.0/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb Package Version Architecture
   mkdir -m 700 /tmp/ioscaffeinate-p011-v0.1.0-control
   dpkg-deb --control /tmp/ioscaffeinate-p011-v0.1.0/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb /tmp/ioscaffeinate-p011-v0.1.0-control
   sed -n '1,240p' /tmp/ioscaffeinate-p011-v0.1.0-control/preinst /tmp/ioscaffeinate-p011-v0.1.0-control/prerm
   ```
4. On the iPad, run the read-only preflight with the transferred package path. `/var/mobile/...` below is a path to fill with the actual transfer location; do not use shell history characters in pasted commands.

   ```sh
   /bin/sh ./scripts/p011_device_preflight.sh /var/mobile/Documents/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb
   ```

   Confirm iOS/model, rootful assumptions, `dpkg --print-architecture`, installed package state, file owners/collisions, staged and live launchd state, daemon process and socket, state/log path presence, free storage, package hash/metadata, manager availability, and recovery prerequisites. A blocker ends the session; do not bypass it with manual deletion or a package-manager force option.
5. Review existing schedules, server-mode policy, logs, package state, daemon/socket state, and the staged launchd plist. Back up `/var/lib/ioscaffeinate/`, `/var/log/ioscaffeinate/`, and any operator evidence to a separate safe location. Do not include credentials in evidence.
6. Confirm the daemon is stopped and no assertion is outstanding. If a daemon, socket, loaded service, or uncertain assertion is present, stop and resolve it through an explicitly approved operator action before continuing. Do not kill a process or remove a socket to make the preflight pass.
7. Confirm the live path `/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist` is absent and the label is not loaded. Do not enable or load launchd.

## Phase B — Manual installation

Installation is permitted only after separate explicit operator authorization, successful Phase A, a verified artifact, physical recovery, a clean daemon/assertion state, and a reviewed backup. The following command is provided for that authorized session only; P011 cloud work never runs it:

```sh
dpkg -i /var/mobile/Documents/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb
```

Save the actual `dpkg` output. Record `dpkg-query -W -f='${Status} ${Version} ${Architecture}\n' com.ioscaffeinate.cli`, each installed path, owner/mode, and installed executable SHA-256. Confirm no post-install action enabled launchd.

## Phase C — Installed binary execution

Run the installed paths, not staged temporary binaries:

```sh
/usr/local/bin/ios-caffeinate --help
/usr/local/bin/ic wake status
/usr/local/bin/ic status
/usr/local/bin/ic server doctor
/usr/local/libexec/ioscaffeinate-manager verify
```

Record each exit code and complete output. Confirm the exact CLI, daemon, alias, manager, project state, log, socket, and staged launchd paths. Start the daemon manually in a supervised terminal:

```sh
/usr/local/bin/ios-caffeinated --foreground
```

From another rootful terminal, check the socket owner and mode with `ls -l /var/run/ioscaffeinated.sock` and `stat -f '%u:%g %Lp' /var/run/ioscaffeinated.sock`. Confirm root-only permissions and CLI-to-daemon communication. Do not background or daemonize the service for this check.

## Phase D — Bounded assertion acceptance

Keep the operator at the device with physical recovery available. Run each trial separately and capture the daemon response, assertion ID, acquisition result, release return code, and final idle state:

1. **IOKit probe:** run `/usr/local/bin/ic probe`; confirm the create and release calls both report success.
2. **Natural expiry:** run `/usr/local/bin/ic start --for 30s`, observe the full 30 seconds, then verify inactive state and successful release.
3. **Explicit STOP:** start a separate `/usr/local/bin/ic start --for 30s` trial, immediately run `/usr/local/bin/ic stop`, and verify inactive state and a successful release.
4. **SIGTERM cleanup:** run the daemon in the foreground. Capture its actual numeric PID from `ps`, then in a second terminal set `P011_DAEMON_PID` to that number and run `kill -TERM "$P011_DAEMON_PID"`. Confirm daemon exit, socket cleanup, and successful assertion release. Do not paste a literal `!` into interactive zsh commands.

Do not enable an unlimited hold. Any failed, missing, or uncertain release result ends the session. Restore a known stopped state before the next phase.

## Phase E — Connectivity observations

Record locked-screen LAN SSH and locked-screen Tailscale SSH separately, with observer, timestamps, timebase, uncertainty, authenticated command result, and trial association. Do not store credentials or retain unnecessary network addresses. Network reachability is evidence about that path; it is not automatic proof that an assertion prevented sleep.

The October 18, 2026 24/24 operator-reported LAN and Tailscale observations remain `REVIEW_REQUIRED`. They are from manually staged binaries and do not substitute for installed-package observations. Leave the formal no-assertion A/B/C/D comparison to P012.

## Phase F — Package state preservation

Verify that schedules, server policy, logs, and evidence remain present and unchanged from the pre-install backup. Re-run the read-only manager check. Confirm the live launchd plist remains absent and the daemon is stopped with no assertion outstanding. Record any difference without repairing it during the acceptance session.

## Phase G — Removal and rollback

Removal and rollback are separate state-changing operations. Before either, require separate operator authorization, a verified previous package and its matching checksum/manifest, a state backup, correct dpkg architecture, stopped daemon and released assertion, no default socket, inactive launchd, and physical recovery independent of SSH/Tailscale.

Run the manager's read-only checks first:

```sh
/usr/local/libexec/ioscaffeinate-manager uninstall-check
/usr/local/libexec/ioscaffeinate-manager rollback-check /absolute/path/to/verified-previous-package.deb
```

Only after the checks pass and authorization is given may the operator execute one of these documented actions:

```sh
dpkg --remove com.ioscaffeinate.cli
```

or, to restore a verified older package:

```sh
dpkg -i /absolute/path/to/verified-previous-package.deb
```

Record output and confirm state, logs, and evidence are preserved. Do not use `--force`, manually delete files, or treat an unexecuted rollback check as rollback acceptance. If the prior artifact or physical recovery path is absent, leave removal/rollback `PENDING`.

## Evidence and stop conditions

Use the existing P009 template, schema, validator, replay, and report. Enter only observed values and real timestamps. Mark the evidence source `OPERATOR_RECORDED` or `EXTERNAL_OBSERVER` as appropriate. Keep raw logs, sanitized notes, and P009 manifests together; do not put keys, passwords, tokens, or credentials in them.

During the attended session, a private evidence directory can capture actual command output without changing package state:

```sh
P011_EVIDENCE_DIR=/var/root/P011-evidence-session
umask 077
mkdir -p "$P011_EVIDENCE_DIR"
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$P011_EVIDENCE_DIR/capture-time.utc"
dpkg-query -W -f='${Status} ${Version} ${Architecture}\n' com.ioscaffeinate.cli > "$P011_EVIDENCE_DIR/package-state.txt" 2>&1
/usr/local/libexec/ioscaffeinate-manager verify > "$P011_EVIDENCE_DIR/manager-verify.txt" 2>&1
/bin/sh ./scripts/p011_device_preflight.sh /var/mobile/Documents/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb > "$P011_EVIDENCE_DIR/device-preflight.txt" 2>&1
```

Use a new directory for each real session, transfer it to the host by the operator's approved method, sanitize it, then populate and validate a P009 session. These commands record actual execution time and output; they do not generate trial events or imply a gate result.

Stop the session on any hash/metadata mismatch, unexpected file owner or alias, loaded launchd label, daemon/socket ambiguity, insufficient storage, state change, missing physical recovery, acquisition/release uncertainty, or suspected package-script behavior. Preserve the evidence and report the gate as pending or failed according to the P009 schema; do not convert CI results into device results.
