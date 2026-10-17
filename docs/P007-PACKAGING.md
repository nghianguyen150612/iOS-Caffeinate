# P007 Rootful Debian Packaging

## Package identity and support boundary

P007 builds `com.ioscaffeinate.cli` version `0.1.0-1`, with Debian architecture `iphoneos-arm`. The packaged executable files are thin ARM64 Mach-O binaries built for iOS 12.0. The package architecture describes the rootful package-manager convention; it is not the executable CPU architecture. Theos documents `iphoneos-arm` for rootful iOS and `iphoneos-arm64` for rootless iOS in its [packaging guide](https://theos.dev/docs/packaging). P007 supports only the former.

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
| `/usr/share/ioscaffeinate/SHA256SUMS` | `0644` file | Checksums for packaged executables, signing-state record, and launchd template |
| `/usr/share/ioscaffeinate/SIGNING-STATE` | `0644` file | Explicit signature-presence and device-verification state |
| `/usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist` | `0644` file | Inert launchd template, staged outside active LaunchDaemons |
| `/usr/share/doc/ioscaffeinate/README.md`, `LICENSE`, `docs/**` | `0644` files | Project documentation and validation procedures |

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

The unsigned output is named like `ioscaffeinate_0.1.0-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb`. Adjacent files contain the package SHA-256, checksums for packaged executables/template, and build metadata. Inspect an artifact without installing it:

```sh
sha256sum -c ioscaffeinate_0.1.0-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb.sha256
dpkg-deb --info ioscaffeinate_0.1.0-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb
dpkg-deb --contents ioscaffeinate_0.1.0-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb
dpkg-deb --control ioscaffeinate_0.1.0-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb control-view
dpkg-deb --extract ioscaffeinate_0.1.0-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb extracted-view
python3 scripts/validate_rootful_package.py ioscaffeinate_0.1.0-1_iphoneos-arm_UNSIGNED-DEVICE-UNVERIFIED.deb
```

These commands inspect or extract into a chosen directory. They do not install the package.

## Signing boundary

CI packages the unsigned iOS build and labels it **UNSIGNED / DEVICE-UNVERIFIED**. This is not an installation-ready or execution-ready claim.

When an operator has already obtained a trusted `ldid` binary through a controlled source, the builder supports an optional ad-hoc pseudo-signing stage:

```sh
./scripts/package-rootful.sh --input-dir dist --output-dir dist/package \
  --sign-with-ldid /absolute/path/to/ldid
```

The builder invokes `ldid -S` separately on the CLI and daemon without supplying entitlements. The Procursus [ldid manual](https://github.com/ProcursusTeam/ldid/blob/master/docs/ldid.1) describes `-S` as pseudo-signing Mach-O binaries. It does not download, build, or execute a signing tool fetched during packaging. The builder checks for the resulting Mach-O code-signature load command and labels output **SIGNED / DEVICE-UNVERIFIED**. That check establishes signature presence only. The manual's `ldid -h` option displays signature metadata (hash types, flags, CDHash, and CodeDirectory version); it is not documented as a signature verification operation. Neither signature presence nor that metadata proves the iPad's jailbreak accepts or executes the binary. No extra entitlements, platform-application privileges, or unrelated exceptions are added.

The gates remain distinct: cross-build, Mach-O inspection, signature presence, signature verification, Debian archive integrity, package installation, iOS 12 execution, and power-assertion behavior. Real-device signing acceptance and execution remain pending. Follow [P007 device validation](P007-DEVICE-TEST.md) before any device deployment.

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
