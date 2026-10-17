# P009 — Validation

P009 validation is offline. The dedicated `p009-evidence-validation` CI job runs the versioned schema checks, generated fixture integrity checks, replay and safety tests, path/file handling tests, deterministic report comparison, and P008 readiness regression assertions.

The P009 suite currently contains **55 tests**. The workflow continues to run all four product jobs on P009 branches and pull requests:

| Job | Existing coverage |
|---|---|
| `linux-protocol` | Explicit C11 mock build, 45-test integration baseline, and no ungated Linux power backend. |
| `ios-cross-build` | Official iPhoneOS SDK cross-build for iOS 12 ARM64. |
| `ios-artifact-inspection` | Mach-O platform, ARM64, minimum iOS, dependencies, and unsigned state. |
| `ios-rootful-package` | 20 packaging tests, package build, archive/payload/scripts/checksums inspection. |
| `p009-evidence-validation` | Standard-library schema validator, all synthetic cases, replay, safety, integrity, path, determinism, P008 readiness regression, and JSON/Markdown report artifacts. |

The P008 `p008-release-attestation` remains branch-specific. Its expected skip on P009 is not a P009 attestation; P009 uploads its own offline validation artifact and report.

## Local checks

```sh
python3 -m unittest discover -s tests -p 'test_p009_evidence.py' -v
python3 -m py_compile scripts/p009_evidence.py tests/p009_fixtures.py tests/test_p009_evidence.py
./scripts/build-linux-test.sh && python3 tests/integration.py
python3 -m unittest discover -s tests/packaging -v
```

P009 runs through all inputs without a network client. Tests verify that identical evidence yields identical reports and file enumeration order does not change the output. The only allowed physical `PASS` path is an explicit interactive gate review; no JSON `review_status` or CI result is sufficient.

The uploaded P009 artifact is tied to the workflow's checked-out commit. It contains the test report, validated synthetic package report, replay result, and deterministic Markdown/JSON readiness reports. Every fixture is labelled `SIMULATED` or `MOCK`; fixtures are not device observations.

## Required interpretation

Passing the P009 job establishes that the offline tools behaved as tested. It does not install or sign an artifact, execute iOS code, prove IOKit behavior, or establish locked-screen LAN/Tailscale connectivity. Physical acceptance remains `PENDING`; scheduled wake remains `UNVERIFIED`; 24/7 operation remains `NOT_VALIDATED`.
