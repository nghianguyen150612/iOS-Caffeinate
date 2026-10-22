# H002 — Security Review

## Trust boundary

The historical exception begins only after an exact archive digest match for the published v0.1.0 package. Filenames, embedded metadata, and checksum records cannot substitute for that digest. The release API identity, pinned package SHA, and pinned sidecar SHA values are checked independently.

## Archive inspection

The validator streams the Debian data and control archives through `dpkg-deb`; it never installs the package and never executes a maintainer script. It rejects duplicate paths, absolute paths, traversal, unexpected members, hardlinks, special files, unsafe symlinks, non-root ownership, and modes that differ from the derived historical inventory. The only allowed symlink is `usr/local/bin/ic -> ios-caffeinate`.

The seven embedded checksum entries must use strict lowercase SHA-256 syntax, have unique paths, match the historical required set, and hash to the corresponding archive bytes. The validator enumerates every regular member and reports the 52 members outside that set, including the checksum file itself. It never reports the historical set as complete coverage.

Debian control metadata and the exact `control`, `preinst`, and `prerm` file set are checked. Scripts are syntax-checked with `sh -n -c` and scanned for state-changing or network behavior; they are not run. Every incoming file and symlink must be guarded by the historical pre-install ownership checks.

## Provenance and signing

Embedded and external package metadata must match the pinned package and P010 values, including source SHA, signing state, signer version/SHA, profile SHA, source and final binary hashes, and pending signature-integrity state. All eight public release assets are bound to the SHA-256 values observed from the official release and checked by P011. The derived file inventory is labeled as post-publication audit data and is not accepted as original publisher metadata.

The Mach-O checks verify ARM64 iOS 12 binaries and signature presence. Exact entitlement extraction requires the exact H001 signer executable and is blocked when that input is unavailable. The report preserves `signature_integrity=PENDING`; signature presence and embedded entitlement matching do not establish cryptographic trust or iOS acceptance.

## Preservation of current validation

`scripts/validate_rootful_package.py` and its full regular-file coverage rule are unchanged. The compatibility validator is a separate P011 path pinned to the exact archive SHA; it does not change P018 or P020 candidate inspection or release gates. The packaging regression builds a full-coverage v0.2 candidate and verifies that removing one record fails current validation.

No release assets were edited. No package was signed, installed, or published. No device was accessed. P020 CI continues to require exact-source checks and keeps simulated evidence unable to satisfy hardware gates.
