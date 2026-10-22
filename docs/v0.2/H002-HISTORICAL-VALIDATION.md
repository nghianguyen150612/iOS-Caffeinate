# H002 — Historical Package Validation

## Scope

The compatibility validator accepts only the published v0.1.0 artifact identity:

- Repository/release: `nghianguyen150612/iOS-Caffeinate`, tag `v0.1.0`
- File: `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb`
- Debian identity: `com.ioscaffeinate.cli`, version `0.1.0-1`, architecture `iphoneos-arm`
- Archive SHA-256: `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c`
- Source commit: `0cfdc645dc1d67ddc4320a00bb114763b9669b66`

`verify_official_archive_identity()` checks the exact filename, regular-file status, size, and archive digest before `dpkg-deb`, checksum parsing, or historical layout validation. Other `0.1.0-1` packages do not enter this path. P011 continues to check the GitHub release API identity and every pinned release-asset digest, then validates the package and sidecars.

## Historical checks

The versioned result from `scripts/p011_legacy_package_validator.py` reports:

- Exact archive SHA-256 and publisher release-asset identity.
- All seven historical checksum records, with duplicate, malformed, missing, and modified records rejected.
- The complete package member layout compared with `H002-DERIVED-INVENTORY.json`, including type, path, root ownership, mode, size, symlink target, and derived member digest.
- Debian control identity, the exact control-file set, and non-executed maintainer-script syntax and safety checks.
- Package build metadata, signing state, entitlement profile bytes, published sidecars, P010 manifests, source SHA, signer claims, and final binary digests.
- CLI and daemon Mach-O architecture, iOS platform, minimum OS, dependencies, and signature presence.
- Embedded entitlement extraction only when the supplied signer passes the pinned H001 version and SHA-256 checks.

The uncovered-member list contains 52 regular members under the stated count convention: `SHA256SUMS` itself and 51 documentation/license files. Each is returned with its path, type, and purpose. The JSON inventory is derived after publication; the result always reports `full_payload_manifest=NOT_PRESENT_IN_HISTORICAL_RELEASE` and `published_checksum_scope=LEGACY_REQUIRED_SET`.

## Integrity levels stay separate

The host report distinguishes the archive digest from release metadata, historical checksum scope, the derived inventory, signer executable provenance, independently extracted entitlements, signature integrity, and physical acceptance. A published `embedded_entitlements=EXACT_MATCH` claim is not treated as a fresh entitlement check. A complete host run requires the exact H001 executable:

```text
ProcursusTeam/ldid 2.1.5-procursus7
SHA-256 15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c
```

The current workspace did not contain this executable or an H001 build receipt file. P011 therefore reports the verified release metadata, validated archive structure and seven checksum records, then blocks before entitlement reinspection. It does not select another `ldid` automatically. Signature integrity remains `PENDING`; device execution is `UNVERIFIED`; device package acceptance is `PENDING`.

The H002 implementation does not modify `scripts/validate_rootful_package.py`. New packages, including v0.2 candidates, continue to require full regular-file checksum coverage. The historical exception is isolated to the exact pinned archive SHA and does not grant compatibility to arbitrary legacy-version packages.

## Observed host result

The exact GitHub release API and local release assets were checked. The official package SHA-256 matched. The legacy manifest had seven valid records; the full layout had 81 members; package structure, signing metadata, sidecars, Mach-O properties, and maintainer-script checks passed. The P011 command exited `1` with the precise remaining blocker: the pinned H001 `ldid` executable was not available for independent embedded-entitlement extraction.

The machine-readable result has schema version `1`. P011 emits `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING` only after all applicable host checks, including pinned signer identity and entitlement extraction, pass. A host pass never changes `device_acceptance=PENDING` or release authorization.
