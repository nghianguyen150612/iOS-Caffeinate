# R05 Attended Device Acceptance Runbook

This runbook prepares staged procedures for the reference iPad mini 2 (`iPad4,4`, iOS 12.5.7, Amethyst/Procursus rootful). Run device commands only from an operator-controlled host while physically beside the iPad with independent local recovery available. Cloud CI does not connect to or modify the device.

Every package installation, removal, daemon start, recovery reset, state restoration, or other persistent/runtime mutation requires separate explicit operator authorization and a passing prior gate. Stop on unknown assertion ownership, failed release, package/audit mismatch, uncertain recovery, loaded launchd state, or missing physical recovery. Never use a force option or delete persistent state to clear a blocker.

**Current candidate stop:** exact-source run [39975913477](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/39975913477) failed Apple host signature-integrity verification for both ARM64 executables (“code object is not signed at all”). It emitted no finalized candidate manifest or full checksum inventory. Do not perform the v0.2 RC transfer or installation steps below unless a later exact-source run succeeds and its receipt and complete inventory are reviewed.

## 1. Retrieve and verify the published v0.1.0 P011 package

On the attended operator host, use a new private directory and retrieve the official release assets:

```sh
P011_DIR="$PWD/ioscaffeinate-p011-v0.1.0"
umask 077
mkdir -m 700 "$P011_DIR"
gh release download v0.1.0 \
  --repo nghianguyen150612/iOS-Caffeinate \
  --dir "$P011_DIR"
(cd "$P011_DIR" && sha256sum -c ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb.sha256)
```

The exact package is `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb`, expected SHA-256 `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c`. Confirm the SHA sidecar, then rerun the pinned H003 P011 host verifier from a clean checkout with the H003-compatible Linux signer:

```sh
cd /path/to/iOS-Caffeinate
python3 scripts/p011_release_preflight.py \
  --package "$P011_DIR/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb" \
  --asset-dir "$P011_DIR" \
  --ldid /absolute/path/to/H003-verified/ldid \
  --json-out "$P011_DIR/P011-release-preflight.json"
```

Require `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING`, exact package identity/hash, verified historical archive and legacy checksum, exact entitlements, and package structure. The published v0.1 artifact has historically partial checksum coverage. Host preflight does not prove signature trust, installation, execution, or acceptance.

## 2. Download and verify the exact v0.2.0-rc1 artifact

After the candidate stop above is cleared, download only the successful `P020 signed v0.2.0 RC candidate` run whose `headSha` equals the PR's reviewed source SHA. Check the run and fetch the named artifact:

```sh
RC_SOURCE_SHA='<exact reviewed 40-character source SHA>'
RC_RUN_ID=$(gh run list \
  --repo nghianguyen150612/iOS-Caffeinate \
  --workflow 'P020 signed v0.2.0 RC candidate' \
  --branch docs/h004-device-phase0-readiness \
  --json databaseId,headSha,status,conclusion \
  --jq "[.[] | select(.headSha == \"$RC_SOURCE_SHA\" and .status == \"completed\" and .conclusion == \"success\")] | first | .databaseId")
test -n "$RC_RUN_ID" && test "$RC_RUN_ID" != null
RC_DIR="$PWD/ioscaffeinate-v0.2.0-rc1-$RC_SOURCE_SHA"
umask 077
mkdir -m 700 "$RC_DIR"
gh run download "$RC_RUN_ID" \
  --repo nghianguyen150612/iOS-Caffeinate \
  --name iOS-Caffeinate-v0.2.0-rc1-SIGNED-DEVICE-UNVERIFIED \
  --dir "$RC_DIR"
(cd "$RC_DIR" && sha256sum -c SHA256SUMS)
```

Inspect `signed-final/P020-SIGNED-CANDIDATE-MANIFEST.json`. Confirm `source.commit_sha` equals `RC_SOURCE_SHA`, `candidate_state` is `SIGNED_RC_DEVICE_UNVERIFIED`, package identity is `com.ioscaffeinate.cli` / `0.2.0~rc1-1` / `iphoneos-arm`, and the P020 assessment remains `RELEASE_BLOCKED` with `publication_authorized=false`. Check the package sidecar before transfer:

```sh
RC_PACKAGE="$RC_DIR/signed-final/ioscaffeinate_0.2.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb"
(cd "$(dirname "$RC_PACKAGE")" && sha256sum -c "$(basename "$RC_PACKAGE").sha256")
```

Record the manifest source SHA and package SHA in the attended session notes. Stop on a missing run, source mismatch, checksum failure, missing Apple `codesign` success receipt, or any non-pending physical state in the P020 assessment.

## 3. Transfer and complete read-only preflight

Transfer the verified package from the attended host using the operator's chosen method. Example SSH copy, only while the operator is physically present and local recovery is ready:

```sh
scp "$RC_PACKAGE" root@<device-address>:/var/mobile/Documents/
```

On the iPad, compare the downloaded package SHA with the host's recorded value and inspect its Debian identity. Use the device's available SHA-256 utility (`sha256sum` or `shasum -a 256`):

```sh
cd /var/mobile/Documents
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum ioscaffeinate_0.2.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 ioscaffeinate_0.2.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb
else
  echo 'No SHA-256 utility is available; stop before installation.' >&2
  exit 1
fi
dpkg-deb --field ioscaffeinate_0.2.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb Package Version Architecture
```

Run the versioned read-only `scripts/p011_device_preflight.sh` from the reviewed source checkout on the device, with the package path as its argument. Record exact output and exit status. Do not run install, reset, start, launchctl, or cleanup commands as part of preflight.

