# P010 — Rootful Package Validation

## Package identity and release ordering

The candidate Debian package remains `com.ioscaffeinate.cli` with rootful architecture `iphoneos-arm`. Its RC package version is `0.1.0~rc1-1`, which sorts before stable `0.1.0-1` under dpkg version comparison. The public-facing intended prerelease identifier is `v0.1.0-rc1`. The architecture remains distinct from the thin ARM64 iOS executable architecture.

CI retains a separate **UNSIGNED / DEVICE-UNVERIFIED** package. A signed package is produced only by an explicit local signing request using [the P010 profile procedure](P010-SIGNING.md). The package includes the signed CLI and daemon, the profile used, a build/signing record, a SHA256SUMS for the final payload, and an inactive launchd template. It does not include active schedules or server policy.

## Validation performed against the final archive

`scripts/validate_rootful_package.py` inspects the `.deb` itself, extracts it into a temporary directory, and checks:

- Package/control identity, `0.1.0~rc1-1`, and `iphoneos-arm` architecture.
- The expected ARM64 iOS 12.0 platform and exact CLI/daemon dynamic dependencies.
- Signature state, profile file contents and digest, signer metadata, source/final executable hashes, and the archive/payload sidecars.
- For a signed package, exact embedded entitlement extraction from both packaged executables. It requires an explicit host-compatible `ldid`; missing extraction capability is a blocker.
- Root ownership, file modes, alias symlink and target, inactive launchd plist, and all incoming-file collision checks.
- Maintainer script names, shell syntax, and lifecycle safety patterns.
- Empty persistent state/log directories, no seeded schedules or server policy, and preservation policy for operator data.

Example commands:

```sh
sha256sum -c dist/package/ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb.sha256
python3 scripts/validate_rootful_package.py \
  dist/package/ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb \
  --ldid /absolute/path/to/host-compatible/ldid \
  --report dist/package/signed-validation.txt
python3 scripts/p010_signed_candidate_manifest.py \
  --ci-manifest dist/package/P010-RELEASE-MANIFEST.json \
  --package dist/package/ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb \
  --ldid /absolute/path/to/host-compatible/ldid \
  --output dist/package/P010-SIGNED-CANDIDATE-MANIFEST.json
```

Use `dpkg-deb --info`, `--contents`, `--control`, and `--extract` to inspect the archive without installing it. The builder refuses to overwrite existing outputs and emits `.sha256`, `.files.sha256`, `.manifest.txt`, and `.manifest.json` sidecars. The JSON manifest links source hashes, final signed binary hashes, profile and signer identity, package hash, verifier result, and device statuses.

The generated signed-candidate release manifest combines the exact-source CI workflow URL/results with local signer, profile, binary, and `.deb` hashes. Its release state remains blocked and device statuses remain unverified. The package scripts never start a daemon, enable or load launchd, create a power assertion, change SSH/Tailscale, or erase persistent data. Package validation is a host-side archive check; it does not install the package or establish jailbreak acceptance.
