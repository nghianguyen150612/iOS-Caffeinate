# H003 Milestone Manifest

## Scope and Git stack

| Field | Value |
|---|---|
| Repository | `nghianguyen150612/iOS-Caffeinate` |
| H003 branch | `fix/h003-p011-signer-preflight` |
| Review base | `fix/h002-p011-legacy-checksum` |
| H002 starting commit | `341c6840fc9d6c64876fb3a0106fd318c4dfc7c0` |
| P020 predecessor branch/head | `release/p020-v02-integration` / `57b06c534d18f094ad59e4229e626fae51668de9` |
| Stable v0.1.0 release mutation | None |
| v0.2 tag/release mutation | None |

The H003 stack validator requires the exact open H002 and P020 predecessor heads, H003 ancestry over H002, and unchanged P011–P020 ancestry. H003 extends the P020 integration-base validation and does not weaken P020 release-readiness rules.

## Build and P011 identity

| Claim | Recorded result |
|---|---|
| Procursus source commit/tree | `aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef` / `e473e8213e9821e986ac488ced802f5ee2b4bbea` |
| Newly recorded environment | Ubuntu 24.04 `linux/amd64`, digest-pinned image and signed dated apt snapshot in `scripts/h003-build-inputs.lock` |
| Independent executable hashes | Both equal the pinned P010 SHA-256 |
| H003 host preflight | `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING` |
| Signature integrity | `PENDING` |
| Device acceptance | `PENDING` |
| Release authorization | `BLOCKED` |

The H001 environment receipt was unavailable. H003's new environment is not claimed to be the historical H001 image or package snapshot. The JSON receipts are [H003-SIGNER-PROVENANCE.json](H003-SIGNER-PROVENANCE.json) and [H003-P011-HOST-PREFLIGHT.json](H003-P011-HOST-PREFLIGHT.json).

## H003 files

| Path | Purpose |
|---|---|
| `scripts/h003-build-inputs.lock` | Exact source, image, snapshot, package, toolchain, version, and executable pins |
| `scripts/h003_signer.py` | Source/image/dependency validation, two clean builds, hash-before-execution, ELF inspection, and JSON provenance |
| `scripts/h003_build_signer.sh` | Host command to build into an empty private output directory |
| `scripts/h003_build_signer_container.sh` | Signed snapshot setup and locked in-container build |
| `scripts/h003_fetch_release_assets.py` | Exact public v0.1.0 asset retrieval through P011's release verifier |
| `scripts/h003_run_p011_preflight_container.sh` | Digest-pinned host wrapper, read-only package mounts, CA/proxy forwarding, and report handling |
| `scripts/h003_p011_preflight_container.sh` | Locked P011 runtime dependencies and H002 command execution |
| `scripts/h003_stack.py` | Strict H003/H002/P020 PR stack contract |
| `.github/workflows/h003-p011-authentic-host-preflight.yml` | Rebuild, release retrieval, authentic P011 run, exact-source receipts |
| `tests/test_h003_signer.py` | Signer input, identity, reproduction, and fail-closed tests |
| `tests/test_h003_stack.py` | H003 stack and predecessor-integrity tests |
| `docs/v0.2/H003-P011-HOST-PREFLIGHT.json` | Actual successful P011 host result |
| `docs/v0.2/H003-SIGNER-PROVENANCE.json` | Actual two-build source and environment receipt |
| `docs/v0.2/H003-ARCHITECTURE.md`, `H003-REPRODUCIBLE-BUILD.md`, `H003-SIGNER-PROVENANCE.md`, `H003-P011-HOST-PREFLIGHT.md`, `H003-VALIDATION.md` | Architecture, repeatable commands, observed results, and limits |

## Safety record

No physical iPad operation, package/device installation, service activation, assertion acquisition, package repackaging, re-signing, v0.2 release, or merge was performed. The P011 package and sidecars were validated as published. The generated host signer is retained only outside the repository; CI uploads receipts and reports, not the executable or package.