Complete the full H004 Phase 0 inspection directly on the iPad, including `dpkg --audit`, every warning package, owners/modes/link counts for relevant paths, process/socket/lock state, launchd registration and plist, P014 status, assertion owner/cleanup state, policy/schedule/log/evidence state, storage, battery/thermal availability, and a physical recovery method. The current SSH observations are preliminary. Specifically resolve the reported virtual hardware-capability package audit warnings; five payload-empty samples do not clear all warnings. Record actual timestamps, timebases, uncertainty, command output references, and independent reviewer details in the H004 worksheet. Unknown history or assertion ownership stops progression.

After a passing read-only inspection, preserve package state, schedules, Server Mode policy, P014 journal, logs, evidence, and the previous package in a separate access-controlled backup. Verify the backup files and record their hashes. Keep credentials out of evidence.

## 4. P011 v0.1.0 acceptance

P011 stable-package installation is a separate authorized action. Install only after the direct Phase 0 review, package hash checks, audit resolution, clean assertion/service state, backup, and physical recovery confirmation pass. Follow [P011 device acceptance](P011-DEVICE-ACCEPTANCE.md) for the attended install, installed-path/hash verification, foreground execution, root-only IPC socket, IOKit acquire/release probe, bounded expiry, STOP, SIGTERM cleanup, state preservation, and verified rollback. Do not enable or load launchd.

Run each trial separately and preserve the actual exit code, assertion ID, acquire result, release result, daemon PID, process/socket/lock observations, logs, and final idle state. Do not intentionally crash a daemon holding an active assertion. Any uncertain release or cleanup ends the session.

## 5. Install and qualify the exact v0.2.0-rc1 candidate

Proceed only after H004 and the authorized P011 prerequisite reviews pass, the candidate source/package/checksum are independently checked, and a new explicit authorization names the exact RC package hash. Re-run device preflight and backup immediately before the RC install. Save package-manager output and verify installed package version, architecture, paths, owners/modes, and binary hashes against the candidate manifest. Confirm no install script enabled launchd.

For the first v0.2 daemon start, inspect `ic service recovery status` first. A missing journal is `MISSING_FIRST_INSTALL_REVIEW_REQUIRED`, not clean state. Establish known prior assertion history and direct cleanup/supervisor observations. Only after separate authorization and review may root run:

```sh
/usr/local/bin/ic service recovery reset --reviewed-cleanup --reviewed-supervisor-state
/usr/local/bin/ic service recovery status
```

The reset command mutates the journal and may create the root-owned lock. Its flags attest that observations were reviewed; the command does not inspect historical assertion ownership or verify external observations. Never use it to clear a crash, unknown assertion owner, release failure, corrupt journal, unsafe file, or unsupported record. Do not repeat reset after an unexpected run outcome.

Run `/usr/local/bin/ios-caffeinate --help`, `ic status`, `ic server doctor`, and manager `verify` first. Start the daemon only in the foreground under observation. Check CLI-to-daemon IPC and that the Unix socket is root-owned with mode `0600`. If macOS signature validation succeeded but iOS execution fails, preserve the complete AMFI/codesign/device log and the exact command/exit status; do not swap signing methods or binaries during the session.

Qualify the candidate in supervised, bounded steps:

1. Verify native CLI and daemon execution on iOS 12.5.7 and the installed binary/package identities.
2. Verify IPC and root-only socket/lock permissions.
3. Probe IOKit assertion acquisition and release, then separately test a short natural expiry, explicit STOP, and foreground-daemon SIGTERM cleanup.
4. Exercise the documented first-install recovery path and non-mutating failure gates. Preserve schedules, policy, logs, journal, package state, and evidence before/after.
5. Complete P012's prescribed 24 physical trials. Complete P019's 12 bounded 180-second acquire/release cycles across three distinct attended dates with an independent observer/reviewer. Never run an unattended assertion or infer 24/7 operation.
6. Record battery and thermal observations and availability. Keep launchd disabled.
7. Preserve unchanged raw P009 evidence privately; generate and independently review only the sanitized P018 export. Bind evidence hashes and signed review receipts through the P020 evaluator.

Do not compress these into one continuous run. Stop and preserve evidence after any abnormal temperature, battery/power change, assertion ownership uncertainty, failed release, unexpected process/service state, or unexplained package/audit difference.

## 6. Rollback

Rollback or removal is a separate state-changing action requiring separate authorization, a verified previous package and matching checksum, a verified backup, stopped daemon, confirmed release, absent socket, inactive launchd, and physical recovery. Run the package manager's read-only checks first:

```sh
/usr/local/libexec/ioscaffeinate-manager uninstall-check
/usr/local/libexec/ioscaffeinate-manager rollback-check /absolute/path/to/verified-previous-package.deb
```

After review and authorization, install the exact verified prior package or remove the package using the steps in [P011 device acceptance](P011-DEVICE-ACCEPTANCE.md). Never force removal, delete the journal/log/evidence directories, or treat a rollback check as completed rollback acceptance. Verify persistent state against the backup and record actual differences.

## 7. Evidence and release decision

Use the existing P009 schema and validator only for actual captured events. Keep the raw record private and unchanged. Create a sanitized P018 export separately and review it. Submit exact package/source hashes, device identity, logs, valid trial counts, dates, observer and reviewer identities, and detached signed reviews only after the underlying actions happened. Run the offline P020 evaluator against the exact source and trusted external reviewer keyring. Do not modify release state based on an artifact download, CI success, manually entered `PASS`, or this runbook.
