# H002 — Artifact and Evidence Manifest

## Source and review target

| Field | Value |
|---|---|
| Repository | `nghianguyen150612/iOS-Caffeinate` |
| H002 branch | `fix/h002-p011-legacy-checksum` |
| Starting P020 SHA | `57b06c534d18f094ad59e4229e626fae51668de9` |
| P020 PR | [#19](https://github.com/nghianguyen150612/iOS-Caffeinate/pull/19), open at H002 start |
| Stacked PR target | `release/p020-v02-integration` |
| Historical source commit | `0cfdc645dc1d67ddc4320a00bb114763b9669b66` |
| Historical tag | `v0.1.0`, resolving to the historical source commit above |

## Exact published package

| Field | Value |
|---|---|
| Release URL | [v0.1.0](https://github.com/nghianguyen150612/iOS-Caffeinate/releases/tag/v0.1.0) |
| Package | `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb` |
| Debian package | `com.ioscaffeinate.cli` |
| Version / architecture | `0.1.0-1` / `iphoneos-arm` |
| Size | `95,572` bytes |
| Archive SHA-256 | `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c` |

The seven embedded historical checksum records are:

| Path | SHA-256 |
|---|---|
| `usr/local/bin/ios-caffeinate` | `a4957dfacbd2ff84fe4122578e050eee53d8db4b1b04dc89828d3b72494651fe` |
| `usr/local/bin/ios-caffeinated` | `a692c0daff6df9f2aafeb89bbbeabd2439f1efd163cf88fbada75f203bef5cc0` |
| `usr/local/libexec/ioscaffeinate-manager` | `fae0235b67c7b461c02d826becb395b3ae19f69055347361ce681bf0f975c28c` |
| `usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist` | `ef99bafc2f521dfdfbcf52009f87209b357c9058b0984f4d27856ee9b168cc63` |
| `usr/share/ioscaffeinate/SIGNING-STATE` | `dc17a4b9721505d803507b13cfbdffec482d0156107d733f1cf79497e35f50bd` |
| `usr/share/ioscaffeinate/signing/amethyst-ios12-rootful.plist` | `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca` |
| `usr/share/ioscaffeinate/package-build.json` | `f188b7751fa09523f3e6c6d8a1b2b000b79e8e9bb62d99cd2418b1af3c3600c1` |

This seven-record list is the original published checksum scope. The [derived inventory](H002-DERIVED-INVENTORY.json) separately lists the 81 observed package members and 59 regular-file digests, with an explicit `DERIVED_AFTER_PUBLICATION` label. It is not a replacement or reconstruction of the original embedded manifest.

## Pinned release asset digests

The release API returned exactly these eight uploaded assets. P011 verifies each local asset against its pinned size and SHA-256.

| Asset | Bytes | SHA-256 |
|---|---:|---|
| `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb` | 95,572 | `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c` |
| `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb.sha256` | 130 | `2ec6d780ffbd32d10b1c193b5c2707a0493a1006f8e181ffa4af494574cc8009` |
| `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb.files.sha256` | 766 | `d215d778e89d8b642946533c917dad63a6c2276d0b09aef7d9bb3f49e3bd146a` |
| `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb.manifest.json` | 1,478 | `66a15fc039eb4c375b1921e3f6279ec99b39e6edde885967412ebbd6e7b95f1e` |
| `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb.manifest.txt` | 1,320 | `468e47695881e1a88dc601129d328d7a135ccb3d6ccc942a6d51e387182faf49` |
| `P010-RELEASE-MANIFEST.json` | 2,898 | `2c9ceb3c6a3e985a9f88897b4b785b67081ac589ad6fa9ac86f940e689c9834e` |
| `P010-SIGNED-CANDIDATE-MANIFEST.json` | 3,376 | `5c92fe90de9e579dfbfd010d4f36d133f0900388888d553dd7871ad1f3dadc8a` |
| `signed-validation.txt` | 501 | `cf1bc8687ce3dba5e0b6cf1fe6d0e8a03556c5cc6f43c55aa9a272368b66c086` |

## Signer and entitlement provenance

| Field | Pinned value |
|---|---|
| Signer | `ProcursusTeam/ldid` |
| Version | `2.1.5-procursus7` |
| Signer SHA-256 | `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c` |
| Approved profile SHA-256 | `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca` |

The release sidecars and embedded build metadata match these pinned values. The H001 executable and receipt files were not present in the actual workspace, so this manifest records the expected identity, not a fresh local executable verification. P011 remains blocked before independent entitlement extraction until the exact verified H001 executable is supplied.

## Status semantics

```text
archive_sha256=VERIFIED
published_checksum_scope=LEGACY_REQUIRED_SET
published_checksum_entries=7
full_payload_manifest=NOT_PRESENT_IN_HISTORICAL_RELEASE
derived_payload_inventory=AVAILABLE_AFTER_PUBLICATION
signer_provenance=PUBLISHED_METADATA_MATCHED_PINNED_H001_IDENTITY_EXECUTABLE_MISSING
embedded_entitlements=PENDING_PINNED_LDID
signature_integrity=PENDING
device_execution=UNVERIFIED
device_package_acceptance=PENDING
```

These fields are computed from the input evidence; they are not prefilled validation outcomes.
