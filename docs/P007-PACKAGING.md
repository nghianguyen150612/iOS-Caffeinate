# P007 Rootful Debian Packaging

**Current operator guidance:** P018 adds manager-backed preflight and a read-only first-session runbook. The P007 device commands below are historical package procedures, not authorization to mutate the current device. Follow [P018 device acceptance](v0.2/P018-DEVICE-ACCEPTANCE.md) and obtain separate explicit authorization before installation or removal.

## Package identity and support boundary

P007 established package `com.ioscaffeinate.cli` and Debian architecture `iphoneos-arm`. P010's RC package uses version `0.1.0~rc1-1`; stable `0.1.0-1` remains the intended subsequent package version. The packaged executable files are thin ARM64 Mach-O binaries built for iOS 12.0. The package architecture describes the rootful package-manager convention; it is not the executable CPU architecture. Theos documents `iphoneos-arm` for rootful iOS and `iphoneos-arm64` for rootless iOS in its [packaging guide](https://theos.dev/docs/packaging). P010 continues to use the former.

The package has no explicit runtime package dependencies. It uses the operating system libraries already present on iOS and does not depend on tweak frameworks, injection libraries, or package-specific launch services. A future device must report `iphoneos-arm` from `dpkg --print-architecture` before installation. Dpkg's package architecture check and the package `preinst` both fail closed on a mismatch.

The control metadata uses section `utils`, priority `optional`, and maintainer `iOS-Caffeinate contributors <ios-caffeinate@users.noreply.github.com>`. The package contains no Linux mock executable or test fixture.

## Installed file manifest

The package installs these files and directories as root-owned entries:

| Package path | Mode / type | Purpose |
|---|---|---|
| `/usr/local/bin/ios-caffeinate` | `0755` executable | Canonical CLI |
| `/usr/local/bin/ios-caffeinated` | `0755` executable | Canonical daemon |
| `/usr/local/bin/ic` | symlink to `ios-caffeinate` | CLI shorthand |
| `/usr/local/libexec/ioscaffeinate-manager` | `0755` executable | Read-only package and device checks |
| `/var/lib/ioscaffeinate/` | `0750` directory | Persistent schedules and optional server policy; no files are seeded |
| `/var/log/ioscaffeinate/` | `0750` directory | Operator and daemon logs; no files are seeded |
| `/usr/share/ioscaffeinate/SHA256SUMS` | `0644` file | Checksums for packaged executables, package metadata, documentation, and P009/P018 tools |
| `/usr/share/ioscaffeinate/SIGNING-STATE` | `0644` file | Separate signature, integrity, device-execution, and package-acceptance states |
| `/usr/share/ioscaffeinate/package-build.json` | `0644` file | Source/final hashes and signing provenance record |
| `/usr/share/ioscaffeinate/signing/amethyst-ios12-rootful.plist` | `0644` file when signed | The opt-in P010 profile used for this candidate |
| `/usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist` | `0644` file | Inert launchd template, staged outside active LaunchDaemons |
| `/usr/share/doc/ioscaffeinate/README.md`, `LICENSE`, `docs/**`, `tools/*.py` | `0644` files | Project documentation, P009 validator, and P018 preflight/inventory/export tools |

The launchd template has `Disabled=true` and `RunAtLoad=false`. It is not installed at `/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist`. Installing the package does not load, bootstrap, enable, or start a service. Activation requires separate authorization after device validation.

No `schedules.json` or `server-mode.json` is included. A missing server-mode file continues to mean `DISABLED`. Dpkg may remove the package's empty state or log directories during ordinary removal; it leaves any non-empty directories and all operator-created contents in place. The package has no purge operation and no post-removal script. It never clears schedules, server policy, logs, or evidence.

## Maintainer scripts

Only `preinst` and `prerm` are included; there is no `postinst` or `postrm`.

- `preinst` checks that the target dpkg architecture is `iphoneos-arm`, refuses symlink or non-directory collisions at package directories, and refuses to overwrite any incoming file or symlink not already owned by this package. It does not create data, change SSH/Tailscale, or start services.
- `prerm` refuses upgrade/removal while any entry exists at the default daemon socket path. This detects a live socket and also fails closed on a stale or unexpected entry. It prints operator instructions and does not remove the endpoint, signal a process, or claim that an assertion was released. A daemon launched with a custom socket path cannot be detected by this script; the operator must check it separately.

