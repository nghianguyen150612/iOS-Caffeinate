# P010 — Hardware Signing Profile

## Approved profile

`packaging/signing/profiles/amethyst-ios12-rootful.plist` is the versioned profile ID `amethyst-ios12-rootful`. It contains exactly one entitlement: `com.apple.private.security.no-container=true`. The builder rejects malformed or semantically different plists, including additional entitlements. It never adds `platform-application`, task-port privileges, or any other entitlement automatically.

Signing is opt-in. The operator must provide both an explicit absolute path to a trusted, host-compatible `ldid` executable and the approved profile:

```sh
./scripts/package-rootful.sh \
  --input-dir dist \
  --output-dir dist/package \
  --sign-with-ldid /absolute/path/to/host-compatible/ldid \
  --entitlements packaging/signing/profiles/amethyst-ios12-rootful.plist
```

The trusted iOS `/usr/bin/ldid` binary is not assumed to execute on Linux. The builder does not download or bundle signers. A Linux host may build the host-compatible Procursus signer from its pinned upstream source; an iOS executable copied from the device is not a host-compatible choice. For Debian hosts with `build-essential`, `libplist-dev`, and `libssl-dev` installed:

```sh
git clone https://github.com/ProcursusTeam/ldid.git ldid-p010
git -C ldid-p010 checkout --detach aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef
make -C ldid-p010 VERSION=2.1.5-procursus7
sha256sum ldid-p010/ldid
ldid-p010/ldid
```

The pinned source is the Procursus `v2.1.5-procursus7` tag at commit `aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef`. Review the source and host build dependencies before using it. The signer must emit its `Link Identity Editor <version>` banner; the package builder records that version and the exact signer SHA-256. The recorded executable hash is host/build-specific.

## What the builder checks

The input directory contains the unsigned CLI, daemon, and `SHA256SUMS`. Source hashes and unsigned ARM64/iOS 12.0 Mach-O metadata are checked before signing. Each executable is copied to an isolated temporary staging tree and the copy hash is compared with the exact source hash. The builder signs both copies using the ldid argument form `-S<profile-path>`, extracts their embedded entitlements with `ldid -e`, and requires an exact semantic match to the approved profile.

After signing, the builder checks the iOS device platform, ARM64 architecture, minimum deployment target, expected dynamic dependencies, and `LC_CODE_SIGNATURE`. It removes the final code-signature load command and blob, restores only the `__LINKEDIT` file/virtual sizes that ldid expands to contain that blob, and compares every remaining byte with the unsigned source. This rejects a signer that replaces the staged executable with an unrelated binary. Original input files are never modified.

The package record contains source and final CLI/daemon SHA-256 values, profile ID/hash, signer version/hash, entitlement extraction result, and separate integrity/device states. If macOS `codesign` is available, the builder runs `codesign --verify --strict --verbose=2` for both signed binaries and records each exact command, output, and exit code. Without that verifier, signature integrity stays `PENDING`. `ldid -e`, `LC_CODE_SIGNATURE`, and successful signing establish neither cryptographic integrity verification nor device trust.

## Status vocabulary

| Field | Meaning |
|---|---|
| `UNSIGNED` | No code-signature load command is present. |
| `SIGNATURE_PRESENT` | The Mach-O signature command and blob exist; embedded entitlements were extracted and matched to the approved profile. |
| `SIGNATURE_VERIFIED` | A host signature-integrity verifier reported success. This still does not mean a jailbreak trusts the executable. |
| `DEVICE_EXECUTION_VERIFIED` | The exact signed executable ran on the target device and the evidence passed P009 review. |
| `DEVICE_PACKAGE_ACCEPTED` | The signed `.deb` was installed and its package acceptance checks passed on the target under supervision. |

The package itself records `signature_integrity=PENDING` when no host verifier ran, `device_execution=NOT_VERIFIED`, and `device_package_acceptance=NOT_ACCEPTED`. No unsigned output is named or described as signed. There is no externally pre-signed input mode; unsupported provenance fails closed.

To bind the local candidate back to the exact CI run after package validation, generate a signed-candidate release manifest from the CI `P010-RELEASE-MANIFEST.json`, the signed `.deb`, and the same ldid executable:

```sh
python3 scripts/p010_signed_candidate_manifest.py \
  --ci-manifest dist/package/P010-RELEASE-MANIFEST.json \
  --package dist/package/ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb \
  --ldid /absolute/path/to/host-compatible/ldid \
  --output dist/package/P010-SIGNED-CANDIDATE-MANIFEST.json
```

The generator revalidates the archive, matches both unsigned executable hashes to CI, checks the signed package and profile records, and keeps device acceptance and release authorization blocked.

## Test signer boundary

P010 regression tests use a deterministic fixture signer that adds a synthetic signature command and embeds the profile bytes so the command construction, hash linkage, entitlement extraction, and rejection paths can be tested offline. This fixture is not Apple runtime signing and cannot establish device acceptance. Hosted CI continues to build and publish only unsigned binaries and the distinct unsigned CI package.
