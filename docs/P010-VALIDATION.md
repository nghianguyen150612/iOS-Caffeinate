# P010 — Validation

## Deterministic local checks

```sh
./scripts/build-linux-test.sh
python3 tests/integration.py
python3 -m unittest discover -s tests/packaging -p 'test_rootful_package.py' -v
python3 -m unittest discover -s tests/packaging -p 'test_p010_signing.py' -v
python3 -m unittest discover -s tests -p 'test_p009_evidence.py' -v
dpkg --compare-versions 0.1.0~rc1-1 lt 0.1.0-1
```

The package tests use deterministic Mach-O metadata fixtures and a synthetic fixture signer. They cover exact profile contents, privileged-entitlement rejection, signer/profile opt-in, ldid command shape, signature/extractor failures, immutable input hashes, signature-only source identity, final package hashes, package-state safety, RC ordering, and release blocking. Fixture signing is a unit-test technique only; it does not claim Apple runtime signing.

The last local run on the P010 working tree passed 45 Linux integration tests, 21 rootful packaging tests, 13 P010 signing/release tests, and 55 P009 evidence tests. These are workstation results; the exact-source GitHub Actions artifact is authoritative for the PR head SHA.

The `p010-signing-release-gate` job also validates the unsigned CI package, runs the P009 tests, prepares the operator-reported evidence bundle, generates the exact-source RC manifest, and asserts that missing package acceptance keeps release authorization blocked. Existing P008 attestation remains branch-guarded to `release/p008-v01-integration`; on the P010 branch it is expected to skip and is recorded as such.

## Final-source evidence

The workflow checks out the exact pull-request head SHA and includes that SHA in the P010 manifest and test reports. The authoritative final counts and conclusions are the successful P010 workflow artifact, not an earlier local run. Required workflow jobs remain `linux-protocol`, `ios-cross-build`, `ios-artifact-inspection`, `ios-rootful-package`, `p009-evidence-validation`, and `p010-signing-release-gate`.

Hosted CI deliberately produces only unsigned artifacts; the explicit local signing flow is separate and never uploads signing keys. A local candidate, when produced, carries its own signed binary, signer, profile, and package hashes in the generated sidecar manifest. If no trusted compatible signer or exact-source candidate is available, that artifact gate remains `PENDING` or `BLOCKED`; no synthetic signature is presented as runtime verification.
