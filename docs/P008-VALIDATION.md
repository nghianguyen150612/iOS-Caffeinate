# P008 — Validation Evidence

P008 keeps Linux mock evidence separate from iOS build evidence and physical-device acceptance. The authoritative exact-SHA results are attached to the successful GitHub Actions run as `iOS-Caffeinate-P008-v0.1-cloud-attestation`; the artifact contains `release-candidate.json`, `P008-CI-ATTESTATION.md`, and a generated readiness matrix. The manifest records the source SHA and artifact hashes collected by that run.

## Local regression

On the P008 working tree, before the final commit:

```text
./scripts/build-linux-test.sh && python3 tests/integration.py
45 integration tests passed

python3 -m unittest discover -s tests/packaging -v
20 packaging tests passed
```

The integration suite uses only the explicit `IOSCAFFEINATE_TEST_MOCK` backend, which has no power effect. The package suite uses temporary Mach-O metadata fixtures; those fixtures are never used as product artifacts. The integrated smoke test covers the major P001–P007 CLI commands through the `ic` symlink. New negative cases cover unsafe/corrupt schedule state, state-write failure before assertion acquisition, invalid schedule state paths, and invalid timezone serialization.

## Hosted CI gates

The workflow preserves the four required jobs:

| Job | Evidence |
|---|---|
| `linux-protocol` | C11 mock build, integration suite, and rejection of an ungated Linux backend build |
| `ios-cross-build` | Official iPhoneOS SDK, `arm64-apple-ios12.0`, SDK/toolchain capture, CLI and daemon hashes |
| `ios-artifact-inspection` | Mach-O ARM64 device platform, iOS 12.0 minimum, dependencies, and unsigned-state verification |
| `ios-rootful-package` | Packaging tests, package build, Debian metadata/payload/mode/script/checksum inspection |

The fifth `p008-release-attestation` job runs only after all four gates succeed. It validates the test reports and artifact hashes, then generates the manifest and exact-SHA readiness evidence. It does not set a hardware result from CI.

Local Linux and package regressions pass. Final hosted results must be read from the P008 attestation artifact for the pushed source SHA. A failure in any required job blocks P008 cloud completion; no earlier milestone CI run substitutes for the final SHA.

## Package and signing evidence

The hosted package must identify `com.ioscaffeinate.cli`, version `0.1.0-1`, architecture `iphoneos-arm`, and thin `arm64-apple-ios12.0` executables. It must contain no Linux mock executable, install no active LaunchDaemon, seed no state, and report checksums for the exact archive and payload. CI package validation is read-only and does not install or sign the package.

The release candidate is labeled **UNSIGNED / DEVICE-UNVERIFIED**. CI verifies that state; it does not establish jailbreak signature acceptance or device installation readiness.

## Physical-device result

Hardware validation is **PENDING**. No iPad test was run. Follow [the consolidated P008 device acceptance plan](P008-DEVICE-ACCEPTANCE.md) only when the target and physical recovery access are available.
