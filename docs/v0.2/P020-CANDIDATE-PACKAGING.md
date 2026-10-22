# P020 Candidate Packaging

## Package identity

- Debian package: `com.ioscaffeinate.cli`
- Candidate version: `0.2.0~rc1-1`
- Architecture: `iphoneos-arm`; executable format: thin ARM64 iOS Mach-O
- Default repository/stable version remains `0.1.0-1`
- Signing state: unsigned until the exact P010 signer provenance gate closes

## Candidate build process

On macOS with Xcode and the official iPhoneOS SDK, CI builds two separate clean checkouts into separate output directories. It embeds the exact source SHA and RC version, records compiler/SDK inputs without absolute host paths, inspects Mach-O architecture/deployment target/dependencies, and verifies both SHA256SUMS files. It then packages each tree independently with the fixed `SOURCE_DATE_EPOCH`, validates package metadata and every payload path/mode/checksum, and compares all binary and package hashes.

The Actions artifacts are run-scoped, labeled `UNSIGNED-DEVICE-UNVERIFIED`, and include source/build identity and package inspection reports. They are not published release assets and are not installation-ready. If byte comparison passes, provenance says `REPRODUCIBLE`; otherwise the output identifies differences and never claims a match.

## Payload review

The expected rootful layout contains the CLI, daemon, `ic` symlink, manager, documentation and tools, separate empty state/log directories, and a staged inactive launchd template. No schedule, Server Mode policy, recovery state, credentials, or device evidence is seeded. The staged plist remains disabled and is not copied into `/Library/LaunchDaemons` by installation scripts. Package scripts perform collision/safety checks only; they do not start services, acquire assertions, restart daemons, delete state, or change network access.

The candidate validator does not install a package. A successful package inspection does not establish iOS code-signature acceptance, target-device execution, launchd compatibility, or hardware behavior.

## Publication boundary

No `v0.2.0-1` package, tag, GitHub Release, or public asset is created by P020. Existing v0.1.0 assets remain untouched. Stable publication requires a separately authorized final step after all release gates pass.
