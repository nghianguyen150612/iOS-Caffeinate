# R05 Release Blocker Matrix

**Assessment date:** 2026-10-23 UTC
**Reference target:** iPad mini 2 A1489 (`iPad4,4`), iOS 12.5.7, Amethyst/Procursus rootful
**Stable v0.2.0 publication:** not authorized; no stable tag or release is created by R05.

This matrix distinguishes host validation from device evidence. A hash or CI result identifies an artifact; it does not establish installation, device trust, or runtime behavior.

## Host artifacts and source

| Item | Verified state | Evidence |
|---|---|---|
| H003 pinned Procursus `ldid` | `VERIFIED`; two independent builds matched SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`. | H003 provenance receipt and R05 reproduction; receipt SHA-256 `6a737e0c89c8cd2409ef2f9e15150c7252ea87456f1a1526061c813be473de86`. |
| Published v0.1.0 package | P011 host preflight passed for the official stable asset, package identity `com.ioscaffeinate.cli` / `0.1.0-1` / `iphoneos-arm`, SHA-256 `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c`. | Eight official release assets checked; historical archive and legacy checksum verified; package structure and exact embedded entitlements verified. Full payload checksum coverage is historically partial. |
| P011 signature integrity and physical acceptance | `PENDING`. Signature presence and entitlement inspection do not establish cryptographic trust or target-device acceptance. | R05 host report SHA-256 `edaeb800dd7d8d9e8a44fa3bad01be8d88dcea17882fe1961a606b52e33390c5`; saved under the R05 host artifact directory. |
| R05 source changes and signed RC workflow | Review/CI pending until the new exact source commit is recorded below. The RC workflow uploads a run-scoped artifact and cannot publish a tag or release. | Existing H004 starting head was `159d02efd5f2296b7caf9f07244af1487bc58ee1`; final source SHA and exact-head CI are reported with the PR. |
| Signed v0.2.0-rc1 package | Not yet produced at this assessment point. It is produced only when exact-source iOS CI, H003 signer reproduction, entitlement validation, and macOS `codesign` all pass. | Candidate artifact must include `P020-SIGNED-CANDIDATE-MANIFEST.json`, macOS signature-integrity receipt, full `SHA256SUMS`, package sidecars, and blocked P020 assessment. |

## Device and release gates

| Gate | Current classification | Required next evidence/action |
|---|---|---|
| H004 Phase 0 | `INCOMPLETE / REVIEW_PENDING`. The supplied SSH observations are preliminary, not a complete direct inspection or P009 record. | Physically attended, read-only H004 inspection; preserve actual timestamps, sources, clock basis, outputs, recovery method, and independent review. Do not fill the blank result template from this summary. |
| First-install baseline | `MISSING_FIRST_INSTALL_REVIEW_REQUIRED`. Supplied observations report package absent, no standard project binaries/process/socket/lock/launchd registration/live plist, and no P014 journal. A missing journal alone does not establish a safe baseline. | Establish known prior runtime/assertion history and direct assertion-owner/cleanup state. Unknown ownership or history remains a stop. No journal reset is part of H004. |
| Package database audit | `REVIEW_REQUIRED`. SSH notes report warnings involving virtual hardware-capability packages; five representative packages were reported installed and payload-empty. | Capture complete `dpkg --audit` output and package identities on device; independent review must resolve or explicitly bound the warnings before installation. Five samples do not establish the state of every warning. |
| P011 v0.1.0 acceptance | `PENDING`. Host validation passed; device installation, execution, bounded assertion, stop, cleanup, state preservation, and rollback have not been accepted. | Complete H004 and the attended P011 steps with separate authorization for installation and each other state-changing operation. |
| v0.2.0-rc1 installed identity and execution | `PENDING`. No RC package has been installed or run on the device. | Verify exact RC artifact SHA and source manifest, then perform separately authorized attended installation only after the P011/Phase 0 gates pass. Record AMFI/codesign logs and actual CLI/daemon results. |
| P012 physical trials | `PENDING`. | Complete the protocol's 24 valid physical trials and analysis; do not derive trials from CI or SSH anecdotes. |
| P013 lifecycle | `PENDING`. | Attended lifecycle checks with launchd kept disabled unless a separate authorization permits a specific test. |
| P014 recovery and cleanup | Source behavior remains fail-closed and regression coverage is added. Physical first-install, expiry, STOP, SIGTERM, and recovery acceptance are `PENDING`. | Review direct assertion cleanup first. If a first-run journal is absent after authorization, use the documented root-only reviewed reset before daemon startup; preserve corrupt/unsafe journals and unknown ownership. |
| P016 resource review | `PENDING`. | Record battery and thermal availability/observations during supervised tests. |
| P018 privacy and P009 evidence review | `PENDING`. | Preserve raw P009 privately and unchanged; review the sanitized P018 export independently and bind both to actual evidence hashes. |
| P019 reliability | `PENDING`. | Complete 12 bounded attended 180-second cycles across three distinct dates with independent review, in addition to P012 trial requirements. This is not 24/7 validation. |
| P020 candidate-bound P010 evidence | `PENDING`. H003 signer provenance is available, while P020 still requires signed candidate-bound evidence and independent review. | Admit only the exact RC's source, package, signed binary hashes, profile, signer receipt, and verification outcome; obtain the required external review. |
| Stable v0.2.0 release | `RELEASE_BLOCKED`; `publication_authorized=false`. | Satisfy all physical gates and signed reviewer receipts, rerun the exact P020 evaluator, and obtain explicit human publication approval as a separate action. |

## Supplied SSH observations (preliminary only)

The operator reports `iPad4,4`, iOS 12.5.7, and `iphoneos-arm` rootful; package `com.ioscaffeinate.cli` absent; no CLI or daemon at standard paths; no observed project daemon process, socket, lock, registered launchd label, or live plist; and no existing P014 recovery journal. These observations are useful for planning the attended inspection but lack the complete command log, timestamps/timebase, direct physical recovery confirmation, full package audit, and independent review required for H004/P011 acceptance.

The package database warning summary remains open for review. No package names or additional audit results are inferred here. No physical device command, package installation, journal mutation, stable publication, or release authorization was performed for R05.
