# P008 — Release Readiness Snapshot

This document records the P008 status before the October 18, 2026 device test. P010 supersedes its physical-device rows; current statuses are in [P010 release readiness](P010-RELEASE-READINESS.md). The P010 operator observations remain unreviewed and do not imply signed package acceptance.

This repository matrix describes the source and local results. The generated matrix in the exact-SHA CI attestation artifact updates the hosted cloud gates using observed job results. Device rows remain independent of CI.

## Engineering gates

| Gate | Repository status | Evidence or condition |
|---|---|---|
| Source and milestone integration | PASS | P001–P007 tree audit and PR comparison in [P008 integration](P008-INTEGRATION.md) |
| CLI/daemon command contracts | PASS | 45 Linux integration tests, including integrated `ic` smoke coverage |
| C11 Linux regression | PASS | Explicit no-power mock build and integration suite |
| iOS ARM64 cross-build | PENDING | Must pass on the official iPhoneOS SDK at the final pushed SHA |
| iOS artifact inspection | PENDING | Mach-O platform, ARM64, iOS 12.0, dependencies, and unsigned state |
| Rootful package build and inspection | PENDING | Debian metadata, package payload, permissions, maintainer scripts, and hashes |
| Security regression | PASS | Source-level audit and mock negative tests; device security behavior remains pending |
| Documentation and release manifest | PASS | P008 docs, schema, and workflow-generated manifest/attestation |

## Device gates

| Gate | Status |
|---|---|
| iOS 12.5.7 binary execution | PENDING |
| Code-signature acceptance | PENDING |
| IOKit assertion acquisition | PENDING |
| IOKit assertion release | PENDING |
| Bounded trial expiry | PENDING |
| STOP/SIGTERM cleanup | PENDING |
| Display-locked LAN SSH | PENDING |
| Display-locked Tailscale SSH | PENDING |
| Battery observation | PENDING |
| Thermal observation | PENDING |
| Physical recovery | PENDING |
| Installation and rollback | PENDING |
| Scheduled wake | PENDING — capability remains UNVERIFIED |

## Authorization

The cloud candidate is not a production release. Release authorization is **BLOCKED** until physical acceptance and signing/installation requirements are reviewed. P008 does not authorize device deployment, automatic daemon activation, an indefinite assertion, a public release, or a device-validated version tag.
