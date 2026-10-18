# P007 Packaging Validation

## Hosted CI sequence

The `ios-rootful-package` GitHub Actions job waits for `linux-protocol` and `ios-artifact-inspection`. The latter follows the successful iOS cross-build. The package job downloads the two binaries and checksum manifest from that same workflow run, plus the inspection report. It confirms the report establishes unsigned iOS 12.0 ARM64 device Mach-O files and rechecks the source SHA-256 values before packaging.

The job then runs the isolated package regression suite, builds an `iphoneos-arm` Debian package with `dpkg-deb`, extracts it into temporary directories, validates its archive/control metadata and checksums, and uploads the `.deb`, hash files, build manifest, and validation report. It never runs `dpkg -i` and never writes to a device.

The job's artifact name identifies both architecture and signing state:

```text
iOS-Caffeinate-rootful-iphoneos-arm-UNSIGNED-DEVICE-UNVERIFIED
```

Only the exact final commit's successful workflow run establishes hosted P007 package validation. Artifact inspection and package validation do not establish device installation, signature acceptance, execution, IOKit behavior, network survival, or 24/7 readiness.

## Package gates

`scripts/validate_rootful_package.py` validates:

- Package identifier `com.ioscaffeinate.cli`, version `0.1.0-1`, `Architecture: iphoneos-arm`, metadata and the no-extra-dependency policy.
- Root ownership and expected modes in the Debian archive.
- Thin ARM64 iOS Mach-O format and exact iOS 12.0 minimum target for both binaries.
- Checksums for the packaged CLI, daemon, manager, staged launchd plist, and explicit signing-state record.
- Canonical file names and `ic -> ios-caffeinate` as an actual relative symlink.
- No duplicate, absolute, traversal, unsupported, or root-escaping symlink paths.
- No mock binary, active LaunchDaemons path, schedule fixture, or server-mode fixture.
- Disabled launchd template, only the necessary `preinst`/`prerm`, shell syntax, and prohibited lifecycle operations.
- Isolated extraction consistency and the package SHA-256 sidecar.

The 20 deterministic package tests run without root. They build a temporary package from generated, non-runnable Mach-O metadata fixtures; those test inputs are never used in the hosted product package. The suite covers valid package identity and layout, reproducible output, source hashes, absent inputs, safe output collision refusal, wrong CPU architecture, arm64e refusal, iOS minimum target, signature-state refusal, duplicate and traversal paths, symlink and executable modes, disabled startup, no seeded data, simulated removal with operator state preserved, maintainer script syntax/idempotency/safety, rollback prerequisites, and no host installation/service activation.

The existing `linux-protocol` job remains intact and tests the explicit Linux mock backend. The iOS cross-build and macOS artifact inspection jobs remain intact and inspect the actual product executables. These reports are separate evidence and must not be conflated.

## Local commands

```sh
python3 -m unittest discover -s tests/packaging -v
./scripts/build-linux-test.sh
python3 tests/integration.py
```

For an actual iOS build, use macOS with Xcode and the official iPhoneOS SDK:

```sh
./scripts/build-macos.sh
python3 scripts/inspect-ios.py
```

After retrieving those actual binaries and their `SHA256SUMS`, Linux can build and inspect the package:

```sh
./scripts/package-rootful.sh --input-dir dist --output-dir dist/package
python3 scripts/validate_rootful_package.py dist/package/*.deb
```

The package validator extracts into temporary directories only. Do not install a CI artifact into the CI host.

## Evidence categories

| Gate | P007 evidence |
|---|---|
| Cross-build | macOS Xcode/iPhoneOS SDK workflow job |
| Mach-O format, architecture, minimum OS, dependencies, unsigned state | `ios-artifact-inspection` report |
| Debian metadata, payload paths, modes, hashes, script safety | `ios-rootful-package` validation report |
| Package archive integrity | `.deb` SHA-256 sidecar |
| Signature presence | Absent in CI artifact; optional local `ldid -S` output is only checked for presence |
| Signature verification | PENDING |
| Package installation | PENDING |
| iOS 12 binary execution | PENDING |
| IOKit assertion create/release | PENDING |
| Locked-screen LAN SSH/Tailscale | PENDING, measured separately |
| Battery/thermal observations | PENDING |
| 24/7 operation | NOT VALIDATED |

P007 status is **PARTIAL — cloud packaging engineering complete** at its milestone. P010 later records operator-reported native execution and assertion observations, but the P007 package remains a historical unsigned artifact and its device package gates were not exercised. Current acceptance is tracked in [P010 release readiness](P010-RELEASE-READINESS.md).
