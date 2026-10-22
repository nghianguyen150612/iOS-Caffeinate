# H002 — Validation Record

## Local regression results

The following checks completed on the H002 branch:

| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -v` | PASS — 312 tests, 3 skipped |
| P011 CI job command and summary parser | PASS — 55 tests, 1 optional authentic-signer test skipped |
| `python3 -m unittest discover -s tests/packaging -v` | PASS — 35 tests |
| `python3 tests/integration.py` | PASS — 55 integration scenarios |
| Selected P018/P020 package, candidate, release-gate, provenance, and end-to-end suites | PASS — 33 tests |
| `python3 scripts/check_p018_docs_shell.py` | PASS — 22 documented shell examples checked; no commands executed |
| `git diff --check` | PASS |

The Linux mock build completed before the integration and P018/P020 runs. The full Python suite includes the P011 legacy compatibility regressions and strict current-package coverage regressions.

## Published-package P011 result

The official v0.1.0 release API, source tag, package SHA-256, Debian identity, pinned sidecars, profile, archive layout, seven historical checksum records, signing metadata, Mach-O properties, and maintainer scripts passed host validation. The observed result is:

```text
status=P011_HOST_PREFLIGHT_BLOCKED
archive_sha256=VERIFIED
published_checksum_scope=LEGACY_REQUIRED_SET
published_checksum_entries=7
derived_uncovered_regular_members=52
package_structure=VERIFIED
signer_provenance=PUBLISHED_METADATA_MATCHED_PINNED_H001_IDENTITY_EXECUTABLE_MISSING
embedded_entitlements=PENDING_PINNED_LDID
signature_integrity=PENDING
device_acceptance=PENDING
```

P011 exited with status `1` because this workspace did not contain the exact H001 `ProcursusTeam/ldid` 2.1.5-procursus7 executable with SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`. The validator did not substitute another signer. This is a P011 input blocker; no iPad was accessed, and physical acceptance remains pending.

## Exact-head CI

GitHub exact-head CI is evaluated on the H002 pull request commit. This local record makes no claim that remote checks have passed. H002 may be reported complete only after all required exact-head checks pass; the P011 host-preflight pass string additionally requires the pinned H001 signer and independent embedded-entitlement validation.
