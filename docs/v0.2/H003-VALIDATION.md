# H003 Validation Record

**Recorded:** 2026-10-22. This record separates the exact host observations from device acceptance and remote exact-head CI.

## Signer and P011 host result

| Check | Result |
|---|---|
| Digest-pinned Ubuntu build environment and signed apt snapshot | `PASS` |
| Procursus exact source commit and tree checks | `PASS` |
| Independent clean signer builds | `2/2` matched the exact pinned executable SHA-256 |
| Hash-before-version execution, ELF64 PIE and x86_64 checks | `PASS` |
| Official v0.1.0 API identity, source tag, eight assets and pinned sidecars | `PASS` |
| Actual H002 `scripts/p011_release_preflight.py` command in the pinned runtime | Exit `0` |
| H002 P011 status | `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING` |
| Embedded CLI and daemon entitlement inspection | `EXACT_MATCH` |
| Historical checksum coverage | `HISTORICALLY_PARTIAL` |
| Signature integrity / device acceptance / release authorization | `PENDING` / `PENDING` / `BLOCKED` |

The successful JSON result is [H003-P011-HOST-PREFLIGHT.json](H003-P011-HOST-PREFLIGHT.json); the independent build receipt is [H003-SIGNER-PROVENANCE.json](H003-SIGNER-PROVENANCE.json). The local authentic-artifact regression run set `P011_OFFICIAL_ASSET_DIR` and `P011_VERIFIED_LDID` to the retrieved official assets and the generated hash-verified executable. This unskipped `test_official_v010_package_passes_only_with_authentic_signer_input`.

## Local regression results

| Command/suite | Result |
|---|---|
| `python3 -m unittest discover -s tests -v` | PASS — 339 tests, 3 skipped |
| P011 tests with authentic release assets and signer | PASS — 63 tests, no skips |
| H003 signer and stack tests | PASS — 19 tests |
| P010 signing/profile tests | PASS — 13 tests |
| Rootful packaging test suite | PASS — 35 tests |
| P018 package-preflight/export/manager and P020 provenance/candidate/release-gate tests | PASS — 59 tests, 2 skipped for root ownership |
| `./scripts/build-linux-test.sh` | PASS — mock daemon and CLI compiled with warnings as errors |
| `python3 tests/integration.py` | PASS — 55 integration scenarios |
| `python3 scripts/check_p018_docs_shell.py` | PASS — 22 documented commands syntax-checked; none executed |
| Python compilation and shell syntax checks | PASS |
| `git diff --check` | PASS |

The full suite's three skips include the real-artifact P011 test when its inputs are absent and the two root-ownership-only P018 cases. The dedicated P011 run supplied the authentic inputs and passed without skips. The P020 release-gate tests continue to reject simulated evidence and keep release authorization blocked.

## GitHub exact-head CI

The H003 pull request is stacked on H002, whose exact head is `341c6840fc9d6c64876fb3a0106fd318c4dfc7c0`. The pull request CI must pass on the final H003 source SHA, including the H003 reproducible signer/P011 job, the existing Linux and macOS iOS 12 ARM64 cross-build, Mach-O inspection, package, P011–P020 tests, and the normal P020 release-readiness evaluation. GitHub Actions run URLs and conclusions belong to that exact source SHA; this local record does not promote a pending or failed remote run to PASS.

No physical iPad operation was performed. P011 device acceptance, P019 hardware observations, P020 hardware gates, signature integrity, and stable-release authorization remain pending or blocked as stated above.