Both scripts are noninteractive and read-only. The package includes no network access, reboot/respring, recursive delete, broad ownership changes, process-name termination, launchd control, or daemon launch. Package extraction and script validation happen in CI without `dpkg -i`.

## Building and inspecting

The iOS build emits unsigned executables and a `SHA256SUMS` file. From a Linux host with `dpkg-deb`:

```sh
./scripts/package-rootful.sh --input-dir dist --output-dir dist/package
```

The builder verifies the input manifest, executable Mach-O format, ARM64 CPU type, iOS device platform, exact 12.0 minimum target, and absence of a code-signature load command. It rejects arm64e-only, wrong-architecture, higher-deployment-target, altered, missing, or already-signed input binaries. It uses isolated staging, normalizes timestamps with `SOURCE_DATE_EPOCH`, and builds the `.deb` with `dpkg-deb --root-owner-group`.

The unsigned RC output is named like `ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb`. Adjacent files contain the package SHA-256, payload checksums, and JSON/text build metadata. Inspect an artifact without installing it:

```sh
sha256sum -c ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb.sha256
dpkg-deb --info ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb
dpkg-deb --contents ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb
dpkg-deb --control ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb control-view
dpkg-deb --extract ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb extracted-view
python3 scripts/validate_rootful_package.py ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb
```

These commands inspect or extract into a chosen directory. They do not install the package.

## Signing boundary

CI packages the unsigned iOS build and labels it **UNSIGNED / DEVICE-UNVERIFIED**. This is not an installation-ready or execution-ready claim. P010 defines the only supported opt-in profile and the signing workflow in [P010-SIGNING.md](P010-SIGNING.md):

```sh
./scripts/package-rootful.sh --input-dir dist --output-dir dist/package \
  --sign-with-ldid /absolute/path/to/host-compatible/ldid \
  --entitlements packaging/signing/profiles/amethyst-ios12-rootful.plist
```

The builder invokes `ldid -S<profile>` on isolated CLI/daemon copies, extracts embedded entitlements, checks exact-source binary identity, and records profile/tool/source/final hashes. It uses `codesign --verify --strict --verbose=2` when Apple's host verifier is available; otherwise signature-integrity status remains `PENDING`. `ldid -h` output and `LC_CODE_SIGNATURE` establish neither host verification nor device trust. The trusted iOS signer is not assumed to run on Linux. There is no profile auto-selection or pre-signed-input mode, and no extra or unrelated entitlement is accepted.

The gates remain distinct: cross-build, Mach-O inspection, signature presence, signature integrity, Debian archive integrity, package installation, iOS 12 execution, and power-assertion behavior. Operator-reported execution/assertion/network results are documented in [P010 hardware findings](P010-HARDWARE-FINDINGS.md) and remain subject to P009 review. Signed package installation and rollback remain pending. Follow [P010 device acceptance](P010-DEVICE-ACCEPTANCE.md) before any package deployment.

## Read-only manager

Run `/usr/local/libexec/ioscaffeinate-manager` with one of these commands:

```text
status          report package metadata, files, checksums, architecture, permissions, launchd and socket state
verify          return failure if package metadata, binary checksums, architecture, alias or ownership/modes fail
doctor          report the same gates and missing local inspection tools
rollback-check  /absolute/path/to/previous.deb
uninstall-check show package removal prerequisites and state-preservation policy
```

All commands are read-only. `rollback-check` requires a matching `.sha256` sidecar and checks package name, architecture, and that its version predates the installed version. It does not install or restore the artifact and cannot prove the previous operational state. Status reports default-socket presence separately from custom-socket activity, and always reports physical behavior as unverified. No lifecycle-changing command is provided.

Before any later installation, check `dpkg --print-architecture`, available disk, package hash, signature evidence, collisions, ownership/modes, SSH/Tailscale health, and a physical recovery path. Use the deferred device and rollback procedures; P007 itself does not deploy to an iPad.
