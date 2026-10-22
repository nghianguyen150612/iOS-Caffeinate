# H002 — v0.1.0 Checksum and Layout Audit

## Finding

The published `v0.1.0` package has a valid archive digest and a historically valid seven-record `SHA256SUMS`. That file was never a complete checksum manifest for every regular payload file. The current P020 validator correctly requires full regular-file coverage for current packages, so its rule cannot be applied to the original archive as though it had been published with a complete manifest.

The official package was retrieved from the GitHub `v0.1.0` release and independently hashed as:

```text
ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb
439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c
```

The decoded Debian data archive contains 81 members: 59 regular files, 21 directories, and one `usr/local/bin/ic -> ios-caffeinate` symlink. There are no hardlinks or special files. The 59 regular-file count includes the `SHA256SUMS` file itself. Seven records cover the two signed executables, manager, launchd template, signing state, entitlement profile, and package build metadata. The other 52 regular members are the checksum file itself plus 51 ordinary documentation/license files. Excluding the self-referential checksum file, 51 regular payload files are not covered.

The 52 uncovered members break down as follows. Every member is a regular file; the exact path, mode, ownership, derived digest, and purpose are recorded in the [post-publication derived inventory](H002-DERIVED-INVENTORY.json).

| Count | Paths | Purpose |
|---:|---|---|
| 1 | `usr/share/ioscaffeinate/SHA256SUMS` | The checksum file cannot include its own digest. |
| 2 | `usr/share/doc/ioscaffeinate/README.md`, `usr/share/doc/ioscaffeinate/LICENSE` | Top-level documentation and license. |
| 38 | `usr/share/doc/ioscaffeinate/docs/*` at the docs root | Project architecture, milestone, safety, packaging, and acceptance documentation. |
| 2 | `usr/share/doc/ioscaffeinate/docs/evidence/*` | Historical evidence notes. |
| 3 | `usr/share/doc/ioscaffeinate/docs/releases/*` | Historical release notes and records. |
| 5 | `usr/share/doc/ioscaffeinate/docs/schemas/*` | Evidence and release JSON schemas. |
| 1 | `usr/share/doc/ioscaffeinate/docs/templates/*` | Device acceptance evidence template. |

The historical validator defined six fixed required paths and added the signing profile when present. It verified those records and required that exact set (`scripts/validate_rootful_package.py` at stable source `0cfdc645dc1d67ddc4320a00bb114763b9669b66`, lines 32–40 and 166–185). The historical builder populated the manifest from `payload_hash_paths`, not from every regular file: see `scripts/package_rootful.py` at that source, lines 218–307 and 349–358. README, LICENSE, and all files under `docs/` were copied into the package but were not added to `payload_hash_paths`.

At P020, `check_sha_manifest()` enumerates every regular file in the extracted package except `SHA256SUMS` and requires the record set to equal that complete set (`scripts/validate_rootful_package.py`, lines 210–231). It must remain strict for all newly produced packages. P020 also added four required packaged tools under `usr/share/doc/ioscaffeinate/tools/` (`scripts/package_rootful.py`, lines 51–56 and 325–329; `scripts/validate_rootful_package.py`, lines 32–44 and 122–179). Comparing the v0.1.0 archive with the P020 expected path set at the historical source SHA shows five absent entries: the `tools/` directory and those four files. The remaining signed profile paths are present in the package and are included in the expected set when the package is marked signed.

These are independent incompatibilities: the historical manifest does not cover every regular file, and the current package layout requires P020 documentation tools that were not part of the released v0.1.0 layout.

## Derived inventory boundary

`H002-DERIVED-INVENTORY.json` was produced after publication from the archive whose outer SHA-256 matches the pinned release value. It records the observed members and per-file digests for audit and exact layout checks. It is explicitly labeled `DERIVED_AFTER_PUBLICATION`; it is not the original embedded `SHA256SUMS`, a publisher-supplied full manifest, or evidence that v0.1.0 had full checksum coverage.

The derived inventory is useful only inside the exact-artifact exception. A package with any changed byte fails the pinned archive SHA-256 before this inventory or the compatibility rules are used.

## Source references

- Historical source: [`0cfdc645dc1d67ddc4320a00bb114763b9669b66`](https://github.com/nghianguyen150612/iOS-Caffeinate/tree/0cfdc645dc1d67ddc4320a00bb114763b9669b66)
- P020 source at H002 start: [`57b06c534d18f094ad59e4229e626fae51668de9`](https://github.com/nghianguyen150612/iOS-Caffeinate/tree/57b06c534d18f094ad59e4229e626fae51668de9)
- Dedicated compatibility code: `scripts/p011_legacy_package_validator.py`
- P011 routing and host result: `scripts/p011_release_preflight.py`
- Current strict checksum contract, unchanged: `scripts/validate_rootful_package.py`
