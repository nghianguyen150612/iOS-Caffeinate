# P011 — Release and milestone manifest

This is a static identity record for P011. It is not a signed attestation, test log, or device evidence bundle. Run-specific test counts and exact commit identifiers belong in CI artifacts.

## Published baseline

| Field | Expected value |
|---|---|
| Repository | `nghianguyen150612/iOS-Caffeinate` |
| Stable tag | `v0.1.0` |
| Release URL | <https://github.com/nghianguyen150612/iOS-Caffeinate/releases/tag/v0.1.0> |
| Known main/source baseline | `0cfdc645dc1d67ddc4320a00bb114763b9669b66` |
| Package | `com.ioscaffeinate.cli` |
| Debian version | `0.1.0-1` |
| Debian architecture | `iphoneos-arm` |
| Signed package filename | `ioscaffeinate_0.1.0-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb` |
| Published package SHA-256 | `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c` |
| Device binary architecture | ARM64 |
| Minimum iOS | 12.0 |
| Target | iPad mini 2 A1489 (`iPad4,4`), iOS 12.5.7, Amethyst/Procursus rootful |

Expected release assets are the signed `.deb`, `.deb.sha256`, `.deb.files.sha256`, `.deb.manifest.json`, `.deb.manifest.txt`, `P010-RELEASE-MANIFEST.json`, `P010-SIGNED-CANDIDATE-MANIFEST.json`, and `signed-validation.txt`. The verifier rejects an unexpected GitHub tag, asset set, package hash, Debian identity, version, architecture, profile, or manifest relationship.

## Signing profile and current limits

| Field | Published record |
|---|---|
| Profile ID | `amethyst-ios12-rootful` |
| Profile path | `packaging/signing/profiles/amethyst-ios12-rootful.plist` |
| Profile SHA-256 | `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca` |
| Exact entitlement | `com.apple.private.security.no-container=true` |
| Signing tool | `ldid 2.1.5-procursus7` |
| Recorded ldid SHA-256 | `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c` |
| Signature integrity | `PENDING` |
| Embedded entitlement result | `EXACT_MATCH` in the published P010 record |
| Device execution | `NOT_VERIFIED` |
| Device package acceptance | `NOT_ACCEPTED` |
| Release authorization | `BLOCKED` in P010 manifests |

The private entitlement is only for the approved Amethyst/Procursus rootful profile. Do not reuse it as a general jailbreak entitlement. Signature presence and a matching profile record do not establish cryptographic trust or device acceptance.

## P011 output files

- `scripts/p011_release_preflight.py`: pinned, read-only release and package verifier; optional GitHub HTTPS retrieval uses Python's standard library.
- `scripts/p011_device_preflight.sh`: POSIX shell read-only target inspection.
- `docs/v0.2/ROADMAP.md`: P011–P020 deliverables, dependencies, safety, validation, and completion gates.
- `docs/v0.2/P011-DEVICE-ACCEPTANCE.md`: ordered attended procedure; install/removal/rollback are separately authorized.
- `docs/v0.2/P011-EVIDENCE-MATRIX.md`: conceptual status mapping to the existing P009 vocabulary.
- `docs/v0.2/P011-VALIDATION.md`: cloud validation and device-preflight commands.
- `tests/test_p011_preflight.py`: offline negative and invariant tests.

## Current acceptance state

The release-channel identity and published package digest can be checked in cloud. The physical gates remain `PENDING` or `REVIEW_REQUIRED`: stable package installation, installed CLI/daemon execution, package removal and rollback, P009 review, no-assertion comparison, battery/thermal impact, long-duration reliability, and scheduled wake. No timestamp, log, checksum, or device measurement is implied by this manifest beyond the published release metadata above.
