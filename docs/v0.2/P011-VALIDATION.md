# P011 — Validation record and procedures

P011 validates the v0.1.0 artifact and prepares a device acceptance session. It does not install a package or run target-device tests.

## Automated cloud validation

The `p011-release-preflight` CI job runs `tests/test_p011_preflight.py`, validates POSIX shell syntax for the device preflight, records the exact checked-out commit, and uploads its test output. It is offline and does not depend on a release download or physical device.

The regressions cover stable tag and asset identity, the pinned package SHA, Debian identity/version/architecture rejection, unsigned package rejection, invalid profile identity, tampered checksum and package-manifest relationships, P010 alias/executable path contracts, source-commit-specific package documentation, device-preflight read-only invariants, missing tool failure, and P009-compatible pending hardware gates.

The live cloud preflight retrieved the eight published v0.1.0 release assets. The `.deb` matched the pinned 95,572-byte SHA-256, Debian identity/version/architecture, package sidecars, P010 manifests, and Amethyst profile identity. The P010 validator inspected the package structure, Mach-O metadata, maintainer scripts, checksums, and bundled profile, then blocked embedded-entitlement reinspection because this environment did not have the exact `ldid` binary hash recorded by the package builder. The upstream `ldid` release binary for the same version also has a different hash and was correctly rejected. No P010 full-validation PASS is recorded here.

Existing CI jobs remain enabled: Linux protocol, iOS cross-build, Mach-O inspection, rootful package validation, P009 evidence validation, and P010 signing/release gates. P011 does not skip or weaken those jobs. CI success establishes cloud checks only.

## Release artifact verification

Retrieve the published assets with GitHub CLI and run the verifier with the host-compatible `ldid` whose version and SHA match P010:

```sh
mkdir -m 700 /tmp/ioscaffeinate-p011-v0.1.0
gh release download v0.1.0 --repo nghianguyen150612/iOS-Caffeinate --dir /tmp/ioscaffeinate-p011-v0.1.0
python3 scripts/p011_release_preflight.py \
  --package /tmp/ioscaffeinate-p011-v0.1.0/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb \
  --asset-dir /tmp/ioscaffeinate-p011-v0.1.0 \
  --ldid /absolute/path/to/pinned-host-compatible-ldid \
  --json-out /tmp/ioscaffeinate-p011-v0.1.0/P011-release-preflight.json
```

To let the Python standard-library workflow retrieve the release itself, use an empty destination:

```sh
mkdir -m 700 /tmp/ioscaffeinate-p011-v0.1.0-auto
python3 scripts/p011_release_preflight.py \
  --download \
  --download-dir /tmp/ioscaffeinate-p011-v0.1.0-auto \
  --ldid /absolute/path/to/pinned-host-compatible-ldid \
  --json-out /tmp/ioscaffeinate-p011-v0.1.0-auto/P011-release-preflight.json
```

Without the exact host-compatible `ldid`, the verifier completes release identity, checksum, sidecar, manifest, Debian, profile, package-structure, Mach-O, and maintainer-script checks, then reports `P010 package validation=BLOCKED` before embedded-entitlement reinspection. It must not label the package P010-verified in that case. A complete cloud result preserves `signature_verification=PENDING`, `device_package_acceptance=PENDING`, `unattended_24_7=NOT_VALIDATED`, and `scheduled_wake=UNVERIFIED`.

## H003 follow-up result

On 2026-10-22, H003 verified the exact `ldid` commit/tree and executable hash using two matching builds, retrieved all eight official assets, and ran the actual H002 P011 CLI contract. The command exited `0` and produced `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING`; both embedded entitlement sets independently matched the approved profile. The report is [H003-P011-HOST-PREFLIGHT.json](H003-P011-HOST-PREFLIGHT.json), with the independent signer receipt at [H003-SIGNER-PROVENANCE.json](H003-SIGNER-PROVENANCE.json).

This result updates the host-side status only. Historical checksum coverage remains partial, signature integrity remains pending, all device acceptance gates remain pending, and release authorization remains blocked. The earlier blocked H002 run above remains a historical record.

## Read-only device preflight

Transfer the checked package and script using the operator's authorized method, then run:

```sh
/bin/sh ./scripts/p011_device_preflight.sh /var/mobile/Documents/ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb
```

This command is read-only. It checks the target runtime, rootful assumptions, package state and collisions, launchd/process/socket state, persistent paths, available storage, package hash tooling, manager status, and recovery prerequisites. It never installs/removes packages, terminates processes, removes sockets, enables launchd, changes networking, or acquires an assertion.

## Evidence and device status

P009 remains the machine-readable evidence source. Use the current P009 schema and vocabulary; do not add P011-only states to evidence JSON. Keep the operator's existing October 18 observations at `REVIEW_REQUIRED`. Do not mark package installation, installed binary execution, rollback, idle comparison, battery/thermal impact, long-duration reliability, or scheduled wake as PASS without actual reviewed evidence.

The P011 release-channel package digest can be cloud-verified independently. Physical acceptance remains a separate gate and blocks any P011 claim that the stable Debian package has been accepted on the iPad.
