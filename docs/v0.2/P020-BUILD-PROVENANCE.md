# P020 Build Provenance and Reproducibility

## Candidate stages

| Stage | Identity | State in P020 |
|---|---|---|
| Unsigned development build | Exact P020 source, iPhoneOS SDK, ARM64 binaries and isolated `.deb` | Prepared by CI; explicitly unsigned and device-unverified |
| Signed candidate | Same source and payload with verified P010 signer and approved profile | Blocked: pinned signer executable and origin are unavailable |
| Device-tested candidate | Exact signed package installed under attended authorization | Not performed |
| Hardware-accepted candidate | Required P011/P012/P013/P014/P016/P018/P019 evidence accepted | Pending physical evidence and independent review |
| Stable v0.2.0 | Stable package and public release | Not authorized or published |

The candidate version is `0.2.0~rc1-1`, which Debian orders before `0.2.0-1`. The repository default remains `0.1.0-1`; P020 passes the RC version to an isolated output path and does not replace the stable package.

## Provenance contract

`P020-BUILD-PROVENANCE.schema.json` requires the exact source commit and tree, worktree state, target triple and deployment target, build flags, Xcode/Clang/SDK identity, `dpkg-deb` version, source-derived `SOURCE_DATE_EPOCH`, dependency inventory, package identity, binary and package hashes, signing state and profile hash, CI workflow/run, validation results, and a reproducibility result. It excludes absolute SDK and runner paths.

`python3 scripts/p020_build_provenance.py capture` compares two builds from separate clean checkouts under recorded inputs. It reports:

- `REPRODUCIBLE` only when source/toolchain/package inputs match and both binaries and `.deb` bytes match.
- `NON_REPRODUCIBLE` when recorded inputs match but bytes differ; the report includes first differing offsets and lengths for review.
- `INCONCLUSIVE` when the recorded inputs differ.
- `NOT_TESTED` when a comparison has not been run.

Matching source SHAs alone do not establish reproducibility. Even identical unsigned builds do not establish signing, installation, or device behavior.

## Signing identity

The required signer is `ldid 2.1.5-procursus7`, SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`, built from `https://github.com/ProcursusTeam/ldid.git` at commit `aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef`. The approved profile is `amethyst-ios12-rootful`, SHA-256 `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca`. Both exact tool identity and verifiable origin, exact profile bytes, signed binary and package hashes, signing command/result, embedded entitlement inspection, and source-to-signed-binary relationship must be recorded. A matching version string is insufficient.

P020 does not execute an unverified signer and does not create a substitute profile. Until the exact signer is verified, provenance must say `SIGNER_PROVENANCE_BLOCKED` and packages remain unsigned.

## Artifact verification

The candidate workflow checks ARM64 Mach-O slices, iOS deployment metadata, dynamic dependencies, payload checksums, package name/version/architecture, paths and modes, inert launchd template, maintainer scripts, absence of seeded persistent data, secret markers and runner paths. These checks are package inspection only; they are not iOS signature acceptance or device testing. CI stores the exact source/tree, both build-info records, both packages, hashes, inspection reports, and generated provenance as run-scoped artifacts.
