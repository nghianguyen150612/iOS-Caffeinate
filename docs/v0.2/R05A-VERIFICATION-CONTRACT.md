# R05A Signature Verification Contract

The candidate workflow keeps Apple host verification, independent signature-integrity validation, entitlement matching, and device acceptance as separate results. It finalizes only after the first three pass for the same exact-source package and both executables.

| Result | Required evidence | Meaning |
|---|---|---|
| `APPLE_CODESIGN_VERIFIED` | `/usr/bin/codesign --verify --strict --verbose=4` exits 0 for both exact package binaries | Apple's host verifier accepted these files on the recorded macOS host |
| `INDEPENDENT_CODEDIRECTORY_VERIFIED` | Bounded parser validates architecture, load commands, signature placement, SuperBlob layout, CodeDirectory fields, every executable-page hash, and requirements/entitlement special-slot hashes | Independently computed byte-integrity checks passed |
| `ENTITLEMENTS_EXACT_MATCH` | XML and DER blobs are linked by verified special-slot hashes and contain only `com.apple.private.security.no-container=true` | Embedded entitlements match the approved profile |
| `EMPTY_DESIGNATED_REQUIREMENTS` | Requirements SuperBlob has count 0 and matches the explicitly pinned empty-profile digest | No certificate identity requirement is embedded in the ad hoc signature |
| `DEVICE_SIGNATURE_ACCEPTANCE_PENDING` | Always pending in cloud-only workflows | No claim about iOS installation, AMFI behavior, runtime, or device trust |

The production signing identity remains ProcursusTeam `ldid` 2.1.5-procursus7 at SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`. The entitlement profile remains `amethyst-ios12-rootful`, SHA-256 `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca`, with exactly one entitlement: `com.apple.private.security.no-container=true`.

The signature requirements input is `EMPTY_REQUIREMENTS_SUPERBLOB`, exactly `fade0c010000000c00000000`, SHA-256 `987920904eab650e75788c054aa0b0524e6a80bfc71aa32df8d237a61743f986`. The command remains the same pinned signer with the approved entitlement profile: `ldid -Cadhoc -Q<empty-requirements.superblob> -S<profile> <binary>`. The package builder, RC validator, macOS verifier, finalizer, and final manifest all bind this profile. Nonempty designated requirements block the RC, even if Apple's command exits zero.

The signed-input manifest and receipt bind source commit, package filename and digest, both binary digests, signer, profile, requirements profile, and exact workflow run ID and attempt. The finalizer accepts only a `VERIFIED` schema-v2 macOS receipt from that same workflow run and attempt, with exit 0 for both Apple commands, both independent signature audits, exact entitlements, and empty requirements. It validates the package with the pinned signer again, confirms binaries did not change during metadata-only repackaging, and verifies the final package from a fresh extraction. Missing, failed, mismatched, or copied receipts block finalization.

The `codesign --version` probe is retained only as environment evidence because Apple tool versions may reject the query. It does not determine the candidate result. Both exact package binaries must pass strict `codesign` and the independent CodeDirectory and entitlement audit.

`INDEPENDENT_CODEDIRECTORY_VERIFIED` never substitutes for `APPLE_CODESIGN_VERIFIED`. Apple's native ad hoc diagnostic output is isolated and cannot enter the finalizer. A successful host result leaves device acceptance pending and authorizes no transfer, installation, runtime mutation, tag creation, stable publication, or physical qualification.
